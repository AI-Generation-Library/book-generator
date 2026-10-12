from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from .manuscript import chapter_href, clean_markdown, finalize, frontmatter, write_artifact
from .models import BookConfig, BookPlan
from .prompts import SYSTEM, chapter_prompt, demo_chapter, demo_plan, plan_prompt
from .providers import Provider, ProviderError, parse_plan
from .storage import canonical, digest, inside, run_lock, run_path, save_json


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(run: Path) -> dict:
    return json.loads(inside(run, "checkpoint.json").read_text(encoding="utf-8"))


def create_run(root: Path, config: BookConfig, key: str = "") -> Path:
    config.ensure_ready()
    if key and key in config.model_dump_json():
        raise ValueError("API 키를 제목·주제·목차·설정에 넣지 마세요.")
    base = canonical(root)
    base.mkdir(parents=True, exist_ok=True)
    run = run_path(base, uuid4().hex)
    run.mkdir()
    state = {
        "version": 1,
        "run_id": run.name,
        "created": now(),
        "updated": now(),
        "status": "ready",
        "stage": "plan",
        "config": config.model_dump(),
        "completed_chapters": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "reserved_tokens": 0,
        "calls": [],
        "files": {},
        "message": "생성을 준비했습니다.",
        "archive": None,
    }
    save_json(inside(run, "checkpoint.json"), state)
    return run


def public_state(run: Path) -> dict:
    state = load_state(run)
    result = {
        key: state[key]
        for key in (
            "run_id",
            "created",
            "updated",
            "status",
            "stage",
            "config",
            "completed_chapters",
            "input_tokens",
            "output_tokens",
            "reserved_tokens",
            "message",
            "archive",
        )
    }
    result.update(origin=state.get("origin", "api"), author=state.get("author"))
    return result


class BudgetPause(Exception):
    pass


async def execute(
    run: Path,
    provider: Provider | None,
    *,
    output_budget: int | None = None,
    max_output_tokens: int | None = None,
    on_update=None,
) -> dict:
    """Reserve before each network call so an interrupted call never silently resets its budget."""
    with run_lock(run):
        state = load_state(run)
        config = BookConfig.model_validate(state["config"])
        if state["status"] == "completed":
            if provider:
                provider.forget_key()
            return state
        changes = {}
        if output_budget is not None:
            changes["output_budget"] = output_budget
        if max_output_tokens is not None:
            changes["max_output_tokens"] = max_output_tokens
        config = BookConfig.model_validate({**config.model_dump(), **changes})
        config.ensure_ready()
        state["config"] = config.model_dump()
        if not config.demo and provider is None:
            raise ValueError("API 키가 필요합니다.")
        for relative, expected in state["files"].items():
            path = inside(run, relative)
            if not path.is_file() or digest(path) != expected:
                raise ValueError(
                    "기존 원고가 수정되었습니다. 덮어쓰지 않고 중단합니다. 수정본은 별도 보관 후 재개하세요."
                )

        def persist(message=None):
            if message:
                state["message"] = message
            state["updated"] = now()
            save_json(inside(run, "checkpoint.json"), state)
            if on_update:
                on_update(public_state(run))

        async def request(prompt: str, *, structured=False) -> str:
            available = config.output_budget - state["output_tokens"] - state["reserved_tokens"]
            # Reserve a complete per-call allowance, rather than silently requesting a tiny truncated chapter.
            limit = min(config.max_output_tokens, 8000) if structured else config.max_output_tokens
            if available < limit:
                raise BudgetPause(
                    "남은 출력 예산이 다음 호출 한도보다 작습니다. 전체 예산을 늘려 재개하세요."
                )
            call = {"stage": state["stage"], "started": now(), "limit": limit, "status": "pending"}
            state["calls"].append(call)
            state["reserved_tokens"] += limit
            persist("AI 응답을 기다리고 있습니다.")
            result = await provider.complete(SYSTEM, prompt, limit, structured=structured)
            state["reserved_tokens"] -= limit
            state["input_tokens"] += result.input_tokens
            state["output_tokens"] += result.output_tokens
            call.update(
                status="received",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                finished=now(),
                truncated=result.truncated,
            )
            text = result.text.replace(provider._key, "[REDACTED API KEY]") if provider._key else result.text
            relative = f"responses/{len(state['calls']):03d}.txt"
            write_artifact(run, state, relative, text)
            persist()
            if result.truncated or not text.strip():
                raise ValueError(
                    "AI 응답이 비었거나 중간에 끝났습니다. 응답은 보존했습니다. 한도·모델을 확인하고 재개하세요."
                )
            return text

        state["status"] = "running"
        persist(
            "목차를 기획하고 있습니다." if state["stage"] == "plan" else "저장한 원고부터 이어서 작성합니다."
        )
        try:
            plan_file = inside(run, "plan.json")
            if "plan.json" not in state["files"]:
                if config.demo:
                    plan = demo_plan(config)
                else:
                    text = await request(plan_prompt(config), structured=True)
                    plan = BookPlan.model_validate(parse_plan(text))
                if len(plan.chapters()) != config.chapter_count:
                    raise ValueError("생성된 목차의 장 수가 요청과 다릅니다. 응답을 검토한 뒤 재개하세요.")
                write_artifact(run, state, "plan.json", plan.model_dump_json(indent=2) + "\n")
                state["stage"] = "chapters"
                persist("목차를 저장했습니다. 장별 원고를 작성합니다.")
            else:
                plan = BookPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
            for number, (part, chapter) in enumerate(plan.chapters(), 1):
                if number in state["completed_chapters"]:
                    continue
                state["stage"] = f"chapter-{number}"
                persist(f"{number}/{config.chapter_count}장 · {chapter.title}")
                text = (
                    demo_chapter(config, number, chapter)
                    if config.demo
                    else await request(chapter_prompt(config, plan, number, chapter))
                )
                body = frontmatter(
                    f"{number:02d}장. {chapter.title}", chapter.summary, config, chapter=number, part=part
                ) + clean_markdown(text)
                write_artifact(run, state, f"book/{config.id}/{chapter_href(number)}.md", body)
                state["completed_chapters"].append(number)
                persist(f"{number}/{config.chapter_count}장 저장 완료")
                await asyncio.sleep(0)  # Cancellation is observed even during the offline demo.
            state["stage"] = "package"
            persist("콘텐츠 형식을 검사하고 ZIP을 만듭니다.")
            finalize(run, state, config, plan)
            state["status"] = "completed"
            state["stage"] = "done"
            persist("원고 생성과 파일 형식 검사가 완료되었습니다. 내용 검토 후 공개하세요.")
        except asyncio.CancelledError:
            state["status"] = "paused"
            persist("중단했습니다. 진행 중이던 호출은 과금될 수 있어 예약 출력 한도를 유지합니다.")
            raise
        except BudgetPause as error:
            state["status"] = "paused"
            persist(str(error))
        except (ProviderError, ValueError) as error:
            state["status"] = "failed"
            # ValidationError includes input values by default, so never expose its rendering.
            message = (
                "목차 JSON 형식이 올바르지 않습니다. 저장된 응답을 검토하고 재개하세요."
                if isinstance(error, (ValidationError, json.JSONDecodeError))
                else str(error)
            )
            persist(message)
        except Exception:
            state["status"] = "failed"
            persist("작업 파일을 처리하지 못했습니다. 로컬 파일 권한·남은 공간을 확인하고 재개하세요.")
        finally:
            if provider:
                provider.forget_key()
        return state

"""Package authored manuscripts without claiming to have generated them through an API."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .engine import now
from .manuscript import chapter_href, clean_markdown, finalize, frontmatter, write_artifact
from .models import BookConfig, BookPlan
from .storage import canonical, inside, run_path, save_json


def package_manuscript(
    root: Path, config: BookConfig, plan: BookPlan, source: Path, author: str, model: str | None = None
) -> Path:
    """Input: NN-chapter/chapter.md plus optional appendices/templates/examples."""
    if config.demo:
        raise ValueError("외부 원고를 데모로 표시하지 않습니다. config.demo를 false로 설정하세요.")
    if len(plan.chapters()) != config.chapter_count:
        raise ValueError("목차의 장 수와 설정의 chapter_count가 다릅니다.")
    if not author.strip() or len(author) > 200 or (model is not None and not model.strip()):
        raise ValueError("실제 작성 도구와 확인된 모델명만 입력하세요.")
    manuscript = canonical(source)
    prepared = []
    for number, (part, chapter) in enumerate(plan.chapters(), 1):
        path = inside(manuscript, chapter_href(number) + ".md")
        if not path.is_file():
            raise ValueError(f"{number}장 원고가 없습니다.")
        text = clean_markdown(path.read_text(encoding="utf-8-sig"))
        prepared.append((number, part, chapter, text))
    extras = []
    for directory in ("appendices", "templates", "examples"):
        folder = inside(manuscript, directory)
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_symlink() or not canonical(path).is_relative_to(manuscript):
                raise ValueError("원고 안의 symlink·junction을 가져오지 않습니다.")
            if not path.is_file():
                continue
            relative = path.relative_to(manuscript).as_posix()
            if relative == "appendices/verification.md":
                raise ValueError("검증 기록은 패키징 후 실제 확인한 범위로 작성하세요.")
            if path.name.startswith(".env") or path.suffix not in {
                ".md",
                ".csv",
                ".json",
                ".yaml",
                ".yml",
                ".txt",
                ".py",
            }:
                raise ValueError("공개할 텍스트 원고와 실습 자료만 가져옵니다.")
            extras.append((relative, path.read_text(encoding="utf-8-sig")))
    base = canonical(root)
    if base == manuscript or base.is_relative_to(manuscript):
        raise ValueError("출력 폴더는 입력 원고 폴더와 분리하세요.")
    base.mkdir(parents=True, exist_ok=True)
    run = run_path(base, uuid4().hex)
    run.mkdir()
    state = {
        "version": 1,
        "run_id": run.name,
        "created": now(),
        "updated": now(),
        "status": "ready",
        "stage": "package",
        "config": config.model_dump(),
        "origin": "external-manuscript",
        "author": author.strip(),
        "completed_chapters": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "reserved_tokens": 0,
        "calls": [],
        "files": {},
        "archive": None,
        "message": "저자가 제공한 원고를 정리합니다. API를 호출하지 않습니다.",
    }
    write_artifact(run, state, "plan.json", plan.model_dump_json(indent=2) + "\n")
    write_artifact(run, state, f"book/{config.id}/approved-plan.json", plan.model_dump_json(indent=2) + "\n")
    for number, part, chapter, text in prepared:
        body = (
            frontmatter(
                f"{number:02d}장. {chapter.title}", chapter.summary, config, chapter=number, part=part
            )
            + text
        )
        write_artifact(run, state, f"book/{config.id}/{chapter_href(number)}.md", body)
        state["completed_chapters"].append(number)
    for relative, text in extras:
        write_artifact(run, state, f"book/{config.id}/{relative}", text)
    authorship = {
        "generator": f"{author.strip()} · AI Generation Library book-generator (packaging)",
        "provider": "external-manuscript",
        "model": model,
        "source": "저자가 제공한 승인 목차와 원고. generation-input.json과 approved-plan.json에 작성 지시와 출처를 기록.",
    }
    finalize(run, state, config, plan, authorship=authorship)
    state.update(
        status="completed",
        stage="done",
        updated=now(),
        message="외부 원고 정리와 콘텐츠 형식 검사가 완료되었습니다. API를 호출하지 않았습니다.",
    )
    save_json(inside(run, "checkpoint.json"), state)
    return run

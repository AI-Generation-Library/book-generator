from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .engine import create_run, execute, load_state, public_state
from .models import BookConfig, StrictModel
from .providers import Provider
from .storage import canonical, inside, run_path


class StartRequest(StrictModel):
    config: BookConfig
    api_key: SecretStr = Field(default=SecretStr(""), exclude=True, max_length=1000)


class ResumeRequest(StrictModel):
    api_key: SecretStr = Field(default=SecretStr(""), exclude=True, max_length=1000)
    output_budget: int | None = Field(default=None, ge=512, le=2000000)
    max_output_tokens: int | None = Field(default=None, ge=512, le=32000)


def create_app(output_root: Path = Path("generated"), provider_factory=Provider) -> FastAPI:
    root = canonical(output_root)
    root.mkdir(parents=True, exist_ok=True)
    static = Path(__file__).parent / "static"
    csrf = secrets.token_urlsafe(32)
    active: dict[str, asyncio.Task] = {}
    errors: dict[str, str] = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        for task in list(active.values()):
            task.cancel()
        await asyncio.gather(*list(active.values()), return_exceptions=True)

    app = FastAPI(
        title="AI Generation Library · book-generator",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.output_root = root
    app.state.active = active

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Pydantic's default response can echo the input, including an API key.
        return JSONResponse(
            {"detail": "입력 형식과 필수 항목·범위를 확인하세요. API 키는 응답에 포함하지 않습니다."},
            status_code=422,
        )

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = "http://" + request.headers.get("host", "")
            if origin is not None and origin != expected:
                return JSONResponse({"detail": "같은 로컬 화면에서 실행하세요."}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-generator-token", ""), csrf):
                return JSONResponse({"detail": "로컬 화면을 새로 열고 실행하세요."}, status_code=403)
        try:
            size = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return JSONResponse({"detail": "유효하지 않은 요청 길이입니다."}, status_code=400)
        if size > 200000:
            return JSONResponse({"detail": "요청이 너무 큽니다."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def existing(run_id):
        try:
            run = run_path(root, run_id)
            if not inside(run, "checkpoint.json").is_file():
                raise ValueError()
            return run
        except ValueError:
            raise HTTPException(404, "작업을 찾을 수 없습니다.") from None

    def key_for(config, secret):
        value = secret.get_secret_value().strip()
        if not config.demo and (not value or any(character in value for character in "\r\n")):
            raise HTTPException(400, "API 키를 입력하세요. 저장하지 않으며 실행 중에만 사용합니다.")
        if value and value in config.model_dump_json():
            raise HTTPException(400, "API 키를 책 내용이나 설정에 넣지 마세요.")
        return value

    async def work(run, provider, **changes):
        try:
            await execute(run, provider, **changes)
        except asyncio.CancelledError:
            pass
        except Exception:
            # Do not print exceptions carrying request or provider data.
            # Do not rewrite a checkpoint owned by another process holding its OS lock.
            errors[run.name] = (
                "작업이 다른 프로세스에서 실행 중이거나 파일이 변경되었습니다. 로컬 파일을 확인하세요."
            )
        finally:
            if provider:
                provider.forget_key()
            active.pop(run.name, None)

    def launch(run, config, key, **changes):
        if run.name in active:
            raise HTTPException(409, "작업이 이미 실행 중입니다.")
        if len(active) >= 2:
            raise HTTPException(409, "동시에 실행할 수 있는 작업은 두 개입니다.")
        provider = None if config.demo else provider_factory(config, key)
        errors.pop(run.name, None)
        task = asyncio.create_task(work(run, provider, **changes))
        active[run.name] = task

        def settled(finished):
            # A task cancelled before its coroutine starts never enters work's finally block.
            if provider:
                provider.forget_key()
            if active.get(run.name) is finished:
                active.pop(run.name, None)

        task.add_done_callback(settled)

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return (static / "index.html").read_text(encoding="utf-8")

    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/api/session")
    async def session():
        return {"token": csrf, "providers": ["openai", "claude", "gemini"]}

    @app.get("/api/runs")
    async def runs():
        result = []
        for path in root.iterdir():
            try:
                run = existing(path.name)
                item = public_state(run)
                item["active"] = run.name in active
                if run.name in errors:
                    item.update(status="failed", message=errors[run.name])
                result.append(item)
            except (HTTPException, ValueError, OSError, json.JSONDecodeError, KeyError):
                continue
        return sorted(result, key=lambda item: item["created"], reverse=True)[:100]

    @app.post("/api/runs", status_code=202)
    async def start(body: StartRequest):
        key = key_for(body.config, body.api_key)
        try:
            body.config.ensure_ready()
            if len(active) >= 2:
                raise HTTPException(409, "동시에 실행할 수 있는 작업은 두 개입니다.")
            run = create_run(root, body.config, key)
        except ValueError:
            raise HTTPException(400, "책 ID와 모델 ID, 입력 내용을 확인하세요.") from None
        launch(run, body.config, key)
        key = ""
        return public_state(run)

    @app.get("/api/runs/{run_id}")
    async def detail(run_id: str):
        run = existing(run_id)
        item = public_state(run)
        item["active"] = run.name in active
        if run.name in errors:
            item.update(status="failed", message=errors[run.name])
        return item

    @app.post("/api/runs/{run_id}/resume", status_code=202)
    async def resume(run_id: str, body: ResumeRequest):
        run = existing(run_id)
        state = load_state(run)
        if state["status"] == "completed":
            raise HTTPException(409, "이미 완성된 작업입니다.")
        config = BookConfig.model_validate(state["config"])
        key = key_for(config, body.api_key)
        launch(run, config, key, output_budget=body.output_budget, max_output_tokens=body.max_output_tokens)
        key = ""
        return public_state(run)

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    async def cancel(run_id: str):
        existing(run_id)
        if run_id not in active:
            raise HTTPException(409, "실행 중인 작업이 없습니다.")
        active[run_id].cancel()
        return {"message": "중단 요청을 보냈습니다. 진행 중이던 API 호출은 과금될 수 있습니다."}

    @app.get("/api/runs/{run_id}/download")
    async def download(run_id: str):
        run = existing(run_id)
        state = load_state(run)
        if state["status"] != "completed" or not state["archive"]:
            raise HTTPException(409, "완성된 작업의 ZIP만 내려받을 수 있습니다.")
        path = inside(run, state["archive"])
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.get("/api/runs/{run_id}/preview", response_class=JSONResponse)
    async def preview(run_id: str, chapter: int = 1):
        run = existing(run_id)
        state = load_state(run)
        if chapter not in state["completed_chapters"]:
            raise HTTPException(404, "저장된 장을 선택하세요.")
        config = BookConfig.model_validate(state["config"])
        path = inside(run, f"book/{config.id}/{chapter:02d}-chapter/chapter.md")
        # The browser displays plain text. Generated HTML/code is never executed.
        return {"markdown": path.read_text(encoding="utf-8")}

    return app

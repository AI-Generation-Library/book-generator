from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import warnings
from pathlib import Path

from pydantic import ValidationError

from .book_metadata import validate_book
from .engine import create_run, execute, load_state
from .manuscript import export_book
from .models import BookConfig
from .providers import Provider
from .storage import canonical

ENV_KEYS = {"openai": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}


def get_key(config):
    if config.demo:
        return ""
    key = os.environ.get(ENV_KEYS[config.provider], "").strip()
    if not key:
        if not sys.stdin.isatty():
            raise ValueError(f"{ENV_KEYS[config.provider]} 환경 변수 또는 대화형 API 키 입력이 필요합니다.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                key = getpass.getpass(f"{config.provider} API 키 (표시·저장하지 않음): ").strip()
        except getpass.GetPassWarning:
            raise ValueError(
                "이 터미널은 숨김 입력을 지원하지 않습니다. 환경 변수 또는 로컬 웹 화면을 사용하세요."
            ) from None
    if not key or any(character in key for character in "\r\n"):
        raise ValueError("유효한 API 키가 필요합니다.")
    return key


def progress(state):
    print(
        f"[{state['status']}] {state['message']} · 출력 {state['output_tokens']:,} / 예약 {state['reserved_tokens']:,}",
        flush=True,
    )


def parser():
    root = argparse.ArgumentParser(prog="book-generator", description="사용자 API 키로 만드는 로컬 책 생성기")
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="로컬 웹 화면 열기")
    serve.add_argument("--port", type=int, default=8090)
    serve.add_argument("--output", type=Path, default=Path("generated"))
    generate = commands.add_parser("generate", help="기획과 장별 원고 생성")
    generate.add_argument("--config", required=True, type=Path)
    generate.add_argument("--output", type=Path, default=Path("generated"))
    generate.add_argument("--demo", action="store_true", help="API를 호출하지 않는 데모 원고")
    resume = commands.add_parser("resume", help="체크포인트부터 이어서 생성")
    resume.add_argument("run", type=Path)
    resume.add_argument("--output-budget", type=int)
    resume.add_argument("--max-output-tokens", type=int)
    validate = commands.add_parser("validate", help="완성된 책의 콘텐츠 형식 검사")
    validate.add_argument("book", type=Path)
    export = commands.add_parser("export", help="books 체크아웃에 원고 복사 (덮어쓰기 금지)")
    export.add_argument("run", type=Path)
    export.add_argument("--books", required=True, type=Path)
    return root


def main(argv=None) -> int:
    # Preserve Korean messages when PowerShell captures or redirects output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            import uvicorn

            from .web import create_app

            if not 1 <= args.port <= 65535:
                raise ValueError("유효한 포트를 지정하세요.")
            print(f"로컬 웹 화면: http://127.0.0.1:{args.port}/", flush=True)
            uvicorn.run(
                create_app(args.output),
                host="127.0.0.1",
                port=args.port,
                access_log=False,
                log_level="warning",
            )
            return 0
        if args.command == "validate":
            meta = validate_book(canonical(args.book))
            print(f"콘텐츠 형식 검사 통과: {meta['id']} · {len(meta['chapters'])}장 (내용 검수는 별도)")
            return 0
        if args.command == "export":
            target = export_book(canonical(args.run), args.books)
            print(f"원고 복사 완료: {target}\nbooks의 validate-books.py로 검사하고 검토 후 PR을 제출하세요.")
            return 0
        if args.command == "generate":
            values = json.loads(args.config.read_text(encoding="utf-8-sig"))
            if args.demo:
                values["demo"] = True
            config = BookConfig.model_validate(values)
            config.ensure_ready()
            key = get_key(config)
            run = create_run(args.output, config, key)
        else:
            run = canonical(args.run)
            saved = load_state(run)
            config = BookConfig.model_validate(saved["config"])
            if saved["status"] == "completed":
                print(f"이미 완성된 작업입니다. 책 폴더: {run / 'book' / config.id}")
                return 0
            key = get_key(config)
        print(f"작업 폴더: {run}", flush=True)
        provider = None if config.demo else Provider(config, key)
        key = ""
        try:
            state = asyncio.run(
                execute(
                    run,
                    provider,
                    output_budget=getattr(args, "output_budget", None),
                    max_output_tokens=getattr(args, "max_output_tokens", None),
                    on_update=progress,
                )
            )
        finally:
            if provider:
                provider.forget_key()
        if state["status"] == "completed":
            print(f"책 폴더: {run / 'book' / config.id}\nZIP: {run / state['archive']}")
            return 0
        print(f'재개: book-generator resume "{run}"', flush=True)
        return 2
    except KeyboardInterrupt:
        print(
            "\n중단했습니다. 저장된 작업 폴더로 resume을 실행하세요. 진행 중 API 호출은 과금될 수 있습니다."
        )
        return 130
    except (ValidationError, json.JSONDecodeError):
        print("설정 JSON의 필드·값·범위를 확인하세요. API 키는 JSON에 넣지 마세요.", file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        # All ValueErrors raised by our authoring code use key-free fixed explanations.
        print(
            "작업 오류: "
            + (str(error) if isinstance(error, ValueError) else "파일 경로와 접근 권한을 확인하세요."),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

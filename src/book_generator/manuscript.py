from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .book_metadata import validate_book
from .models import BookConfig, BookPlan
from .storage import atomic_text, canonical, digest, inside


def frontmatter(title: str, description: str, config: BookConfig, **fields) -> str:
    data = {
        "title": title,
        "description": description,
        "tags": config.tags,
        "created": date.today().isoformat(),
        "modified": date.today().isoformat(),
        "enableToc": True,
        **fields,
    }
    return (
        "---\n"
        + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in data.items())
        + "\n---\n\n"
    )


def chapter_href(number: int) -> str:
    # Fixed ASCII paths keep model-generated titles out of filesystem paths.
    return f"{number:02d}-chapter/chapter"


def clean_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```markdown\n") and text.endswith("```"):
        text = text[len("```markdown\n") :].rsplit("```", 1)[0].strip()
    if text.startswith("---") or not text.startswith("# ") or len(text) < 250:
        raise ValueError("원고에 제목과 충분한 본문이 필요합니다. 응답은 저장했으므로 검토 후 재개하세요.")
    # Detect unfinished fences including tilde fences without interpreting generated code.
    opened = None
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if not match:
            continue
        fence, tail = match.groups()
        if opened is None:
            opened = fence
        elif fence[0] == opened[0] and len(fence) >= len(opened) and not tail.strip():
            opened = None
    if opened:
        raise ValueError("원고의 코드 블록이 끝나지 않았습니다. 응답을 검토하고 출력 한도를 늘려 재개하세요.")
    return text + "\n"


def write_artifact(run: Path, state: dict, relative: str, text: str):
    path = inside(run, relative)
    previous = state["files"].get(relative)
    if path.exists() and (previous is None or digest(path) != previous):
        raise ValueError("사용자가 변경했거나 기록되지 않은 파일이 있습니다. 기존 파일을 덮어쓰지 않습니다.")
    atomic_text(path, text)
    state["files"][relative] = digest(path)


def finalize(run: Path, state: dict, config: BookConfig, plan: BookPlan, *, authorship: dict | None = None):
    book_rel = f"book/{config.id}"
    book = inside(run, book_rel)
    today = date.today().isoformat()
    chapters = [
        {"number": number, "title": chapter.title, "href": chapter_href(number), "part": part}
        for number, (part, chapter) in enumerate(plan.chapters(), 1)
    ]
    parts = []
    first = 1
    for number, part in enumerate(plan.parts, 1):
        last = first + len(part.chapters) - 1
        parts.append({"number": number, "title": part.title, "first": first, "last": last})
        first = last + 1
    meta = {
        "id": config.id,
        "title": config.title,
        "description": plan.description,
        "status": "draft",
        "tags": config.tags,
        "provenance": {
            "generator": "AI Generation Library book-generator 0.1.0"
            + (" (offline demo)" if config.demo else ""),
            "provider": "offline-demo" if config.demo else config.provider,
            "model": None if config.demo else config.model,
            "created": state["created"][:10],
            "updated": today,
            "source": "저자가 입력한 주제·목차·참고 자료. 원문은 generation-input.json에 기록.",
            "review": {
                "status": "unreviewed",
                "scope": [],
                "notVerified": ["사실·출처 확인", "생성 코드의 실행", "전체 사람 검수"],
                "verification": "appendices/verification",
            },
        },
        "chapters": chapters,
        "parts": parts,
        "downloads": [],
    }
    if authorship is not None:
        meta["provenance"].update(authorship)
    toc = "\n\n".join(
        f"### {part['number']}부. {part['title']}\n\n"
        + "\n".join(
            f"- [{item['number']:02d}장. {item['title']}]({item['href']})"
            for item in chapters[part["first"] - 1 : part["last"]]
        )
        for part in parts
    )
    intro = frontmatter(config.title, plan.description, config, bookHome=True)
    intro += f"# {config.title}\n\n{plan.description}\n\n> AI로 작성한 미검수 초안입니다."
    if config.demo:
        intro += " **실제 AI 호출 없이 만든 데모 원고입니다.**"
    intro += f"\n\n## 목차\n\n{toc}\n\n[검증 상태](appendices/verification)\n"
    verification = frontmatter("생성 기록과 검증 범위", "AI 초안의 검증 상태", config)
    verification += "# 생성 기록과 검증 범위\n\n이 원고는 **미검수 초안**입니다. 파일 형식 검사는 내용의 정확도를 보증하지 않습니다.\n\n"
    verification += f"- 생성 도구: {meta['provenance']['generator']}\n"
    verification += f"- 제공자/작성 경로: {meta['provenance']['provider']}\n"
    verification += f"- 확인된 모델: {meta['provenance']['model'] or '확인되지 않음'}\n"
    if authorship is not None:
        verification += "- 이 도구의 외부 AI API 호출: 없음. 저자가 제공한 원고를 정리했습니다.\n"
    verification += "- 사실 확인·출처 검토·코드 실행·사람 검수: 미수행\n- 참고 URL 자동 조회: 미수행\n\n"
    verification += "원고를 공개하기 전에 설명과 예제, 참고 자료, 라이선스를 검토하고 확인한 범위를 book.json에 기록하세요.\n"
    for relative, text in {
        "index.md": intro,
        "appendices/verification.md": verification,
        "book.json": json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        "generation-input.json": json.dumps(
            {"config": config.model_dump(), "authorship": authorship}, ensure_ascii=False, indent=2
        )
        + "\n"
        if authorship is not None
        else config.model_dump_json(indent=2) + "\n",
    }.items():
        write_artifact(run, state, f"{book_rel}/{relative}", text)
    validate_book(book)
    archive = inside(run, f"{config.id}.zip")
    temporary = inside(run, f"{config.id}.zip.tmp")
    with ZipFile(temporary, "w", ZIP_DEFLATED) as zip_file:
        for relative in sorted(state["files"]):
            if relative.startswith(book_rel + "/"):
                path = inside(run, relative)
                zip_file.write(path, f"{config.id}/{path.relative_to(book).as_posix()}")
    temporary.replace(archive)
    state["archive"] = archive.name


def export_book(run: Path, books: Path) -> Path:
    state = json.loads(inside(run, "checkpoint.json").read_text(encoding="utf-8"))
    if state["status"] != "completed":
        raise ValueError("완성된 작업만 내보낼 수 있습니다.")
    config = BookConfig.model_validate(state["config"])
    source = inside(run, f"book/{config.id}")
    validate_book(source)
    root = canonical(books)
    if not (root / "scripts" / "validate-books.py").is_file():
        raise ValueError("books 저장소의 로컬 경로를 지정하세요.")
    content = inside(root, "content")
    content.mkdir(exist_ok=True)
    target = inside(root, f"content/{config.id}")
    if target.exists():
        raise ValueError("같은 id의 책이 이미 있습니다. 기존 책은 덮어쓰지 않습니다.")
    # Stage inside the validated destination before atomic publication of the folder.
    with tempfile.TemporaryDirectory(prefix=".generator-", dir=content) as temporary:
        staged = Path(temporary) / config.id
        shutil.copytree(source, staged, symlinks=False)
        validate_book(staged)
        # os.rename on Windows refuses existing targets; directory targets elsewhere must also be absent.
        if target.exists():
            raise ValueError("내보내기 중 같은 id의 책이 추가되었습니다.")
        staged.rename(target)
    return target

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path


def canonical(path: Path) -> Path:
    return Path(os.path.abspath(path)).resolve()


def inside(root: Path, relative: str) -> Path:
    if not relative or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise ValueError("안전한 상대 경로가 필요합니다.")
    if any(character in relative for character in "\\:?#%"):
        raise ValueError("허용되지 않는 경로입니다.")
    base = canonical(root)
    path = canonical(base / relative)
    if not path.is_relative_to(base):
        raise ValueError("파일 경로가 작업 폴더 밖을 가리킵니다.")
    return path


def run_path(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("유효하지 않은 작업 ID입니다.")
    return inside(root, run_id)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    # Check the temporary sibling too; an existing symlink must never be followed.
    if temporary.is_symlink() or canonical(temporary).parent != canonical(path.parent):
        raise ValueError("안전하지 않은 임시 파일 경로입니다.")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def save_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def run_lock(run: Path):
    """An OS lock works across the CLI and web process, and is released after a crash."""
    path = inside(run, ".lock")
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("이 작업이 다른 프로세스에서 실행 중입니다.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

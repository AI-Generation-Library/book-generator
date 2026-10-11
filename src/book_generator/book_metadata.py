"""Vendored CC0 content validator from AI-Generation-Library/books (7359063).

Source: https://github.com/AI-Generation-Library/books/blob/73590634887671cc8d70ff94d850646953836a37/scripts/book_metadata.py
Reading a book never changes its files. Keep contract changes aligned with books.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path, PurePosixPath


def check_slug(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError("Book id must use lowercase ASCII letters, numbers and hyphens")
    return value


def local_href(value: str) -> str:
    if not isinstance(value, str) or not value or any(character in value for character in "\\:?#%"):
        raise ValueError(f"Invalid book-relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"Path must stay inside its book: {value!r}")
    return value


def write_json(path: Path, value: dict) -> None:
    """Write metadata only when explicitly called by an authoring command."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != encoded:
        path.write_text(encoded, encoding="utf-8")


def _text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _file(book: Path, value: str, label: str, markdown: bool = False) -> None:
    href = local_href(value)
    if markdown and href.endswith(".md"):
        raise ValueError(f"{label} must omit the .md extension")
    target = (book / (href + ".md" if markdown else href)).resolve()
    if not target.is_relative_to(book.resolve()) or not target.is_file():
        raise ValueError(f"{label} needs an existing file inside its book: {href}")


def validate_metadata(book: Path, meta: dict) -> dict:
    """Validate a supplied document and its files without writing source data."""
    if not isinstance(meta, dict):
        raise ValueError(f"{book}: book.json must be an object")
    if check_slug(meta.get("id", "")) != book.name:
        raise ValueError(f"{book}: book.json id must equal the directory name")
    for field in ("title", "description", "status"):
        _text(meta.get(field), f"{book}: {field}")
    tags = meta.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        raise ValueError(f"{book}: tags must be an array of nonempty strings")
    provenance = meta.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError(f"{book}: provenance must record generation and review information")
    for field in ("generator", "source"):
        _text(provenance.get(field), f"{book}: provenance.{field}")
    if "model" not in provenance or (provenance["model"] is not None and
            (not isinstance(provenance["model"], str) or not provenance["model"].strip())):
        raise ValueError(f"{book}: provenance.model must be a recorded model name or null")
    for field in ("created", "updated"):
        value = provenance.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{book}: provenance.{field} must use YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{book}: provenance.{field} is not a real calendar date") from error
    if provenance["updated"] < provenance["created"]:
        raise ValueError(f"{book}: provenance.updated cannot precede created")
    review = provenance.get("review")
    if not isinstance(review, dict):
        raise ValueError(f"{book}: provenance.review must be an object")
    _text(review.get("status"), f"{book}: provenance.review.status")
    for field in ("scope", "notVerified"):
        values = review.get(field, [] if field == "notVerified" else None)
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError(f"{book}: provenance.review.{field} must be an array of nonempty strings")
    verification = review.get("verification")
    if verification is not None:
        _file(book, verification, f"{book}: review verification", markdown=True)
    _file(book, "index.md", f"{book}: book index")
    chapters = meta.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError(f"{book}: chapters must contain at least one chapter")
    hrefs = set()
    for expected, chapter in enumerate(chapters, 1):
        if not isinstance(chapter, dict):
            raise ValueError(f"{book}: chapter {expected} must be an object")
        if not _positive(chapter.get("number")) or chapter["number"] != expected:
            raise ValueError(f"{book}: chapters must be ordered consecutively from 1 to their total count")
        _text(chapter.get("title"), f"{book}: chapter {expected} title")
        href = local_href(chapter.get("href"))
        if href in hrefs:
            raise ValueError(f"{book}: chapter hrefs must be unique")
        _file(book, href, f"{book}: chapter {expected}", markdown=True)
        if not _positive(chapter.get("part")):
            raise ValueError(f"{book}: chapter {expected} needs a positive part number")
        hrefs.add(href)
    parts = meta.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError(f"{book}: parts must contain at least one part")
    next_chapter = 1
    for expected, part in enumerate(parts, 1):
        if not isinstance(part, dict) or not _positive(part.get("number")) or part["number"] != expected:
            raise ValueError(f"{book}: parts must be ordered consecutively from 1")
        _text(part.get("title"), f"{book}: part {expected} title")
        first, last = part.get("first"), part.get("last")
        if not _positive(first) or not _positive(last) or first != next_chapter or last < first or last > len(chapters):
            raise ValueError(f"{book}: part {expected} must cover the next continuous chapter range")
        if any(chapter["part"] != expected for chapter in chapters[first - 1:last]):
            raise ValueError(f"{book}: part {expected} does not match its chapters")
        next_chapter = last + 1
    if next_chapter != len(chapters) + 1:
        raise ValueError(f"{book}: parts must cover every chapter exactly once")
    downloads = meta.get("downloads", [])
    if not isinstance(downloads, list):
        raise ValueError(f"{book}: downloads must be an array")
    download_hrefs = set()
    for download in downloads:
        if not isinstance(download, dict):
            raise ValueError(f"{book}: every download must be an object")
        for field in ("title", "type"):
            _text(download.get(field), f"{book}: download {field}")
        href = local_href(download.get("href"))
        if href in download_hrefs:
            raise ValueError(f"{book}: download hrefs must be unique")
        _file(book, href, f"{book}: download")
        download_hrefs.add(href)
    return meta


def validate_book(book: Path) -> dict:
    meta = json.loads((book / "book.json").read_text(encoding="utf-8-sig"))
    return validate_metadata(book, meta)


def load_books(root: Path) -> list[tuple[Path, dict]]:
    """Return every registered book only after the entire collection validates."""
    content = (root / "content").resolve()
    paths = sorted(content.glob("*/book.json"))
    if not paths:
        raise ValueError("No books registered: add content/<id>/book.json")
    books = []
    for path in paths:
        if not path.resolve().is_relative_to(content) or not path.parent.resolve().is_relative_to(content):
            raise ValueError(f"Book metadata must stay inside content: {path}")
        books.append((path.parent, validate_book(path.parent)))
    return books

import json
from zipfile import ZipFile

import pytest

from book_generator.book_metadata import validate_book
from book_generator.models import BookConfig
from book_generator.packaging import package_manuscript
from book_generator.prompts import demo_chapter, demo_plan


def source_manuscript(tmp_path, config):
    plan = demo_plan(config)
    source = tmp_path / "manuscript"
    for number, (_, chapter) in enumerate(plan.chapters(), 1):
        path = source / f"{number:02d}-chapter/chapter.md"
        path.parent.mkdir(parents=True)
        path.write_text(demo_chapter(config, number, chapter), encoding="utf-8")
    (source / "templates").mkdir()
    (source / "templates/checklist.md").write_text(
        "# Checklist\n\nAuthor supplied template.", encoding="utf-8"
    )
    return source, plan


def test_authored_book_does_not_claim_api_generation_or_known_model(config, tmp_path):
    config = BookConfig.model_validate({**config.model_dump(), "model": ""})
    source, plan = source_manuscript(tmp_path, config)
    run = package_manuscript(tmp_path / "output", config, plan, source, "Codex")
    state = json.loads((run / "checkpoint.json").read_text(encoding="utf-8"))
    assert state["calls"] == [] and state["origin"] == "external-manuscript"
    book = run / "book/test-book"
    meta = validate_book(book)
    assert meta["provenance"]["model"] is None
    assert meta["provenance"]["provider"] == "external-manuscript"
    assert "Codex" in meta["provenance"]["generator"]
    assert meta["provenance"]["review"]["status"] == "unreviewed"
    with ZipFile(run / state["archive"]) as archive:
        assert "test-book/templates/checklist.md" in archive.namelist()


def test_missing_chapter_leaves_no_output(config, tmp_path):
    source, plan = source_manuscript(tmp_path, config)
    (source / "02-chapter/chapter.md").unlink()
    with pytest.raises(ValueError, match="원고가 없습니다"):
        package_manuscript(tmp_path / "output", config, plan, source, "Codex")
    assert not (tmp_path / "output").exists()


def test_private_env_is_not_packaged(config, tmp_path):
    source, plan = source_manuscript(tmp_path, config)
    (source / "templates/.env").write_text("PRIVATE=do-not-export", encoding="utf-8")
    with pytest.raises(ValueError, match="공개할 텍스트"):
        package_manuscript(tmp_path / "output", config, plan, source, "Codex")
    assert not (tmp_path / "output").exists()

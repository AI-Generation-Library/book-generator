import asyncio
import importlib.util
import os
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
from conftest import MockAuthor, response_for

from book_generator.book_metadata import validate_book
from book_generator.engine import create_run, execute, load_state
from book_generator.manuscript import clean_markdown, export_book
from book_generator.models import BookConfig
from book_generator.providers import Provider
from book_generator.storage import inside, run_lock


@pytest.mark.parametrize("name", ["openai", "claude", "gemini"])
def test_full_book_is_portable_and_secret_free(config, tmp_path, name):
    config = BookConfig.model_validate({**config.model_dump(), "provider": name})
    author = MockAuthor(config)
    run = create_run(tmp_path, config, author.key)
    provider = author.provider()
    state = asyncio.run(execute(run, provider))
    assert state["status"] == "completed", state["message"]
    assert state["completed_chapters"] == [1, 2, 3]
    assert len(author.requests) == 4
    assert state["output_tokens"] == 440
    assert state["reserved_tokens"] == 0
    assert provider._key == ""
    meta = validate_book(run / "book" / config.id)
    assert meta["provenance"]["review"]["status"] == "unreviewed"
    assert meta["provenance"]["model"] == "test-model"
    with ZipFile(run / state["archive"]) as archive:
        assert f"{config.id}/book.json" in archive.namelist()
        assert all(path.startswith(config.id + "/") for path in archive.namelist())
        assert all(author.key not in archive.read(path).decode() for path in archive.namelist())
    for path in run.rglob("*"):
        if path.is_file() and path.suffix != ".zip":
            assert author.key not in path.read_text(encoding="utf-8")


def test_budget_pause_then_resume_skips_completed_chapters(config, tmp_path):
    config = BookConfig.model_validate({**config.model_dump(), "output_budget": 800})
    author = MockAuthor(config)
    run = create_run(tmp_path, config)
    state = asyncio.run(execute(run, author.provider()))
    assert state["status"] == "paused"
    assert state["completed_chapters"] == [1, 2]
    original = (run / "book/test-book/01-chapter/chapter.md").read_bytes()
    state = asyncio.run(execute(run, author.provider(), output_budget=2000))
    assert state["status"] == "completed"
    assert len(author.requests) == 4
    assert (run / "book/test-book/01-chapter/chapter.md").read_bytes() == original


def test_user_changes_are_preserved(config, tmp_path):
    config = BookConfig.model_validate({**config.model_dump(), "output_budget": 512})
    run = create_run(tmp_path, config)
    state = asyncio.run(execute(run, MockAuthor(config).provider()))
    assert state["status"] == "paused"
    path = run / "plan.json"
    path.write_text("user-edited-content", encoding="utf-8")
    with pytest.raises(ValueError, match="수정"):
        asyncio.run(execute(run, MockAuthor(config).provider(), output_budget=2000))
    assert path.read_text(encoding="utf-8") == "user-edited-content"


def test_cancel_keeps_reservation_and_forgets_key(config, tmp_path):
    async def scenario():
        started = asyncio.Event()

        async def handle(request):
            started.set()
            await asyncio.Event().wait()

        provider = Provider(config, "sensitive", httpx.MockTransport(handle))
        run = create_run(tmp_path, config)
        task = asyncio.create_task(execute(run, provider))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert load_state(run)["status"] == "paused"
        assert load_state(run)["reserved_tokens"] == 512
        assert provider._key == ""

    asyncio.run(scenario())


def test_invalid_response_does_not_drop_usage(config, tmp_path):
    run = create_run(tmp_path, config)
    provider = Provider(
        config,
        "private-key",
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_for("openai", "not valid JSON"))
        ),
    )
    state = asyncio.run(execute(run, provider))
    assert state["status"] == "failed"
    assert state["output_tokens"] == 110 and state["reserved_tokens"] == 0
    assert (run / "responses/001.txt").read_text(encoding="utf-8") == "not valid JSON"


def test_demo_and_actual_books_contract(tmp_path, config):
    config = BookConfig.model_validate({**config.model_dump(), "demo": True})
    run = create_run(tmp_path, config)
    state = asyncio.run(execute(run, None))
    assert state["status"] == "completed"
    assert not state["calls"] and state["output_tokens"] == 0
    assert "데모" in (run / "book/test-book/index.md").read_text(encoding="utf-8")
    source = Path(
        os.getenv("BOOKS_VALIDATOR", Path(__file__).resolve().parents[2] / "books/scripts/book_metadata.py")
    )
    if not source.is_file():
        pytest.skip("books checkout not present (CI supplies BOOKS_VALIDATOR)")
    spec = importlib.util.spec_from_file_location("source_books_validator", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    meta = module.validate_book(run / "book/test-book")
    assert len(meta["chapters"]) == 3


def test_export_refuses_existing_book(tmp_path, config):
    config = BookConfig.model_validate({**config.model_dump(), "demo": True})
    run = create_run(tmp_path / "runs", config)
    asyncio.run(execute(run, None))
    checkout = tmp_path / "books"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "scripts/validate-books.py").write_text("# fixture")
    target = export_book(run, checkout)
    assert validate_book(target)["id"] == config.id
    with pytest.raises(ValueError, match="既存|이미"):
        export_book(run, checkout)


@pytest.mark.parametrize("relative", ["../outside", "C:/outside", "a/../../b", "/absolute", "a\\b"])
def test_paths_stay_inside(tmp_path, relative):
    with pytest.raises(ValueError):
        inside(tmp_path, relative)


def test_process_lock(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(ValueError, match="실행 중"):
            with run_lock(tmp_path):
                pass


def test_secrets_cannot_enter_config(config, tmp_path):
    config = BookConfig.model_validate({**config.model_dump(), "subject": "my-key-in-input"})
    with pytest.raises(ValueError, match="API 키"):
        create_run(tmp_path, config, "my-key-in-input")
    assert not list(tmp_path.iterdir())


def test_unfinished_fence_rejected():
    with pytest.raises(ValueError, match="코드 블록"):
        clean_markdown("# Title\n" + "Enough content. " * 30 + "\n```python\nprint('hello')\n")

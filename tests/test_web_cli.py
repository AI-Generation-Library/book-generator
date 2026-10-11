import asyncio
import io
import json
import time
from pathlib import Path
from zipfile import ZipFile

import pytest
from conftest import MockAuthor
from fastapi.testclient import TestClient

from book_generator.cli import main
from book_generator.models import BookConfig
from book_generator.web import create_app


def wait_for_job(client, run_id):
    for _ in range(100):
        result = client.get(f"/api/runs/{run_id}").json()
        if not result["active"]:
            return result
        time.sleep(0.02)
    raise AssertionError("Background generation did not settle")


def test_web_demo_preview_archive_and_redacted_validation(tmp_path, config):
    app = create_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        session = client.get("/api/session").json()
        headers = {"x-generator-token": session["token"], "origin": "http://127.0.0.1"}
        body = {"config": {**config.model_dump(), "demo": True}, "api_key": "unused-secret"}
        response = client.post("/api/runs", json=body, headers=headers)
        assert response.status_code == 202 and "unused-secret" not in response.text
        run_id = response.json()["run_id"]
        job = wait_for_job(client, run_id)
        assert job["status"] == "completed"
        assert job["completed_chapters"] == [1, 2, 3]
        preview = client.get(f"/api/runs/{run_id}/preview?chapter=2")
        assert "데모 원고" in preview.json()["markdown"]
        assert client.get(f"/api/runs/{run_id}/preview?chapter=99").status_code == 404
        archive = client.get(f"/api/runs/{run_id}/download")
        assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
        with ZipFile(io.BytesIO(archive.content)) as zipped:
            assert "test-book/book.json" in zipped.namelist()
        invalid = client.post(
            "/api/runs", json={"config": {"id": "../bad"}, "api_key": "never-echo-this"}, headers=headers
        )
        assert invalid.status_code == 422 and "never-echo-this" not in invalid.text
        assert "no-store" in client.get("/").headers["cache-control"]
        assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]


def test_web_csrf_host_and_path_guards(tmp_path, config):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        token = client.get("/api/session").json()["token"]
        body = {"config": {**config.model_dump(), "demo": True}}
        assert client.post("/api/runs", json=body).status_code == 403
        assert (
            client.post(
                "/api/runs", json=body, headers={"x-generator-token": token, "origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.get("/api/session", headers={"host": "evil.example"}).status_code == 400
        assert client.get("/api/runs/not-a-valid-run-id").status_code == 404
        assert not list(tmp_path.iterdir())


def test_web_real_provider_mock_pause_resume(tmp_path, config):
    config = BookConfig.model_validate({**config.model_dump(), "output_budget": 800})
    author = MockAuthor(config, "my-web-key")
    with TestClient(
        create_app(tmp_path, lambda config, key: author.provider()), base_url="http://127.0.0.1"
    ) as client:
        headers = {"x-generator-token": client.get("/api/session").json()["token"]}
        missing = client.post("/api/runs", json={"config": config.model_dump()}, headers=headers)
        assert missing.status_code == 400
        start = client.post(
            "/api/runs", json={"config": config.model_dump(), "api_key": author.key}, headers=headers
        )
        run_id = start.json()["run_id"]
        assert wait_for_job(client, run_id)["status"] == "paused"
        assert client.get(f"/api/runs/{run_id}/download").status_code == 409
        resume = client.post(
            f"/api/runs/{run_id}/resume", json={"api_key": author.key, "output_budget": 2000}, headers=headers
        )
        assert resume.status_code == 202
        assert wait_for_job(client, run_id)["status"] == "completed"
        assert author.key not in client.get("/api/runs").text
        assert author.key not in (tmp_path / run_id / "checkpoint.json").read_text(encoding="utf-8")


def test_web_cancel_releases_key(tmp_path, config):
    providers = []

    class WaitingAuthor:
        def __init__(self, config, key):
            self._key = key
            providers.append(self)

        async def complete(self, *args, **kwargs):
            await asyncio.Event().wait()

        def forget_key(self):
            self._key = ""

    with TestClient(create_app(tmp_path, WaitingAuthor), base_url="http://127.0.0.1") as client:
        headers = {"x-generator-token": client.get("/api/session").json()["token"]}
        run_id = client.post(
            "/api/runs", json={"config": config.model_dump(), "api_key": "temporary-key"}, headers=headers
        ).json()["run_id"]
        for _ in range(100):
            if client.get(f"/api/runs/{run_id}").json()["reserved_tokens"]:
                break
            time.sleep(0.01)
        assert client.post(f"/api/runs/{run_id}/cancel", headers=headers).status_code == 202
        assert wait_for_job(client, run_id)["status"] == "paused"
        assert providers[0]._key == ""


def test_cli_demo_validate_export(tmp_path, capsys):
    config = Path(__file__).resolve().parents[1] / "examples/book.json"
    output = tmp_path / "output"
    assert main(["generate", "--config", str(config), "--output", str(output), "--demo"]) == 0
    run = next(output.iterdir())
    assert main(["validate", str(run / "book/my-learning-guide")]) == 0
    assert main(["resume", str(run)]) == 0
    assert "콘텐츠 형식 검사 통과" in capsys.readouterr().out


def test_cli_rejects_key_in_config_without_echo(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {"id": "test", "title": "book", "subject": "test", "demo": True, "api_key": "do-not-echo-me"}
        ),
        encoding="utf-8",
    )
    assert main(["generate", "--config", str(path), "--output", str(tmp_path / "out")]) == 1
    output = capsys.readouterr()
    assert "do-not-echo-me" not in output.err + output.out
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("name", ["../book", "con", "a%2Fb", "UPPER", "a.b"])
def test_rejects_unsafe_ids(name, config):
    with pytest.raises(ValueError):
        BookConfig.model_validate({**config.model_dump(), "id": name})

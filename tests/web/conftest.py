"""Fixtures for the web API tests: an isolated runtime folder, a scripted
stand-in for the local model, and helpers that upload the example bundles
through the API exactly as the browser does."""

from __future__ import annotations

import threading
from collections import deque

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from molarmetrics.api.app import create_app
from molarmetrics.api.ask_service import AskService
from molarmetrics.api.settings import WebSettings
from tests.web.helpers import DATE_FIELD, bundle_files

HEADERS = {"X-MolarMetrics": "1"}


class ScriptedModel(GenericFakeChatModel):
    """Replays scripted replies (offline tests only; not evidence the real model works)."""

    def bind_tools(self, tools, **kwargs):
        return self


class _Replies:
    """An iterator that survives an empty queue (raising IndexError, like a
    failed model call) and keeps working afterwards, as a real client does."""

    def __init__(self, script: "Script"):
        self.script = script

    def __iter__(self):
        return self

    def __next__(self):
        if self.script.gate is not None:
            self.script.gate.wait(10)
        return self.script.queue.popleft()


class Script:
    """Queue replies for the next question(s). Each queued item is one model reply."""

    def __init__(self):
        self.queue: deque = deque()
        self.gate: threading.Event | None = None

    def model(self):
        return ScriptedModel(messages=_Replies(self))

    def tool_call(self, name: str, args: dict, call_id: str = "c1") -> AIMessage:
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])

    def then(self, *replies):
        self.queue.extend(AIMessage(content=r) if isinstance(r, str) else r for r in replies)
        return self


@pytest.fixture()
def web_settings(tmp_path):
    return WebSettings(runtime_dir=tmp_path / "runtime", retention_hours=24, max_file_mb=2, max_files=10,
                       sweep_minutes=10, allowed_hosts=("testserver", "localhost", "127.0.0.1"))


@pytest.fixture()
def script():
    return Script()


@pytest.fixture()
def app(web_settings, script):
    return create_app(web_settings, AskService(model_factory=script.model))


@pytest.fixture()
def client(app):
    with TestClient(app, headers=HEADERS) as c:
        yield c


@pytest.fixture()
def other_client(app):
    """A second browser: its own cookie jar, so its own session."""
    with TestClient(app, headers=HEADERS) as c:
        yield c


def upload(client, bundle: str, only: tuple[str, ...] | None = None):
    files = [("files", (p.name, p.read_bytes(), "text/csv")) for p in bundle_files(bundle, only)]
    response = client.post("/api/uploads", files=files)
    assert response.status_code == 200, response.text
    return response.json()


def confirm(batch: dict, name: str, unit: str | None = None, date_format: str | None = None,
            decisions: dict | None = None) -> dict:
    """The choices a user makes on the review screen."""
    config = batch["config"]
    config["name"] = name
    for f in config["files"]:
        if unit and f["record_type"] in ("treatments", "payments"):
            f["money_unit"] = unit
        if date_format and f["record_type"] in DATE_FIELD:
            f["date_formats"][DATE_FIELD[f["record_type"]]] = date_format
    config["review_decisions"] = decisions or {}
    return config


def import_bundle(client, bundle: str, name: str, only=None, **choices) -> dict:
    batch = upload(client, bundle, only)
    config = confirm(batch, name, **choices)
    report = client.post(f"/api/uploads/{batch['batch_id']}/validate", json=config).json()
    assert report["ready"], report["summary"]
    response = client.post(f"/api/uploads/{batch['batch_id']}/import", json=config)
    assert response.status_code == 200, response.text
    return response.json()


def import_sunrise(client) -> dict:
    return import_bundle(client, "sunrise-dental", "Sunrise Dental", unit="rupees", date_format="DD/MM/YYYY")


def import_lakeview(client, only=None) -> dict:
    return import_bundle(client, "lakeview-dental", "Lakeview Dental", only=only, unit="paise", decisions={
        "payments_before_treatment": "include", "treatments_on_unattended_appointments": "exclude"})

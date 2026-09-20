import os

os.environ.setdefault("PTOUCH_BACKEND", "dry")

import pytest
from fastapi.testclient import TestClient

from ptouch_mcp import service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service.backend, "out_dir", tmp_path)
    return TestClient(service.app)


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_status_reports_the_model_and_its_tapes(client):
    body = client.get("/status").json()
    assert body["connected"] is True
    assert body["transport"] == "dry"
    assert body["model"] == "PT-P710BT"
    assert 24 in body["supported_tape_mm"]


def test_print_writes_one_file_per_copy(client, tmp_path):
    body = client.post("/print", json={"text": "Garage", "copies": 3}).json()
    assert body["copies"] == 3
    assert len(list(tmp_path.glob("*.png"))) == 3


def test_print_rejects_too_many_copies(client):
    resp = client.post("/print", json={"text": "x", "copies": 999})
    assert resp.status_code == 400
    assert "or fewer" in resp.json()["detail"]


def test_print_rejects_overlong_text(client):
    resp = client.post("/print", json={"text": "x" * 500})
    assert resp.status_code == 400


def test_print_rejects_empty_text(client):
    assert client.post("/print", json={"text": ""}).status_code == 422


def test_print_rejects_tape_the_printer_cannot_take(client):
    assert client.post("/print", json={"text": "x", "tape_mm": 36}).status_code == 400


def test_preview_returns_png_and_prints_nothing(client, tmp_path):
    resp = client.post("/preview", json={"text": "Christmas Decor", "tape_mm": 12})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert resp.headers["X-Label-Size-Px"].endswith("x70")
    assert list(tmp_path.glob("*.png")) == []

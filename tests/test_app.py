import pytest
from fastapi.testclient import TestClient

from take_two import config
from take_two.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_bad_take_id_is_400(client):
    assert client.get("/api/takes/C:").status_code == 400
    assert client.get("/takes/D:foo/audio.wav").status_code == 400


def test_missing_take_is_404(client):
    assert client.get("/api/takes/20990101-000000-abcd").status_code == 404


def test_cross_origin_write_is_refused(client):
    r = client.post("/api/suggest/apply", json={"script": "x", "accepted": []}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/suggest/apply", json={"script": "x", "accepted": []}, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200


def test_foreign_host_header_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    r = TestClient(app, base_url="http://attacker.example").get("/api/takes")
    assert r.status_code == 400

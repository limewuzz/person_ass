"""健康端点契约测试（对应 backlog P1-02 的最小子集）。"""
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health_live_matches_contract_shape():
    r = client.get("/api/v1/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["component"] == "control-plane"
    assert "version" in body and "uptime_seconds" in body


def test_health_ready_marks_unknown_deps():
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    body = r.json()
    # 未接入的依赖必须显式 UNKNOWN，不得伪造 ready
    assert body["deps"] == {"database": "UNKNOWN", "probes": "UNKNOWN"}


def test_unknown_route_404():
    assert client.get("/api/v1/nodes").status_code == 404  # P1-05 才实现

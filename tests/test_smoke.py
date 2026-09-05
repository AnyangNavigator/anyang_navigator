"""핵심 페이지/API가 최소한 죽지 않고 응답하는지 확인하는 스모크 테스트.

새 기능이 기존 라우트를 완전히 깨뜨리는 것만 잡는 게 목적이라 값 검증은
최소화했다. 세부 로직 테스트는 app/simulator.py, app/data.py에 필요시 추가.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dashboard_default():
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "안양1동" in res.text


def test_dashboard_with_dong_query():
    res = client.get("/dashboard", params={"dong": "평촌동"})
    assert res.status_code == 200
    assert "평촌동" in res.text


def test_dashboard_unknown_dong_falls_back():
    res = client.get("/dashboard", params={"dong": "존재하지않는동"})
    assert res.status_code == 200


def test_simulator_page():
    res = client.get("/simulator")
    assert res.status_code == 200


def test_simulator_default_scenario():
    res = client.post("/simulator", data={"scenario_id": "yangji"})
    assert res.status_code == 200
    assert "양지마을" in res.text


def test_simulator_custom_scenario():
    res = client.post(
        "/simulator",
        data={"region": "동안구", "facility": "도서관", "num_facilities": "2"},
    )
    assert res.status_code == 200


def test_api_dong():
    res = client.get("/api/dong/안양1동")
    assert res.status_code == 200
    body = res.json()
    assert body["dong_stats"]["gu"] == "만안구"


def test_api_report():
    res = client.get("/api/report/안양1동")
    assert res.status_code == 200
    assert "report" in res.json()


def test_api_chat():
    res = client.post("/api/chat", json={"question": "주차시설은 어때?", "dong": "안양1동"})
    assert res.status_code == 200
    assert "answer" in res.json()


def test_api_dong_boundaries():
    res = client.get("/api/dong-boundaries")
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 31
    dongs = {f["properties"]["dong"] for f in body["features"]}
    assert "안양1동" in dongs
    # 인구 데이터와 조인이 잘 됐는지 확인 (population_by_dong.csv와 행정동명이 어긋나면 None이 나옴)
    assert all(f["properties"]["total_population"] is not None for f in body["features"])


def test_api_simulate():
    res = client.post(
        "/api/simulate",
        json={"region": "만안구", "facility": "공영주차시설", "num_facilities": 3},
    )
    assert res.status_code == 200
    assert "result" in res.json()

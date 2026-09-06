"""핵심 페이지/API가 최소한 죽지 않고 응답하는지 확인하는 스모크 테스트.

새 기능이 기존 라우트를 완전히 깨뜨리는 것만 잡는 게 목적이라 값 검증은
최소화했다. 세부 로직 테스트는 app/simulator.py, app/data.py에 필요시 추가.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app import report, simulator

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


def test_simulator_invalid_facility_shows_error_not_crash():
    # 폼을 우회해 잘못된 facility를 보내도 500이 아니라 에러 메시지가 담긴
    # 200 페이지여야 한다 (#15).
    res = client.post(
        "/simulator",
        data={"region": "만안구", "facility": "존재하지않는시설", "num_facilities": "1"},
    )
    assert res.status_code == 200
    assert "시뮬레이션을 실행할 수 없습니다" in res.text


def test_simulator_missing_num_facilities_and_budget_shows_error():
    res = client.post("/simulator", data={"region": "만안구", "facility": "도서관"})
    assert res.status_code == 200
    assert "시뮬레이션을 실행할 수 없습니다" in res.text


def test_healthz():
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["dong_count"] == 31


def test_about_page_lists_assumption_coefficients():
    res = client.get("/about")
    assert res.status_code == 200
    # 시뮬레이터 가정 계수가 실제로 렌더돼야 한다 (코드 상수와 동기화).
    assert "데이터 출처와 방법론" in res.text
    assert "공영주차시설" in res.text
    assert "1,500,000,000원" in res.text


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


def test_api_simulate_rank():
    res = client.post(
        "/api/simulate/rank",
        json={
            "scenarios": [
                {"region": "만안구", "facility": "공영주차시설", "budget": 3_000_000_000},
                {"region": "만안구", "facility": "보건의료시설", "budget": 6_000_000_000},
            ]
        },
    )
    assert res.status_code == 200
    ranked = res.json()["ranked"]
    assert len(ranked) == 2
    assert ranked[0]["rank"] == 1 and ranked[1]["rank"] == 2
    # 효율(1억원당 감소폭) 내림차순으로 정렬돼 있어야 한다.
    effs = [r["efficiency"] for r in ranked]
    assert effs == sorted(effs, reverse=True)


def test_rank_scenarios_reuses_budget_conversion():
    ranked = simulator.rank_scenarios(
        [
            {"region": "만안구", "facility": "공영주차시설", "budget": 3_000_000_000},
            {"region": "동안구", "facility": "도서관", "num_facilities": 1},
        ]
    )
    assert [r.rank for r in ranked] == [1, 2]
    # budget 시나리오는 estimate_facility_count로 개소가 환산돼야 한다.
    parking = next(r for r in ranked if r.result.facility == "공영주차시설")
    assert parking.result.num_facilities == simulator.estimate_facility_count(
        "공영주차시설", 3_000_000_000
    )
    # num_facilities만 준 시나리오는 예산이 없으므로 효율 0.
    library = next(r for r in ranked if r.result.facility == "도서관")
    assert library.efficiency == 0.0


def test_api_simulate_rank_missing_budget_and_count():
    res = client.post(
        "/api/simulate/rank",
        json={"scenarios": [{"region": "만안구", "facility": "도서관"}]},
    )
    assert res.status_code == 200
    assert "error" in res.json()


def test_call_openai_falls_back_on_malformed_json_response(monkeypatch):
    # OpenAI가 파싱 불가능한 바디를 돌려줘도 예외가 새어나가지 않고
    # None(규칙 기반 폴백 신호)을 반환해야 한다 (#15).
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class FakeResponse:
        def read(self):
            return b"not valid json"

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    with patch("app.report.urllib.request.urlopen", return_value=FakeResponse()):
        result = report._call_openai("아무 프롬프트")

    assert result is None


def test_call_openai_falls_back_when_content_is_null(monkeypatch):
    # 콘텐츠 필터·tool_calls 등으로 OpenAI가 정상 200 + 정상 JSON이지만
    # content: null을 돌려주는 경우도 폴백돼야 한다 (PR #18 리뷰에서 발견).
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class FakeResponse:
        def read(self):
            return b'{"choices":[{"message":{"content":null}}]}'

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    with patch("app.report.urllib.request.urlopen", return_value=FakeResponse()):
        result = report._call_openai("아무 프롬프트")

    assert result is None

"""핵심 페이지/API가 최소한 죽지 않고 응답하는지 확인하는 스모크 테스트.

새 기능이 기존 라우트를 완전히 깨뜨리는 것만 잡는 게 목적이라 값 검증은
최소화했다. 세부 로직 테스트는 app/simulator.py, app/data.py에 필요시 추가.
"""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app import data, facilities, geo, report, simulator

client = TestClient(app)


def test_geo_point_maps_to_known_dong():
    # 안양역 인근 좌표는 안양1동으로 매핑돼야 한다.
    assert geo.dong_for_point(126.9226, 37.4018) == "안양1동"
    # 안양시 밖(서울 시청)은 None.
    assert geo.dong_for_point(126.9780, 37.5665) is None
    assert geo.dong_for_point(None, None) is None


def test_facilities_registry_loads_and_maps():
    for kind in facilities.REGISTRY:
        rows = facilities.load_facilities(kind)
        assert rows, f"{kind} 로드 실패"
        # 좌표→동 매핑 실패율이 10% 미만이어야 한다 (데이터 품질 가드).
        assert facilities.unmapped_ratio(kind) < 0.10


def test_supply_by_dong_covers_all_31_dong():
    supply = facilities.supply_by_dong()
    assert set(supply) == {d.dong for d in data.list_dong()}
    # 모든 동에 6개 시설 종류 지표가 있어야 한다 (없으면 0).
    for dong, metrics in supply.items():
        assert set(metrics) == set(facilities.REGISTRY)
        assert all(v >= 0 for v in metrics.values())


def test_hospital_excludes_closed_beds():
    # facilities_hospital.csv에는 폐업·전출 병원이 섞여 있다(47행 중 17행).
    # 병상 공급 집계에는 영업중 병원만 들어가야 한다 (#37 리뷰).
    raw = data.read_csv("facilities_hospital.csv")
    operating_beds = int(raw[raw["bsn_state_nm"].str.contains("영업")]["sickbd_cnt"].sum())
    counted_beds = round(sum(facilities.count_by_dong("hospital").values()))
    assert counted_beds == operating_beds  # 폐업분(약 1,394병상) 미포함
    assert len(facilities.load_facilities("hospital")) < len(raw)  # 일부 행 제외됨
    # 폐업 병원이 특정 동 지표를 튀게 만들지 않는지 — 모든 동 병상/1,000명이 상식적 상한 이내
    for metrics in facilities.supply_by_dong().values():
        assert metrics["hospital"] < 100  # 병상 100개/1,000명 이상은 데이터 이상 신호


def test_demand_supply_gaps_shape_and_signs():
    from app import gap

    rows = gap.demand_supply_gaps()
    assert {r["facility"] for r in rows} == set(gap.SURVEY_TO_SUPPLY)
    demand = data.gu_needed_facility_gap()
    by_facility = {r["facility"]: r for r in rows}
    for r in rows:
        # 수요격차는 data.gu_needed_facility_gap()와 같은 값이어야 한다.
        assert r["demand_gap"] == round(demand[r["facility"]], 1)
        # 공급격차 = 동안 − 만안
        assert r["supply_gap"] == round(r["supply_dongan"] - r["supply_manan"], 3)
        # "우선 검토" = 두 격차의 부호가 같을 때 (만안·동안 양방향, #50 리뷰)
        assert r["agrees"] == (
            (r["demand_gap"] > 0 and r["supply_gap"] > 0)
            or (r["demand_gap"] < 0 and r["supply_gap"] < 0)
        )
        if r["agrees"]:
            assert r["disadvantaged"] == ("만안구" if r["demand_gap"] > 0 else "동안구")
        else:
            assert r["disadvantaged"] is None
    # 도서관: 만안 3.8 < 동안 7.8 수요, 만안 공급도 동안보다 큼 → 둘 다 음수 → 동안구 일치
    lib = by_facility["도서관"]
    assert lib["demand_gap"] < 0 and lib["supply_gap"] < 0
    assert lib["agrees"] is True and lib["disadvantaged"] == "동안구"
    # 일치 항목이 앞으로 정렬돼야 한다.
    agrees = [r["agrees"] for r in rows]
    assert agrees == sorted(agrees, reverse=True)


def test_dong_supply_matches_facilities_module():
    from app import facilities, gap

    d = gap.dong_supply("안양1동")
    assert set(d) == set(facilities.REGISTRY)
    assert gap.dong_supply("존재하지않는동") is None
    # 면적 지표만 1인당, 나머지는 1,000명당
    assert d["park"]["per"] == "1인당" and d["parking"]["per"] == "1,000명당"


def test_clustering_covers_all_dong_and_is_reproducible():
    from app import cluster

    a = cluster.cluster_dong()
    assert 3 <= a["k"] <= 6
    assert set(a["dong_to_cluster"]) == {d.dong for d in data.list_dong()}
    assert sum(c["size"] for c in a["clusters"]) == 31
    assert len(a["clusters"]) == a["k"]
    for c in a["clusters"]:
        assert c["traits"] and c["dongs"]
    # random_state 고정 → 같은 라벨링이 재현돼야 한다.
    cluster.cluster_dong.cache_clear()
    b = cluster.cluster_dong()
    assert a["dong_to_cluster"] == b["dong_to_cluster"]


def test_cluster_features_are_ratios_not_raw_counts():
    from app import cluster

    frame = cluster.feature_frame()
    assert len(frame) == 31
    # 비율 변수는 0~1 범위여야 한다 (규모 편향 방지).
    for col in ("senior_ratio", "youth_ratio", "working_ratio"):
        assert frame[col].between(0, 1).all()
    # 세 비율의 합은 1 (반올림 오차 허용).
    total = frame["senior_ratio"] + frame["youth_ratio"] + frame["working_ratio"]
    assert total.between(0.99, 1.01).all()


def test_dashboard_default():
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert "안양1동" in res.text
    assert "trendChart" in res.text
    # 수요-공급 비교 섹션과 공급 커버리지 한계 문구가 렌더돼야 한다 (#39).
    assert "수요 vs 공급" in res.text
    assert "공공·등록 시설만" in res.text
    # 군집분석 섹션과 "우열이 아님" 경고가 렌더돼야 한다 (#29).
    assert "행정동 유형 군집분석" in res.text
    assert "우열이 아닙니다" in res.text


def test_all_facility_trends_matches_needed_facilities_columns():
    trends = data.all_facility_trends()
    assert set(trends.keys()) == set(data.load_needed_facilities().columns)
    for years in trends.values():
        assert set(years.keys()) == {"2021", "2023", "2025"}


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


def test_simulator_brief_scenario():
    res = client.get("/simulator/brief", params={"scenario_id": "yangji"})
    assert res.status_code == 200
    assert "정책 시뮬레이션 브리핑" in res.text
    assert "정책 제언" in res.text
    # 사회조사 근거 수치가 브리핑에 인용돼야 한다.
    assert "향후 필요" in res.text


def test_simulator_brief_custom_and_error():
    ok = client.get(
        "/simulator/brief",
        params={"region": "만안구", "facility": "공영주차시설", "num_facilities": 3},
    )
    assert ok.status_code == 200
    assert "공영주차시설" in ok.text
    # 잘못된 입력은 500이 아니라 에러 안내 페이지
    bad = client.get(
        "/simulator/brief",
        params={"region": "만안구", "facility": "없는시설", "num_facilities": 1},
    )
    assert bad.status_code == 200
    assert "브리핑을 생성할 수 없습니다" in bad.text


def test_simulator_result_has_brief_link():
    res = client.post("/simulator", data={"scenario_id": "yangji"})
    assert "/simulator/brief?scenario_id=yangji" in res.text


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


def test_simulate_rejects_non_positive_num_facilities():
    # 폼(min="0")/스피너를 우회한 직접 호출로 0·음수가 들어오면 격차가
    # 오히려 커지는 결과가 나온다 → ValueError로 막아야 한다 (#9 A1).
    for bad in (-5, 0):
        try:
            simulator.simulate(region="만안구", facility="공영주차시설", num_facilities=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"num_facilities={bad}는 ValueError를 내야 한다")


def test_simulator_negative_num_facilities_shows_error_not_crash():
    res = client.post(
        "/simulator",
        data={"region": "만안구", "facility": "공영주차시설", "num_facilities": "-5"},
    )
    assert res.status_code == 200
    assert "시뮬레이션을 실행할 수 없습니다" in res.text


def test_api_simulate_negative_num_facilities_returns_error():
    res = client.post(
        "/api/simulate",
        json={"region": "만안구", "facility": "공영주차시설", "num_facilities": -5},
    )
    assert res.status_code == 200
    assert "error" in res.json()


def test_simulate_gap_never_reverses_sign_on_over_supply():
    # 더 목마른 쪽(만안구, 공영주차 41.7 vs 26.5)에 과잉 공급해도 격차 부호가
    # 뒤집히면 안 된다 → 현재 격차(15.2%p)까지만 인정 (#9 A2).
    res = simulator.simulate(region="만안구", facility="공영주차시설", num_facilities=100)
    assert res.current_gap > 0
    assert res.projected_gap >= 0
    assert res.projected_gap <= res.current_gap
    assert res.estimated_reduction <= res.current_gap


def test_simulate_flags_adverse_scenario_when_gap_widens():
    # 필요도가 더 낮은 쪽(동안구)에 공영주차를 투입하면 격차가 벌어진다 →
    # 경고 문구가 채워져야 한다 (#9 A3).
    res = simulator.simulate(region="동안구", facility="공영주차시설", num_facilities=3)
    assert res.projected_gap > res.current_gap
    assert res.adverse_warning
    assert "확대" in res.adverse_warning


def test_simulate_normal_scenario_has_no_adverse_warning():
    res = simulator.simulate(region="만안구", facility="공영주차시설", num_facilities=3)
    assert res.adverse_warning == ""


def test_simulate_budget_below_unit_cost_raises_explicit_error():
    # 예산이 1개소 사업비보다 작으면 조용히 0개소·0효과가 아니라
    # "예산 부족"임을 알리는 ValueError (#9 A4).
    try:
        simulator.simulate(region="만안구", facility="공영주차시설", budget=1000)
    except ValueError as e:
        assert "예산" in str(e)
    else:
        raise AssertionError("예산 부족 시 ValueError를 내야 한다")


def test_api_simulate_budget_below_unit_cost_returns_error():
    res = client.post(
        "/api/simulate",
        json={"region": "만안구", "facility": "공영주차시설", "budget": 1000},
    )
    assert res.status_code == 200
    assert "error" in res.json()


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


def test_api_report_diag_without_key(monkeypatch):
    # 키 없으면 원인이 명확히 보여야 하고, /api/report/{dong}보다 먼저 매칭돼야 한다.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = client.get("/api/report/_diag")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["env"]["OPENAI_API_KEY"] == "MISSING"


def test_diagnose_reports_http_error_without_leaking_key(monkeypatch):
    import io
    import urllib.error

    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")

    def boom(*a, **k):
        raise urllib.error.HTTPError(
            "u", 401, "Unauthorized", {}, io.BytesIO(b'{"error":{"message":"Invalid API Key"}}')
        )

    with patch("app.report.urllib.request.urlopen", boom):
        body = report.diagnose()
    assert body["ok"] is False
    assert "401" in body["reason"]
    assert "Invalid API Key" in body["upstream_error"]
    assert "sk-super-secret-value" not in json.dumps(body, ensure_ascii=False)


def test_api_chat():
    res = client.post("/api/chat", json={"question": "주차시설은 어때?", "dong": "안양1동"})
    assert res.status_code == 200
    assert "answer" in res.json()


def test_chatbot_falls_back_to_rule_based_without_llm(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from app import chatbot

    ans = chatbot.answer("주차시설은 어때?", "안양1동")
    # 규칙 기반 폴백: 구 단위 수치를 결정론적으로 반환.
    assert "만안구 41.7%" in ans and "동안구 26.5%" in ans


def test_chatbot_uses_llm_with_structured_context(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from app import chatbot

    captured = {}

    def fake_llm(prompt, system=None):
        captured["prompt"] = prompt
        captured["system"] = system
        return "LLM 답변입니다."

    monkeypatch.setattr(chatbot, "_call_openai", fake_llm)
    ans = chatbot.answer("도서관 필요한가요?", "평촌동")
    assert ans == "LLM 답변입니다."
    # retrieval 단계가 관련 구조화 데이터를 컨텍스트에 넣어야 한다.
    assert "도서관" in captured["prompt"] and "평촌동" in captured["prompt"]
    assert "구 단위" in captured["system"]


def test_chatbot_falls_back_when_llm_call_fails(monkeypatch):
    # 키는 있는데 LLM 호출이 실패(타임아웃·API 오류 등)해 None이 오는 경로.
    # _call_openai의 예외 처리는 report.py 쪽에서 검증되지만, chatbot.answer()가
    # None을 받아 규칙 기반으로 내려가는지는 따로 확인돼 있지 않았다 (#46).
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from app import chatbot

    monkeypatch.setattr(chatbot, "_call_openai", lambda *a, **k: None)
    ans = chatbot.answer("주차시설은 어때?", "안양1동")
    assert "만안구 41.7%" in ans and "동안구 26.5%" in ans


def test_chatbot_context_and_rule_answer_share_gap_numbers(monkeypatch):
    # 같은 시설에 대해 LLM 컨텍스트와 규칙 기반 답변이 동일한 수치를 써야 한다.
    # 계산이 두 곳에 중복돼 있으면 한쪽만 바뀌어 어긋날 수 있다 (#45).
    from app import chatbot

    manan, dongan, gap = chatbot._facility_gap("공영주차시설")
    ctx = chatbot._build_context("주차시설은 어때?", "안양1동", "공영주차시설")
    needed = ctx["문의 시설 필요도(구 단위, %)"]
    assert (needed["만안구"], needed["동안구"]) == (manan, dongan)
    assert needed["격차(만안구-동안구, %p)"] == gap

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ans = chatbot.answer("주차시설은 어때?", "안양1동")
    assert f"만안구 {manan}%" in ans and f"동안구 {dongan}%" in ans
    assert f"{gap:+.1f}%p" in ans


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


def test_api_dong_boundaries_carries_supply_metrics():
    # 지도 지표 토글(#38)이 한 번의 응답으로 레이어를 바꾸므로, 경계 GeoJSON에
    # 공급 지표가 전부 실려 있어야 한다.
    from app import facilities

    body = client.get("/api/dong-boundaries").json()
    props = {f["properties"]["dong"]: f["properties"] for f in body["features"]}
    supply = facilities.supply_by_dong()

    for kind in facilities.REGISTRY:
        key = f"supply_{kind}"
        assert all(key in p for p in props.values()), f"{key} 누락"
    # 값이 supply_by_dong()과 일치해야 한다 (지도와 카드가 다른 숫자를 보이면 안 됨).
    assert props["안양1동"]["supply_parking"] == supply["안양1동"]["parking"]


def test_map_metric_catalog_matches_registry():
    from app import facilities

    catalog = facilities.metric_catalog()
    keys = [m["key"] for m in catalog]
    assert keys[0] == "total_population"  # 기본 레이어는 인구
    assert set(keys[1:]) == {f"supply_{k}" for k in facilities.REGISTRY}
    # 공원만 1인당 면적, 나머지는 1,000명당 (docs/METRICS.md 규격)
    per = {m["key"]: m["per"] for m in catalog}
    assert per["supply_park"] == "1인당"
    assert per["supply_parking"] == "1,000명당"


def test_dashboard_renders_map_metric_toggle():
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert 'id="mapMetric"' in res.text
    assert "supply_parking" in res.text  # 드롭다운 옵션 + MAP_METRICS 주입


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


def test_call_openai_respects_base_url_and_model(monkeypatch):
    # OPENAI_BASE_URL / OPENAI_MODEL 환경변수로 OpenAI 호환 엔드포인트(Groq 등)를
    # 쓸 수 있어야 한다.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1/")
    monkeypatch.setenv("OPENAI_MODEL", "llama-3.3-70b-versatile")
    captured = {}

    class FakeResponse:
        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["ua"] = req.get_header("User-agent") or ""
        return FakeResponse()

    with patch("app.report.urllib.request.urlopen", fake_urlopen):
        result = report._call_openai("아무 프롬프트")

    assert result == "ok"
    # 후행 슬래시가 있어도 정확히 한 번만 붙어야 한다.
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["body"]["model"] == "llama-3.3-70b-versatile"
    # 무료 티어 토큰 한도·비용 대비 상한 (#28).
    assert captured["body"]["max_tokens"] == report._MAX_TOKENS
    # Cloudflare 봇 차단(error 1010) 회피용 — urllib 기본 UA면 안 된다 (#43).
    assert "python-urllib" not in captured["ua"].lower()


def test_scenario_prompt_omits_raw_internal_fields(monkeypatch):
    # 프롬프트에 원시 __dict__(manan_projected·trend 등)를 그대로 넣으면 모델이
    # 내부 계산값을 실측치처럼 인용할 수 있다 (#28). 레이블된 값만 전달.
    _, res = simulator.run_scenario("yangji")
    prompt = report._scenario_prompt({"name": "n", "description": "d"}, res)
    assert "manan_projected" not in prompt
    assert "trend" not in prompt
    assert "가정 기반 추정" in prompt


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

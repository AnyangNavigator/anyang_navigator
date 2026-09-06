from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import data, report, simulator
from .chatbot import answer as chatbot_answer

app = FastAPI(title="안양 균형발전 내비게이터")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# 네이버 지도(Dynamic Map) Client ID. 도메인 화이트리스트로 보호되는 공개 키라
# JS에 그대로 노출돼도 되지만, 배포 도메인이 바뀌면 NAVER_MAP_CLIENT_ID 환경변수로
# 덮어쓸 수 있게 해둔다.
NAVER_MAP_CLIENT_ID = os.environ.get("NAVER_MAP_CLIENT_ID", "ce1hzsmug6")


def _dong_by_gu() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for d in data.list_dong():
        grouped[d.gu].append(d.dong)
    return dict(grouped)


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
def dashboard(request: Request, dong: str | None = None):
    dong_by_gu = _dong_by_gu()
    selected_dong = dong or next(iter(dong_by_gu["만안구"]))
    d = data.get_dong(selected_dong)
    if d is None:
        selected_dong = next(iter(dong_by_gu["만안구"]))
        d = data.get_dong(selected_dong)

    gu_stats = data.get_gu_survey_snapshot(d.gu)
    density = data.get_facility_density(selected_dong)
    needed_gap = data.gu_needed_facility_gap()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "dong_by_gu": dong_by_gu,
            "selected_dong": selected_dong,
            "gu_stats": gu_stats,
            "density": density,
            "needed_gap": needed_gap,
            "naver_map_client_id": NAVER_MAP_CLIENT_ID,
        },
    )


@app.get("/simulator")
def simulator_page(request: Request):
    return templates.TemplateResponse(
        request,
        "simulator.html",
        {
            "active": "simulator",
            "scenarios": simulator.SCENARIOS,
            "gu_list": data.GU_LIST,
            "facility_list": list(simulator.FACILITY_IMPROVEMENT_COEF.keys()),
            "form": {},
            "result": None,
            "report": None,
            "error": None,
        },
    )


@app.post("/simulator")
def simulator_submit(
    request: Request,
    scenario_id: str | None = Form(None),
    region: str | None = Form(None),
    facility: str | None = Form(None),
    num_facilities: int | None = Form(None),
):
    try:
        if scenario_id:
            scenario, result = simulator.run_scenario(scenario_id)
        else:
            scenario = {
                "name": f"사용자 정의: {region} · {facility}",
                "description": f"{region}에 {facility} {num_facilities}개소를 신규 공급하는 시나리오.",
            }
            result = simulator.simulate(region=region, facility=facility, num_facilities=num_facilities)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "simulator.html",
            {
                "active": "simulator",
                "scenarios": simulator.SCENARIOS,
                "gu_list": data.GU_LIST,
                "facility_list": list(simulator.FACILITY_IMPROVEMENT_COEF.keys()),
                "form": {"region": region, "facility": facility, "num_facilities": num_facilities},
                "result": None,
                "report": None,
                "error": str(e),
            },
        )

    report_text = report.generate_scenario_report(scenario, result)

    return templates.TemplateResponse(
        request,
        "simulator.html",
        {
            "active": "simulator",
            "scenarios": simulator.SCENARIOS,
            "gu_list": data.GU_LIST,
            "facility_list": list(simulator.FACILITY_IMPROVEMENT_COEF.keys()),
            "form": {"region": result.region, "facility": result.facility, "num_facilities": result.num_facilities},
            "result": result,
            "report": report_text,
            "error": None,
        },
    )


@app.get("/api/dong-boundaries")
def api_dong_boundaries():
    """안양시 31개 행정동 경계 GeoJSON(+동별 인구) — 대시보드 choropleth 지도용."""
    return data.dong_boundaries_with_population()


@app.get("/api/dong/{dong_name}")
def api_dong(dong_name: str):
    d = data.get_dong(dong_name)
    if d is None:
        return {"error": f"알 수 없는 행정동: {dong_name}"}
    return {
        "dong_stats": data.get_facility_density(dong_name),
        "gu_stats": data.get_gu_survey_snapshot(d.gu),
    }


@app.get("/api/report/{dong_name}")
def api_report(dong_name: str):
    try:
        text = report.generate_dong_report(dong_name)
    except ValueError as e:
        return {"error": str(e)}
    return {"report": text}


class ChatRequest(BaseModel):
    question: str
    dong: str | None = None


@app.post("/api/chat")
def api_chat(payload: ChatRequest):
    return {"answer": chatbot_answer(payload.question, payload.dong)}


class SimulateRequest(BaseModel):
    region: str
    facility: str
    num_facilities: int | None = None
    budget: float | None = None


@app.post("/api/simulate")
def api_simulate(payload: SimulateRequest):
    try:
        result = simulator.simulate(
            region=payload.region,
            facility=payload.facility,
            num_facilities=payload.num_facilities,
            budget=payload.budget,
        )
    except ValueError as e:
        return {"error": str(e)}
    return {"result": result.__dict__}


class RankScenarioItem(BaseModel):
    region: str
    facility: str
    budget: float | None = None
    num_facilities: int | None = None
    name: str | None = None


class RankRequest(BaseModel):
    scenarios: list[RankScenarioItem]


@app.post("/api/simulate/rank")
def api_simulate_rank(payload: RankRequest):
    try:
        ranked = simulator.rank_scenarios([s.model_dump() for s in payload.scenarios])
    except ValueError as e:
        return {"error": str(e)}
    return {
        "ranked": [
            {
                "rank": r.rank,
                "name": r.name,
                "region": r.result.region,
                "facility": r.result.facility,
                "num_facilities": r.result.num_facilities,
                "budget": r.budget,
                "current_gap": r.result.current_gap,
                "estimated_reduction": r.result.estimated_reduction,
                "projected_gap": r.result.projected_gap,
                "efficiency": r.efficiency,
            }
            for r in ranked
        ]
    }

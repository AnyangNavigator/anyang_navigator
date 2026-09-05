"""What-if 시뮬레이터: 특정 지역에 시설을 추가하면 만안구/동안구 격차가
얼마나 줄어드는지 추정한다.

이 시뮬레이터는 "정밀한 예측"이 아니라 정책 우선순위를 논의하기 위한
의사결정 보조 도구다. 아래 계수는 모두 하드코딩된 가정값이며, 실제 시설
확충 후 필요도 응답률 변화를 추적한 실측 데이터가 아니다 (PROJECT_SPEC.md
4절 참고). UI/리포트에는 반드시 이 가정을 명시할 것.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import data

# 신규 시설 1개소당 "향후 필요하다" 응답률 감소 추정치(%p). 가정값.
FACILITY_IMPROVEMENT_COEF: dict[str, float] = {
    "공영주차시설": 2.0,
    "보건의료시설": 1.8,
    "사회복지시설": 1.5,
    "국공립어린이집": 1.5,
    "공원녹지산책로": 1.0,
    "문화예술회관": 0.8,
    "도서관": 0.8,
    "체육시설": 1.0,
    "기타": 0.5,
}

# 시설 1개소당 개략 사업비(원). 예산->시설 개소 환산용 가정값.
FACILITY_UNIT_COST: dict[str, float] = {
    "공영주차시설": 1_500_000_000,
    "보건의료시설": 3_000_000_000,
    "사회복지시설": 2_500_000_000,
    "국공립어린이집": 1_800_000_000,
    "공원녹지산책로": 800_000_000,
    "문화예술회관": 8_000_000_000,
    "도서관": 4_000_000_000,
    "체육시설": 2_000_000_000,
    "기타": 1_000_000_000,
}

DEFAULT_SCENARIO_ID = "yangji"

SCENARIOS = {
    "yangji": {
        "id": "yangji",
        "name": "양지마을 주거재생 혁신지구 (기본 데모)",
        "region": "만안구",
        "dong": "안양3동",
        "facility": "공영주차시설",
        "num_facilities": 3,
        "budget": 15_300_000_000,  # 총사업비 153억원
        "description": (
            "만안구 안양3동 '양지마을'이 국토부 주거재생 혁신지구 국가 시범사업 대상지로 "
            "지정되어 2026년 철거·착공 예정. 생활SOC(공영주차시설 등) 신규 공급을 가정한다."
        ),
    }
}


@dataclass
class SimulationResult:
    region: str
    facility: str
    num_facilities: int
    current_gap: float
    estimated_reduction: float
    projected_gap: float
    manan_current: float
    dongan_current: float
    manan_projected: float
    assumption_note: str
    trend: dict[str, float] = field(default_factory=dict)


def estimate_facility_count(facility: str, budget: float) -> int:
    unit_cost = FACILITY_UNIT_COST.get(facility, FACILITY_UNIT_COST["기타"])
    if unit_cost <= 0:
        return 0
    return max(0, int(budget // unit_cost))


def simulate(region: str, facility: str, num_facilities: int | None = None, budget: float | None = None) -> SimulationResult:
    if region not in data.GU_LIST:
        raise ValueError(f"region은 {data.GU_LIST} 중 하나여야 합니다: {region}")
    if facility not in FACILITY_IMPROVEMENT_COEF:
        raise ValueError(f"알 수 없는 시설 유형: {facility}")

    if num_facilities is None:
        if budget is None:
            raise ValueError("num_facilities 또는 budget 중 하나는 필요합니다.")
        num_facilities = estimate_facility_count(facility, budget)

    needed = data.load_needed_facilities()
    manan_current = float(needed.loc["만안구", facility])
    dongan_current = float(needed.loc["동안구", facility])
    current_gap = round(manan_current - dongan_current, 1)

    coef = FACILITY_IMPROVEMENT_COEF[facility]
    raw_reduction = coef * num_facilities
    # 격차가 뒤집히지 않도록, 감소폭은 현재 해당 구의 응답률을 초과할 수 없다.
    target_current = manan_current if region == "만안구" else dongan_current
    estimated_reduction = min(raw_reduction, target_current)

    if region == "만안구":
        manan_projected = round(manan_current - estimated_reduction, 1)
        dongan_projected = dongan_current
    else:
        manan_projected = manan_current
        dongan_projected = round(dongan_current - estimated_reduction, 1)

    projected_gap = round(manan_projected - dongan_projected, 1)

    return SimulationResult(
        region=region,
        facility=facility,
        num_facilities=num_facilities,
        current_gap=current_gap,
        estimated_reduction=round(estimated_reduction, 1),
        projected_gap=projected_gap,
        manan_current=manan_current,
        dongan_current=dongan_current,
        manan_projected=manan_projected,
        trend=data.facility_trend(facility),
        assumption_note=(
            f"가정: {facility} 신규 1개소당 '향후 필요' 응답률 -{coef}%p 감소. "
            f"이 값은 실측 추적 데이터가 아닌 정책 논의용 추정치입니다."
        ),
    )


def run_scenario(scenario_id: str = DEFAULT_SCENARIO_ID) -> tuple[dict, SimulationResult]:
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError(f"알 수 없는 시나리오: {scenario_id}")
    result = simulate(
        region=scenario["region"],
        facility=scenario["facility"],
        num_facilities=scenario["num_facilities"],
    )
    return scenario, result

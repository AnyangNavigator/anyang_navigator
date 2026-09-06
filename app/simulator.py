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
    # 투입 지역이 해당 시설 필요도가 더 낮은 쪽이라 격차가 오히려 벌어지는
    # 시나리오일 때 채워지는 경고 문구(#9 A3). 정상 시나리오면 빈 문자열.
    adverse_warning: str = ""
    trend: dict[str, float] = field(default_factory=dict)


# 효율 지표를 "1억원당 예상 격차 감소폭(%p)"으로 환산하기 위한 단위.
BUDGET_UNIT = 100_000_000  # 1억원


@dataclass
class RankedScenario:
    rank: int
    name: str
    budget: float
    efficiency: float  # 1억원당 예상 격차 감소폭(%p)
    result: SimulationResult


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
        # 예산이 1개소 사업비보다 작으면 estimate_facility_count()가 0을 돌려주고,
        # 그대로 두면 "모델이 효과 0이라고 봤다"는 오해를 준다(#9 A4). 예산
        # 부족임을 분명히 알린다. (num_facilities 직접 입력 경로의 0·음수는
        # 아래 A1 가드가 처리.)
        if num_facilities < 1:
            unit_cost = FACILITY_UNIT_COST.get(facility, FACILITY_UNIT_COST["기타"])
            raise ValueError(
                f"입력 예산({budget:,.0f}원)이 {facility} 1개소 사업비"
                f"({unit_cost:,.0f}원)보다 작아 배치할 시설이 없습니다. "
                f"예산을 늘리거나 개소 수를 직접 입력하세요."
            )

    # 폼/API를 우회한 직접 POST로 0·음수가 들어오면 격차가 오히려 커지는
    # 무의미한 결과가 나온다(#9 A1). 1 이상의 정수만 허용하고, 나머지는
    # 각 라우트의 `except ValueError`가 에러 메시지로 처리하게 한다.
    if isinstance(num_facilities, bool) or not isinstance(num_facilities, int) or num_facilities < 1:
        raise ValueError(f"num_facilities는 1 이상의 정수여야 합니다: {num_facilities!r}")

    needed = data.load_needed_facilities()
    manan_current = float(needed.loc["만안구", facility])
    dongan_current = float(needed.loc["동안구", facility])
    current_gap = round(manan_current - dongan_current, 1)

    coef = FACILITY_IMPROVEMENT_COEF[facility]
    raw_reduction = coef * num_facilities

    # 감소폭 상한(#9 A2). 두 경우를 구분한다:
    #  - 투입 지역이 현재 '더 목마른'(응답률이 높은) 쪽이면, 감소폭이 현재
    #    격차를 넘는 순간 부호가 뒤집혀(과잉 공급) 무의미해진다 → 현재 격차까지만.
    #  - 투입 지역이 이미 낮은 쪽이면 격차 역전은 애초에 불가능하고, 응답률이
    #    0 미만으로 내려갈 수 없다는 물리적 하한만 적용한다(격차 확대는 A3 경고).
    higher_region = "만안구" if manan_current >= dongan_current else "동안구"
    target_current = manan_current if region == "만안구" else dongan_current
    cap = abs(current_gap) if region == higher_region else target_current
    estimated_reduction = min(raw_reduction, cap)

    if region == "만안구":
        manan_projected = round(manan_current - estimated_reduction, 1)
        dongan_projected = dongan_current
    else:
        manan_projected = manan_current
        dongan_projected = round(dongan_current - estimated_reduction, 1)

    projected_gap = round(manan_projected - dongan_projected, 1)

    # 투입 지역이 해당 시설 필요도가 더 낮은 쪽이면 격차가 오히려 벌어진다(#9 A3).
    # 시나리오 자체를 막지는 않되, 결과 화면·리포트가 이를 분명히 알리도록 경고를 채운다.
    adverse_warning = ""
    if region != higher_region and raw_reduction > 0 and abs(projected_gap) > abs(current_gap):
        adverse_warning = (
            f"{facility}은(는) {higher_region} 필요도가 더 높은데 {region}에 투입하는 "
            f"시나리오라, 두 구의 격차가 현재 {abs(current_gap)}%p에서 "
            f"{abs(projected_gap)}%p로 오히려 확대됩니다."
        )

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
        adverse_warning=adverse_warning,
        trend=data.facility_trend(facility),
        assumption_note=(
            f"가정: {facility} 신규 1개소당 '향후 필요' 응답률 -{coef}%p 감소. "
            f"이 값은 실측 추적 데이터가 아닌 정책 논의용 추정치입니다."
        ),
    )


def rank_scenarios(scenarios: list[dict]) -> list[RankedScenario]:
    """여러 정책 시나리오를 예산 대비 효과(격차 감소폭 / 예산)로 순위화한다.

    각 시나리오 dict는 아래 키를 받는다:
      - region (필수), facility (필수)
      - budget (원) 또는 num_facilities 중 하나 이상
      - name (선택): 표시용 시나리오명

    budget이 주어지면 estimate_facility_count()로 개소를 환산하고, 그렇지 않으면
    num_facilities를 그대로 쓴다. 효율은 "1억원당 예상 격차 감소폭(%p)"으로,
    budget이 없으면 0으로 둔다(예산 대비 비교 불가). 반환 리스트는 효율 내림차순
    정렬이며 rank는 1부터 부여된다. 계산 로직은 simulate()를 그대로 재사용한다.
    """
    ranked: list[RankedScenario] = []
    for idx, sc in enumerate(scenarios):
        region = sc.get("region")
        facility = sc.get("facility")
        budget = float(sc.get("budget") or 0)
        num_facilities = sc.get("num_facilities")
        if num_facilities is None and budget <= 0:
            raise ValueError(
                f"{idx + 1}번째 시나리오: budget 또는 num_facilities 중 하나는 필요합니다."
            )
        result = simulate(
            region=region,
            facility=facility,
            num_facilities=num_facilities,
            budget=budget if budget > 0 else None,
        )
        efficiency = (
            round(result.estimated_reduction / (budget / BUDGET_UNIT), 4)
            if budget > 0
            else 0.0
        )
        name = sc.get("name") or f"{region} · {facility}"
        ranked.append(
            RankedScenario(rank=0, name=name, budget=budget, efficiency=efficiency, result=result)
        )

    ranked.sort(key=lambda r: r.efficiency, reverse=True)
    for rank, r in enumerate(ranked, start=1):
        r.rank = rank
    return ranked


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

"""수요(사회조사 필요도)와 공급(시설 현황)을 나란히 놓고 구 간 격차를 본다.

기존 대시보드는 **수요**(구 단위 "향후 필요" 응답률) 하나만 봤다. #37이 붙인
`facilities.supply_by_dong()`으로 **공급**(인구 기준 정규화 시설량)을 구 단위로
모아 함께 제시한다.

⚠️ 합성 지수를 만들지 않는 이유 (#34 분석):
공급밀도와 필요도의 순위상관이 ρ ≈ +0.59로 **기대와 반대 부호**다(공급이 많은
쪽이 필요도도 높게 나옴 — 개소수/인구가 시설 용량·품질을 못 담기 때문).
따라서 두 격차를 하나의 점수로 섞으면 서로를 상쇄해 실제 신호가 사라진다.
대신 **두 신호를 따로 보여주고, 방향이 일치하는 시설만 "우선 검토" 로 표시**한다.

⚠️ 공급 지표의 커버리지 한계:
집계 대상이 **공공·등록 시설**뿐이다(공영주차장, 병원급 이상, 도시공원 등).
아파트 부설주차장·민간 의원 같은 민간 공급은 빠져 있어, 민간 공급이 두터운
신도시(동안구)가 과소평가될 수 있다. 이 한계는 /about에도 명시한다.
"""
from __future__ import annotations

from . import data, facilities

# 사회조사 시설 문항 ↔ 보유한 시설 현황 CSV. 둘 다 있는 것만 비교 가능하다.
# 사회복지시설·문화예술회관·체육시설은 공급 데이터가 아직 없어 제외(#33).
SURVEY_TO_SUPPLY: dict[str, str] = {
    "공영주차시설": "parking",
    "도서관": "library",
    "공원녹지산책로": "park",
    "국공립어린이집": "childcare",
    "보건의료시설": "hospital",
}


def _supply_by_gu() -> dict[str, dict[str, float]]:
    """구 → {kind: 인구가중 평균 공급}. 동별 지표를 인구로 가중해 구 단위로 모은다."""
    supply = facilities.supply_by_dong()
    pop = {d.dong: (d.gu, d.total_population) for d in data.list_dong()}
    totals: dict[str, dict[str, float]] = {gu: {} for gu in data.GU_LIST}
    gu_pop: dict[str, int] = {gu: 0 for gu in data.GU_LIST}
    for dong, metrics in supply.items():
        gu, population = pop[dong]
        gu_pop[gu] += population
        for kind, value in metrics.items():
            totals[gu][kind] = totals[gu].get(kind, 0.0) + value * population
    return {
        gu: {kind: round(total / gu_pop[gu], 3) for kind, total in kinds.items()}
        for gu, kinds in totals.items()
    }


def demand_supply_gaps() -> list[dict]:
    """시설별 수요격차·공급격차와 두 신호의 일치 여부.

    - `demand_gap` = 만안 필요도 − 동안 필요도 (%p). 양수 = 만안이 더 목마름.
    - `supply_gap` = 동안 공급 − 만안 공급. 양수 = 만안 공급이 더 적음.
    - **부호가 같으면** 한 구가 "수요는 높은데 공급은 적다" → `agrees=True`.
      만안·동안 어느 쪽이든 성립하므로(균형발전은 양방향) 부호 일치로 판정하고,
      `disadvantaged`에 그 구를 담는다.
    """
    demand = data.gu_needed_facility_gap()
    supply = _supply_by_gu()
    rows: list[dict] = []
    for survey_name, kind in SURVEY_TO_SUPPLY.items():
        manan = supply["만안구"].get(kind, 0.0)
        dongan = supply["동안구"].get(kind, 0.0)
        demand_gap = round(demand[survey_name], 1)
        supply_gap = round(dongan - manan, 3)
        agrees = (demand_gap > 0 and supply_gap > 0) or (demand_gap < 0 and supply_gap < 0)
        rows.append(
            {
                "facility": survey_name,
                "kind": kind,
                "label": facilities.REGISTRY[kind].label,
                "unit": facilities.REGISTRY[kind].unit,
                "demand_gap": demand_gap,
                "supply_manan": manan,
                "supply_dongan": dongan,
                "supply_gap": supply_gap,
                "agrees": agrees,
                # agrees일 때만 의미: 수요·공급 두 신호가 모두 불리한 구.
                "disadvantaged": ("만안구" if demand_gap > 0 else "동안구") if agrees else None,
            }
        )
    # 일치 항목을 앞으로, 그 안에서는 수요격차 절대값이 큰 순.
    rows.sort(key=lambda r: (-r["agrees"], -abs(r["demand_gap"])))
    return rows


def dong_supply(dong_name: str) -> dict[str, dict] | None:
    """동 하나의 공급 지표 — 대시보드 동 단위 카드용. 값 + 라벨/단위를 함께 준다.

    `REGISTRY` 전체(6종, 약국 포함)를 돌려준다. 수요-공급 비교표(`demand_supply_gaps`)는
    사회조사 문항과 대응되는 5종만 쓰지만, 동 카드는 보유한 공급 정보를 모두 보여준다.
    """
    supply = facilities.supply_by_dong().get(dong_name)
    if supply is None:
        return None
    return {
        kind: {
            "value": value,
            "label": facilities.REGISTRY[kind].label,
            "unit": facilities.REGISTRY[kind].unit,
            # 개소/병상은 1,000명당, 면적은 1인당 — supply_by_dong() 규격
            "per": "1인당" if facilities.REGISTRY[kind].unit == "㎡" else "1,000명당",
        }
        for kind, value in supply.items()
    }

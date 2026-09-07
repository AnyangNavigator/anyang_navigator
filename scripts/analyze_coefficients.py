"""시뮬레이터 가정 계수(`FACILITY_IMPROVEMENT_COEF`)의 데이터 기반화 시도 — 분석 스크립트.

이슈 #34. `app/simulator.py`의 계수가 근거 없는 하드코딩 가정값이라, 아래 두
접근으로 데이터에서 도출이 가능한지 검토한다. 결론(2026-09 기준 데이터):
**두 접근 모두 계수를 "도출"하기엔 데이터가 부족하다.** 이 스크립트는 그 판단의
재현 근거이며, 계수는 여전히 명시적 가정값으로 두되 `/about`·`docs/COEFFICIENTS.md`에
도출 시도와 한계를 기록한다.

실행:  python scripts/analyze_coefficients.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import data, facilities  # noqa: E402

# survey_12 시설 컬럼 <-> facilities.REGISTRY kind 대응 (겹치는 것만).
NEED_TO_SUPPLY = {
    "공영주차시설": "parking",
    "보건의료시설": "hospital",
    "국공립어린이집": "childcare",
    "공원녹지산책로": "park",
    "도서관": "library",
}


def gu_supply() -> dict[str, dict[str, float]]:
    """행정동 공급(1,000명당 / 공원은 1인당 ㎡)을 인구가중 평균으로 구 단위 집계."""
    per_dong = facilities.supply_by_dong()
    pop = {d.dong: d.total_population for d in data.list_dong()}
    gu_of = {d.dong: d.gu for d in data.list_dong()}
    out: dict[str, dict[str, float]] = {"만안구": {}, "동안구": {}}
    for kind in facilities.REGISTRY:
        for gu in out:
            num = sum(per_dong[dn][kind] * pop[dn] for dn in pop if gu_of[dn] == gu)
            den = sum(pop[dn] for dn in pop if gu_of[dn] == gu)
            out[gu][kind] = num / den if den else 0.0
    return out


def _spearman(xs: list[float], ys: list[float]) -> float:
    """작은 n용 순위상관 (scipy 없이). 동점은 평균순위."""
    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1)) if n > 1 else 0.0


def approach_b_density_gap() -> None:
    """접근 B: 동별 공급밀도 ↔ 필요도. 공급이 낮을수록 필요도가 높다면
    음의 상관이 나와야 하고, 그 기울기가 '밀도 1단위 개선 시 필요도 Δ'가 된다."""
    print("=== 접근 B: 밀도갭 (구 단위 공급 vs 필요도) ===")
    supply = gu_supply()
    need = data.load_needed_facilities()

    need_levels, supply_levels = [], []
    print(f"{'시설':<12}{'만안 필요도':>10}{'동안 필요도':>10}{'만안 공급':>12}{'동안 공급':>12}"
          f"{'필요도격차':>10}{'공급격차':>12}")
    for need_col, kind in NEED_TO_SUPPLY.items():
        mn_need = float(need.loc["만안구", need_col])
        dn_need = float(need.loc["동안구", need_col])
        mn_sup = supply["만안구"][kind]
        dn_sup = supply["동안구"][kind]
        need_gap = mn_need - dn_need          # 양수 = 만안이 더 목마름
        supply_gap = dn_sup - mn_sup          # 양수 = 만안 공급 부족 (docs/METRICS.md 서사)
        print(f"{need_col:<12}{mn_need:>10.1f}{dn_need:>10.1f}{mn_sup:>12.3f}{dn_sup:>12.3f}"
              f"{need_gap:>+10.1f}{supply_gap:>+12.3f}")
        # 구별 (공급, 필요도) 관측치 2개씩
        need_levels += [mn_need, dn_need]
        supply_levels += [mn_sup, dn_sup]

    rho = _spearman(supply_levels, need_levels)
    print(f"\n공급밀도 vs 필요도 순위상관(rho, n={len(need_levels)}): {rho:+.3f}")
    print("해석: 공급이 낮을수록 필요도가 높다면 rho가 뚜렷한 음수여야 한다.")
    print("실제로는 만안구가 주차·공원 공급이 오히려 더 많은데 필요도도 높다 →")
    print("개소수/인구 방식은 시설 '용량·품질'을 담지 못해(만안 공원면적=수리산,")
    print("주차 노외 소형 등) 필요도를 설명하지 못한다. → 계수 도출 불가.\n")


def approach_a_trend() -> None:
    """접근 A: 2021→2023→2025 안양시 전체 필요도 변화. 같은 기간 시설 공급
    증가분이 있으면 '1개소당 탄력성'을 역산할 수 있으나, 공급 시계열이 없다."""
    print("=== 접근 A: 추세 (안양시 전체 필요도, %p) ===")
    trends = data.all_facility_trends()
    print(f"{'시설':<12}{'2021':>8}{'2023':>8}{'2025':>8}{'Δ21→25':>10}{'Δ23→25':>10}")
    for facility, ys in trends.items():
        y21, y23, y25 = ys.get("2021"), ys.get("2023"), ys.get("2025")
        if None in (y21, y23, y25):
            continue
        print(f"{facility:<12}{y21:>8.1f}{y23:>8.1f}{y25:>8.1f}{y25 - y21:>+10.1f}{y25 - y23:>+10.1f}")
    print("\n해석: 필요도는 웨이브마다 ±3~7%p 비단조로 움직이고(여론·표본·이슈 영향),")
    print("짝지을 '연도별 시설 공급량'이 데이터에 없다. → 1개소당 계수 역산 불가.")
    print("다만 '큰 충격 없이 2년간 최대 ±3%p 수준'이라는 상한은 얻는다 → 현행")
    print("계수 0.8~2.0%p/개소(격차 1개 닫는 데 5~10개소)는 자릿수 상 과하지 않다.\n")


def main() -> None:
    approach_b_density_gap()
    approach_a_trend()
    print("결론: 계수는 명시적 '탄력성 가정값'으로 유지한다. 상대적 크기 순서는")
    print("'현재 미충족 필요도가 큰 시설일수록 1개소 효과도 크다'는 원칙으로 정하고,")
    print("절대값은 접근 A의 ±3%p/2년 envelope 안에서 보수적으로 둔다.")
    print("근거·한계는 /about 4절과 docs/COEFFICIENTS.md에 명시.")


if __name__ == "__main__":
    main()

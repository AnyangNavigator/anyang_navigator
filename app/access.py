"""공간 접근성 — 2단계 흡수권역법(2SFCA, Luo & Wang 2003).

이슈 #73(AI 혁신성 보완). 지금까지의 공급 지표(`facilities.supply_by_dong()`)는
"행정동 안에 몇 개 있는가"만 본다. 그래서 만안구가 개소수는 있어도 실제 도달
가능성은 낮을 수 있다는 걸 못 잡았다 — 공급밀도-필요도 순위상관이 기대와
반대(ρ≈+0.59, `scripts/analyze_coefficients.py`)로 나온 이유 중 하나다.

2SFCA는 시설과 인구를 거리로 묶어 "실제 도달 가능한 공급량"을 계산한다.

  1단계: 시설 j의 공급-수요비 R_j = S_j / Σ(P_k : d(k, j) ≤ d0(kind))
         (j로부터 반경 d0 안에 있는 모든 수요지 k의 인구 합으로 j의 용량을 나눈다)
  2단계: 수요지 i의 접근성 A_i = Σ(R_j : d(i, j) ≤ d0(kind))
         (i로부터 반경 d0 안에 있는 모든 시설 j의 R_j를 더한다)

가정과 한계 (docs/METRICS.md에도 기록):
  - 수요지(인구)는 행정동보다 세밀한 격자가 없어 **행정동 경계 폴리곤의 기하 중심점**에
    그 동 인구 전체가 있다고 근사한다. 실제 인구 분포와 다를 수 있다.
  - 시설-수요지 거리는 직선거리(haversine)다. 실제 보행/도로 경로보다 짧게 잡힌다.
  - 반경(d0)은 시설 유형별 생활권 기준을 참고한 가정값이다(CATCHMENT_BASIS).
  - 행정동 경계 밖 시설(REGISTRY 매핑 실패분)은 포함하지 않는다 — 안양시 밖 시설이
    접경 동 주민에게 주는 실제 접근성 기여는 이 지표가 못 담는다.
"""
from __future__ import annotations

import math
from functools import lru_cache

from . import data, facilities

EARTH_RADIUS_M = 6_371_000.0

# 시설 유형별 흡수권역 반경(m). 생활SOC/도시계획시설 결정기준의 생활권 개념을
# 참고한 가정값 — 정밀 실측이 아니다. 값을 조정할 땐 근거를 여기 남길 것.
CATCHMENT_RADIUS_M: dict[str, float] = {
    "parking": 1_000,     # 근린 생활권 공영주차장
    "library": 1_000,     # 도보 생활권 도서관
    "park": 500,          # 근린공원 유치거리 기준(도시공원법 시행규칙 통상값)
    "childcare": 500,     # 어린이집 도보 통학권
    "hospital": 2_000,    # 병원급 이상은 광역 접근(자차·대중교통 포함)
    "pharmacy": 1_000,
    "large_store": 1_500,  # 대형마트 등 자차 이용 전제
    "market": 1_000,
    "school": 1_000,       # 초·중·고 통합값(현재 REGISTRY가 학교급 미분리)
    "bus_stop": 500,       # 국토부 대중교통 접근성 기준(보행권)
}
_DEFAULT_RADIUS_M = 1_000  # CATCHMENT_RADIUS_M에 없는 신규 kind용 기본값

CATCHMENT_BASIS: dict[str, str] = {
    "parking": "근린 생활권(1km) — 도보+단거리 이동 기준.",
    "library": "도보 생활권(1km).",
    "park": "근린공원 유치거리(500m) — 도시공원 관련 법령 통상 기준.",
    "childcare": "도보 통학권(500m).",
    "hospital": "병원급 이상은 광역 접근(2km) — 자차·대중교통 포함 가정.",
    "pharmacy": "생활권(1km).",
    "large_store": "자차 이용 전제(1.5km).",
    "market": "생활권(1km).",
    "school": "통학권 근사(1km) — 학교급별 실제 통학구역과는 차이 있음.",
    "bus_stop": "보행권(500m) — 대중교통 접근성 표준.",
}


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 위경도 점 사이의 대권거리(m)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _polygon_centroid(ring: list[list[float]]) -> tuple[float, float]:
    """단순 폴리곤 외곽링의 기하 중심점(centroid). ring 좌표는 [lng, lat].

    표준 shoelace 기반 centroid 공식. 안양시 규모(수 km)에서는 위경도를 평면
    좌표처럼 다뤄도 오차가 무시할 수준이다(app/geo.py의 point-in-polygon과 같은 단순화).
    반환값은 (lat, lng) — 이 모듈의 다른 함수들과 인자 순서를 맞춘다.
    """
    if ring[0] == ring[-1]:
        ring = ring[:-1]
    area = 0.0
    cx = 0.0
    cy = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area *= 0.5
    if area == 0:  # 퇴화 폴리곤 방어 — 실제로는 발생하지 않음
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (sum(ys) / len(ys), sum(xs) / len(xs))
    cx /= 6 * area
    cy /= 6 * area
    return (cy, cx)  # (lat, lng)


@lru_cache
def dong_centroids() -> dict[str, tuple[float, float]]:
    """행정동 → (lat, lng) 기하 중심점. 인구가 이 점에 집중돼 있다고 근사한다."""
    gj = data.load_dong_boundaries()
    out: dict[str, tuple[float, float]] = {}
    for feat in gj["features"]:
        dong = feat["properties"].get("dong")
        geom = feat["geometry"]
        # 저장소의 경계 데이터는 전부 Polygon(멀티폴리곤 없음, #42) — 외곽링만 사용.
        exterior = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
        out[dong] = _polygon_centroid(exterior)
    return out


@lru_cache
def accessibility_by_dong(kind: str) -> dict[str, float]:
    """kind별 2SFCA 접근성 점수(행정동 → 인구 1,000명당 접근 가능 공급량).

    facilities.supply_by_dong()의 "개소수/인구"와 같은 단위계라 직접 비교 가능하다.
    """
    if kind not in facilities.REGISTRY:
        raise ValueError(f"알 수 없는 시설 종류: {kind}")
    radius = CATCHMENT_RADIUS_M.get(kind, _DEFAULT_RADIUS_M)
    spec = facilities.REGISTRY[kind]
    centroids = dong_centroids()
    pop = {d.dong: d.total_population for d in data.list_dong()}

    sites = [
        (f["lat"], f["lng"], f["weight"] if (spec.weight_col and f["weight"]) else 1.0)
        for f in facilities.load_facilities(kind)
        if f["dong"] and f["lat"] is not None and f["lng"] is not None
    ]

    # 1단계: 시설별 공급-수요비 R_j.
    ratios: list[float] = []
    for flat, flng, weight in sites:
        demand = sum(
            pop[dong] for dong, (dlat, dlng) in centroids.items()
            if haversine_m(flat, flng, dlat, dlng) <= radius
        )
        ratios.append(weight / demand if demand > 0 else 0.0)

    # 2단계: 수요지(행정동)별 접근성 A_i = 반경 안 R_j의 합.
    # supply_by_dong()과 단위를 맞춘다: 면적(㎡) 가중 시설은 1인당, 나머지는 1,000명당.
    scale = 1 if spec.unit == "㎡" else 1000
    result: dict[str, float] = {}
    for dong, (dlat, dlng) in centroids.items():
        total = sum(
            r for (flat, flng, _), r in zip(sites, ratios)
            if haversine_m(dlat, dlng, flat, flng) <= radius
        )
        result[dong] = round(total * scale, 4)
    return result


@lru_cache
def accessibility_all() -> dict[str, dict[str, float]]:
    """행정동 → {kind: 접근성 점수}. facilities.supply_by_dong()과 같은 모양."""
    result: dict[str, dict[str, float]] = {d.dong: {} for d in data.list_dong()}
    for kind in facilities.REGISTRY:
        for dong, score in accessibility_by_dong(kind).items():
            result[dong][kind] = score
    return result


def dong_access(dong_name: str) -> dict[str, dict] | None:
    """동 하나의 접근성 지표 — 대시보드 동 카드용. 값 + 라벨/단위/반경을 함께 준다."""
    all_scores = accessibility_all()
    scores = all_scores.get(dong_name)
    if scores is None:
        return None
    return {
        kind: {
            "value": value,
            "label": facilities.REGISTRY[kind].label,
            "per": "1인당" if facilities.REGISTRY[kind].unit == "㎡" else "1,000명당",
            "radius_m": CATCHMENT_RADIUS_M.get(kind, _DEFAULT_RADIUS_M),
        }
        for kind, value in scores.items()
    }


def access_metric_catalog() -> list[dict]:
    """지도 지표 토글에 얹을 접근성 레이어 정의. facilities.metric_catalog()와 같은 모양."""
    catalog = []
    for kind, spec in facilities.REGISTRY.items():
        radius_km = CATCHMENT_RADIUS_M.get(kind, _DEFAULT_RADIUS_M) / 1000
        per = "1인당" if spec.unit == "㎡" else "1,000명당"
        catalog.append(
            {
                "key": f"access_{kind}",
                "label": f"{spec.label} 접근성(2SFCA)",
                "unit": f"반경{radius_km:g}km",
                "per": per,
                "low": "접근성 낮음",
                "high": "접근성 높음",
            }
        )
    return catalog


def boundaries_with_access(geojson: dict) -> dict:
    """기존 경계 GeoJSON(properties에 supply_* 등이 있는)에 access_<kind>를 얹는다.

    facilities.boundaries_with_metrics()가 만든 결과를 받아 확장한다 — access.py가
    facilities.py에 의존하는 방향만 있어야 하므로(순환참조 방지) 이 함수는
    호출부(main.py)에서 조합해 쓴다.
    """
    all_scores = accessibility_all()
    features = []
    for feat in geojson["features"]:
        dong = feat["properties"].get("dong")
        scores = all_scores.get(dong, {})
        props = {**feat["properties"]}
        for kind in facilities.REGISTRY:
            props[f"access_{kind}"] = scores.get(kind)
        features.append({**feat, "properties": props})
    return {"type": "FeatureCollection", "features": features}

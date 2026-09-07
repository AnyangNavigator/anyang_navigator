"""시설 현황 CSV(6종) 로딩 + 행정동 단위 집계.

저장소의 `data/facilities_*.csv`는 위경도만 있고 행정동 컬럼이 없다. 여기서
`app.geo.dong_for_point`으로 동을 붙이고, 인구 기준으로 정규화한 공급 지표를
만든다. CSV를 추가하려면 아래 `REGISTRY`에 한 줄만 넣으면 된다.

공급 지표 규격 (docs/METRICS.md):
  - 기본: 인구 1,000명당 개소수
  - 가중치(weight) 컬럼이 있으면 개소수 대신 그 합을 씀
    · 공원: PARK_AR(㎡) → 1인당 공원면적(㎡)
    · 병원: sickbd_cnt(병상수) → 1,000명당 병상수
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from . import data
from .geo import dong_for_point


@dataclass(frozen=True)
class FacilitySpec:
    kind: str
    filename: str
    lat_col: str
    lng_col: str
    weight_col: str | None  # None이면 개소수, 있으면 그 값의 합
    label: str
    unit: str  # "개소" | "㎡" | "병상"


REGISTRY: dict[str, FacilitySpec] = {
    "parking": FacilitySpec("parking", "facilities_parking.csv", "LATITUDE", "LONGITUDE", None, "공영주차장", "개소"),
    "library": FacilitySpec("library", "facilities_library.csv", "LATITUDE", "LONGITUDE", None, "도서관", "개소"),
    "park": FacilitySpec("park", "facilities_park.csv", "LATITUDE", "LONGITUDE", "PARK_AR", "도시공원", "㎡"),
    "childcare": FacilitySpec("childcare", "facilities_childcare.csv", "wgs84_lat", "wgs84_logt", None, "어린이집·유치원", "개소"),
    "hospital": FacilitySpec("hospital", "facilities_hospital.csv", "refine_wgs84_lat", "refine_wgs84_logt", "sickbd_cnt", "병원(병원급 이상)", "병상"),
    "pharmacy": FacilitySpec("pharmacy", "facilities_pharmacy.csv", "refine_wgs84_lat", "refine_wgs84_logt", None, "약국", "개소"),
}


def _to_float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


@lru_cache
def load_facilities(kind: str) -> list[dict]:
    """시설 목록. 각 항목에 dong(행정동명 또는 None)·lat·lng·weight를 붙인다."""
    spec = REGISTRY.get(kind)
    if spec is None:
        raise ValueError(f"알 수 없는 시설 종류: {kind} (가능: {sorted(REGISTRY)})")
    df = data._read_csv(spec.filename)
    out: list[dict] = []
    for row in df.to_dict("records"):
        lat = _to_float(row.get(spec.lat_col))
        lng = _to_float(row.get(spec.lng_col))
        weight = _to_float(row.get(spec.weight_col)) if spec.weight_col else None
        out.append(
            {
                "raw": row,
                "lat": lat,
                "lng": lng,
                "weight": weight,
                "dong": dong_for_point(lng, lat) if lat and lng else None,
            }
        )
    return out


def count_by_dong(kind: str) -> dict[str, float]:
    """행정동별 값. weight 컬럼이 없으면 개소수, 있으면 weight 합. 매핑 실패분은 제외."""
    spec = REGISTRY[kind]
    agg: dict[str, float] = {}
    for f in load_facilities(kind):
        if not f["dong"]:
            continue
        add = f["weight"] if (spec.weight_col and f["weight"] is not None) else 1.0
        agg[f["dong"]] = agg.get(f["dong"], 0.0) + add
    return agg


def unmapped_ratio(kind: str) -> float:
    """좌표→동 매핑에 실패한 비율(0~1). 데이터 품질 점검용."""
    rows = load_facilities(kind)
    if not rows:
        return 0.0
    return sum(1 for f in rows if not f["dong"]) / len(rows)


def supply_by_dong() -> dict[str, dict[str, float]]:
    """행정동 → {kind: 인구 1,000명당 값}. 공원은 1인당 ㎡, 병원은 1,000명당 병상수.

    대시보드 choropleth 공급 레이어·군집분석 특징변수·시뮬레이터 밀도갭이 공유.
    """
    pop = {d.dong: d.total_population for d in data.list_dong()}
    result: dict[str, dict[str, float]] = {dong: {} for dong in pop}
    for kind, spec in REGISTRY.items():
        raw = count_by_dong(kind)
        for dong, population in pop.items():
            if population <= 0:
                continue
            value = raw.get(dong, 0.0)
            if spec.unit == "㎡":
                result[dong][kind] = round(value / population, 2)  # 1인당 면적
            else:
                result[dong][kind] = round(value / population * 1000, 3)  # 1,000명당
    return result

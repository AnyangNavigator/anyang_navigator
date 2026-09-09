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

import math
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
    status_col: str | None = None  # 영업상태 컬럼 (있는 CSV만)
    status_ok: str = "영업"  # status_col 값에 이 문자열이 있어야 유효


REGISTRY: dict[str, FacilitySpec] = {
    "parking": FacilitySpec("parking", "facilities_parking.csv", "LATITUDE", "LONGITUDE", None, "공영주차장", "개소"),
    "library": FacilitySpec("library", "facilities_library.csv", "LATITUDE", "LONGITUDE", None, "도서관", "개소"),
    "park": FacilitySpec("park", "facilities_park.csv", "LATITUDE", "LONGITUDE", "PARK_AR", "도시공원", "㎡"),
    "childcare": FacilitySpec("childcare", "facilities_childcare.csv", "wgs84_lat", "wgs84_logt", None, "어린이집", "개소"),
    # 원본에 폐업·전출 병원이 섞여 있어(47행 중 17행) 병상수가 ~38% 부풀려짐 → 영업중만 집계.
    "hospital": FacilitySpec("hospital", "facilities_hospital.csv", "refine_wgs84_lat", "refine_wgs84_logt", "sickbd_cnt", "병원(병원급 이상)", "병상", status_col="bsn_state_nm"),
    "pharmacy": FacilitySpec("pharmacy", "facilities_pharmacy.csv", "refine_wgs84_lat", "refine_wgs84_logt", None, "약국", "개소"),
}


def _to_float(v: str | None) -> float | None:
    try:
        f = float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return None if (f is not None and math.isnan(f)) else f


@lru_cache
def load_facilities(kind: str) -> list[dict]:
    """시설 목록. 각 항목에 dong(행정동명 또는 None)·lat·lng·weight를 붙인다."""
    spec = REGISTRY.get(kind)
    if spec is None:
        raise ValueError(f"알 수 없는 시설 종류: {kind} (가능: {sorted(REGISTRY)})")
    df = data.read_csv(spec.filename)
    out: list[dict] = []
    for row in df.to_dict("records"):
        if spec.status_col is not None:
            state = str(row.get(spec.status_col) or "")
            if spec.status_ok not in state:  # 폐업·전출 등 제외
                continue
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


@lru_cache
def boundaries_with_metrics() -> dict:
    """행정동 경계 GeoJSON에 인구 + 공급 지표를 붙인다 (지도 choropleth 레이어용).

    `data.dong_boundaries_with_population()`의 확장판. properties에 기존
    `total_population`은 그대로 두고(하위호환) `supply_<kind>`를 추가한다.
    데이터가 없는 동은 해당 키가 None으로 내려가 프런트에서 회색 처리된다.

    facilities -> data 방향 의존만 있으므로 이 함수는 data.py가 아니라 여기에 둔다
    (data.py가 facilities를 import하면 순환 참조).
    """
    boundaries = data.dong_boundaries_with_population()
    supply = supply_by_dong()
    features = []
    for feat in boundaries["features"]:
        dong = feat["properties"].get("dong")
        metrics = supply.get(dong, {})
        props = {**feat["properties"]}
        for kind in REGISTRY:
            props[f"supply_{kind}"] = metrics.get(kind)
        features.append({**feat, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def metric_catalog() -> list[dict]:
    """지도 지표 토글 메뉴 정의. 프런트가 이 목록으로 드롭다운·범례를 만든다."""
    catalog = [
        {
            "key": "total_population",
            "label": "인구 규모",
            "unit": "명",
            "per": "",
            "low": "인구 적음",
            "high": "인구 많음",
        }
    ]
    for kind, spec in REGISTRY.items():
        per = "1인당" if spec.unit == "㎡" else "1,000명당"
        catalog.append(
            {
                "key": f"supply_{kind}",
                "label": spec.label,
                "unit": spec.unit,
                "per": per,
                "low": "공급 적음",
                "high": "공급 많음",
            }
        )
    return catalog


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

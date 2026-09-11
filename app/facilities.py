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
import re
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
    # 이름이 이 정규식에 걸리는 행을 제외한다. 한 시설이 두 CSV에 중복 등재된
    # 경우(대규모점포 대장에 전통시장이 함께 잡힘) 어느 kind가 담당할지 가르는 용도.
    exclude_name_pattern: str | None = None
    name_col: str | None = None  # exclude_name_pattern을 적용할 컬럼
    # 좌표→동 매핑 실패 허용 상한. 원본 CSV의 좌표 충실도가 종류마다 달라
    # 일괄 10%로 묶을 수 없다. 값을 올릴 땐 반드시 이유를 주석으로 남길 것.
    max_unmapped: float = 0.10


REGISTRY: dict[str, FacilitySpec] = {
    "parking": FacilitySpec("parking", "facilities_parking.csv", "LATITUDE", "LONGITUDE", None, "공영주차장", "개소"),
    "library": FacilitySpec("library", "facilities_library.csv", "LATITUDE", "LONGITUDE", None, "도서관", "개소"),
    "park": FacilitySpec("park", "facilities_park.csv", "LATITUDE", "LONGITUDE", "PARK_AR", "도시공원", "㎡"),
    "childcare": FacilitySpec("childcare", "facilities_childcare.csv", "wgs84_lat", "wgs84_logt", None, "어린이집", "개소"),
    # 원본에 폐업·전출 병원이 섞여 있어(47행 중 17행) 병상수가 ~38% 부풀려짐 → 영업중만 집계.
    "hospital": FacilitySpec("hospital", "facilities_hospital.csv", "refine_wgs84_lat", "refine_wgs84_logt", "sickbd_cnt", "병원(병원급 이상)", "병상", status_col="bsn_state_nm"),
    "pharmacy": FacilitySpec("pharmacy", "facilities_pharmacy.csv", "refine_wgs84_lat", "refine_wgs84_logt", None, "약국", "개소"),
    # 대규모점포 대장에는 전통시장도 함께 등재된다(유통산업발전법상 '시장'도 대규모점포).
    # 시장은 아래 market CSV가 점포수·취급품목까지 갖춘 더 정확한 출처이므로 그쪽에 맡기고,
    # 여기서는 시장·상가를 빼 "대형마트·백화점·쇼핑몰" 의미로 좁힌다. 두 kind의 중복 집계도
    # 이걸로 막는다(회귀 테스트: test_large_store_and_market_do_not_double_count).
    # max_unmapped=0.15 — 정상영업 20건 중 2건(GS THE FRESH 안양비산점, 안양국제유통단지)이
    # 원본에 좌표가 없어 10.0%다. 기본 10% 가드에 정확히 걸려 종류별 상한을 둔다.
    "large_store": FacilitySpec(
        "large_store", "facilities_large_store.csv", "refine_wgs84_lat", "refine_wgs84_logt", None,
        "대규모점포", "개소", status_col="bsn_state_nm", status_ok="정상영업",
        exclude_name_pattern="시장|상가", name_col="bizplc_nm", max_unmapped=0.15,
    ),
    "market": FacilitySpec("market", "facilities_market.csv", "LATITUDE", "LONGITUDE", None, "전통시장", "개소"),
    # 원본은 전국 학교 표준데이터라 폐교도 섞일 수 있음(현재 안양시분 86건은 전부 운영중이나
    # 재추출 시 대비해 상태 필터를 걸어 둔다). 컬럼명은 원본 그대로(한글) 보존.
    "school": FacilitySpec(
        "school", "facilities_school.csv", "위도", "경도", None, "학교(초·중·고)", "개소",
        status_col="운영상태", status_ok="운영",
    ),
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
    exclude = re.compile(spec.exclude_name_pattern) if spec.exclude_name_pattern else None
    out: list[dict] = []
    for row in df.to_dict("records"):
        if spec.status_col is not None:
            state = str(row.get(spec.status_col) or "")
            if spec.status_ok not in state:  # 폐업·전출 등 제외
                continue
        if exclude is not None and spec.name_col:
            if exclude.search(str(row.get(spec.name_col) or "")):  # 다른 kind가 담당하는 시설
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

"""좌표 → 행정동 매핑. 시설 CSV(위경도만 있음)를 행정동 단위로 집계하기 위한 공통 헬퍼.

의존성 없이 순수 파이썬 ray-casting point-in-polygon으로 구현한다. 안양시 31개
행정동 경계는 전부 MultiPolygon이며, 각 폴리곤은 [외곽링, 구멍링...] 구조다.
구멍(hole)은 even-odd 규칙으로 자동 처리된다(링을 하나씩 토글).

이 모듈은 #29(군집분석)·#33(데이터 소싱)·공급 지표 레이어가 공유한다 — 매핑
로직을 여기 한 곳에만 둔다.
"""
from __future__ import annotations

import json
from functools import lru_cache

from . import data


def _point_in_ring(lng: float, lat: float, ring: list[list[float]]) -> bool:
    """ray-casting: 점이 단일 링(닫힌 경로) 내부면 True. ring은 [[lng, lat], ...]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _point_in_polygon(lng: float, lat: float, polygon: list[list[list[float]]]) -> bool:
    """polygon = [외곽링, 구멍링...]. 외곽에 들어가고 구멍에 안 들어가면 True."""
    if not polygon or not _point_in_ring(lng, lat, polygon[0]):
        return False
    for hole in polygon[1:]:
        if _point_in_ring(lng, lat, hole):
            return False
    return True


@lru_cache
def _dong_polygons() -> list[tuple[str, list, tuple[float, float, float, float]]]:
    """(동명, MultiPolygon 좌표, bbox) 목록. bbox로 빠르게 후보를 거른다."""
    path = data.DATA_DIR / "anyang_dong_boundaries.geojson"
    gj = json.loads(path.read_text(encoding="utf-8"))
    out: list[tuple[str, list, tuple[float, float, float, float]]] = []
    for feat in gj["features"]:
        dong = feat["properties"].get("dong")
        geom = feat["geometry"]
        polys = (
            [geom["coordinates"]]
            if geom["type"] == "Polygon"
            else geom["coordinates"]  # MultiPolygon
        )
        xs = [pt[0] for poly in polys for ring in poly for pt in ring]
        ys = [pt[1] for poly in polys for ring in poly for pt in ring]
        out.append((dong, polys, (min(xs), min(ys), max(xs), max(ys))))
    return out


def dong_for_point(lng: float, lat: float) -> str | None:
    """위경도가 속한 안양시 행정동명. 안양시 밖이거나 좌표가 없으면 None."""
    if lng is None or lat is None:
        return None
    for dong, polys, (minx, miny, maxx, maxy) in _dong_polygons():
        if not (minx <= lng <= maxx and miny <= lat <= maxy):
            continue
        for poly in polys:
            if _point_in_polygon(lng, lat, poly):
                return dong
    return None

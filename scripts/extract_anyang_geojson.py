"""
안양시 31개 행정동 경계 GeoJSON을 공식 공공데이터 출처(SGIS, data.go.kr)에서
추출해서 data/anyang_dong_boundaries.geojson 으로 저장한다.

이슈 #30: 행정동 경계 GeoJSON을 vworld/SGIS 공식 출처로 교체 (공공데이터 활용)
(이전 출처였던 개인 저장소 vuski/admdongkor 를 대체한다.)

== 출처 ==
국가데이터처_SGIS 행정구역 통계 및 경계 (data.go.kr, 데이터셋 ID 15129688)
https://www.data.go.kr/data/15129688/fileData.do
파일: "2. 경계/3. 2025년 2분기 기준 행정동 경계/bnd_dong_00_2025_2Q.*"
기준일: 2025-06-30. 로그인/API키 불필요, 무료, 전국 범위.

== 좌표계 ==
원본 좌표계는 bnd_dong_00_2025_2Q.prj 에 아래와 같이 기록되어 있다 (EPSG:5179,
"Korea 2000 / Unified CS Korea"):

    PROJCS["Korea_2000_Korea_Unified_Coordinate_System",
        GEOGCS["GCS_Korea_2000", DATUM["D_Korea_2000",
            SPHEROID["GRS_1980", 6378137.0, 298.257222101]]],
        PROJECTION["Transverse_Mercator"],
        PARAMETER["False_Easting", 1000000.0],
        PARAMETER["False_Northing", 2000000.0],
        PARAMETER["Central_Meridian", 127.5],
        PARAMETER["Scale_Factor", 0.9996],
        PARAMETER["Latitude_Of_Origin", 38.0]]

이 스크립트는 위 파라미터로 EPSG:5179 -> WGS84(EPSG:4326) 역변환을 직접 구현해서
적용한다 (Transverse Mercator 역변환, Snyder "Map Projections: A Working Manual",
USGS Professional Paper 1395 공식). geopandas/pyshp/pyproj 등 외부 패키지가 전혀
없어도 동작하도록 표준 라이브러리만 사용한다 — ESRI Shapefile(.shp/.shx/.dbf)도
직접 파싱한다.

== 사용법 ==
1) 위 data.go.kr 페이지에서 압축파일을 다운로드한다. (다운로드 버튼이 JS로
   동작해서 URL을 통한 자동 다운로드는 불가능하다 — 브라우저에서 직접 클릭해야
   한다.)
2) zip 안의 "2. 경계/3. 2025년 2분기 기준 행정동 경계/" 폴더를 통째로 압축
   해제한다 (bnd_dong_00_2025_2Q.shp/.shx/.dbf/.prj/.cpg 5개 파일이 있어야 한다).
3) 아래처럼 그 폴더 경로를 인자로 실행한다:

    python scripts/extract_anyang_geojson.py "<압축해제한 폴더 경로>"

   예)
    python scripts/extract_anyang_geojson.py "C:\\Users\\...\\Downloads\\국가데이터처_SGIS 행정구역 통계 및 경계\\2. 경계\\3. 2025년 2분기 기준 행정동 경계"

== 안양시 만안구 동 이름 변경 반영 ==
이 shapefile(기준일 2025-06-30)의 만안구 동 이름은 2025-04-30 안양시 개칭 공고
이전 이름(박달1동/박달2동)을 쓰고 있다. population_by_dong.csv 등 이 프로젝트의
나머지 데이터는 개칭 이후 이름(박달동/호현동)을 쓰므로, 아래 RENAME 매핑으로
맞춰준다. (경계 자체는 변경 없음 — 이름만 바뀐 순수 개칭.)
참고: 안양시 공식 발표 (2025-04-30 시행), 관련 보도 다수 확인.
"""
from __future__ import annotations

import glob
import json
import math
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "anyang_dong_boundaries.geojson"

# population_by_dong.csv 에 있는 31개 행정동과 그 소속 구.
DONG_TO_GU = {
    "안양1동": "만안구", "안양2동": "만안구", "안양3동": "만안구", "안양4동": "만안구",
    "안양5동": "만안구", "안양6동": "만안구", "안양7동": "만안구", "안양8동": "만안구",
    "안양9동": "만안구", "석수1동": "만안구", "석수2동": "만안구", "충훈동": "만안구",
    "박달동": "만안구", "호현동": "만안구",
    "비산1동": "동안구", "비산2동": "동안구", "비산3동": "동안구", "부흥동": "동안구",
    "달안동": "동안구", "관양동": "동안구", "인덕원동": "동안구", "부림동": "동안구",
    "평촌동": "동안구", "평안동": "동안구", "귀인동": "동안구", "호계1동": "동안구",
    "호계2동": "동안구", "호계3동": "동안구", "범계동": "동안구", "신촌동": "동안구",
    "갈산동": "동안구",
}

# 원본 소스(2025-06-30 기준)의 이름 -> 2025-04-30 안양시 개칭 이후 이름
RENAME = {"박달1동": "박달동", "박달2동": "호현동"}

# 안양시 행정동 코드(ADM_CD)는 "3104"로 시작한다 (경기도=31, 안양시=04).
# 동 이름만으로 필터링하면 다른 시/군의 동명(예: "비산1동"이 타 지역에도 존재)과
# 충돌할 수 있어 ADM_CD 접두사로 안전하게 걸러낸다.
ADM_CD_PREFIX = "3104"

# EPSG:5179 (Korea 2000 / Unified CS Korea) 투영 파라미터
_A = 6378137.0
_F = 1 / 298.257222101
_LON0 = math.radians(127.5)
_LAT0 = math.radians(38.0)
_K0 = 0.9996
_FE = 1_000_000.0
_FN = 2_000_000.0


def tm_inverse(x: float, y: float) -> tuple[float, float]:
    """EPSG:5179 (x, y) 미터 좌표를 WGS84 (lon, lat) 도(度) 좌표로 역변환한다."""
    e2 = _F * (2 - _F)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    m0 = _A * (
        (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * _LAT0
        - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * _LAT0)
        + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * _LAT0)
        - (35 * e2 ** 3 / 3072) * math.sin(6 * _LAT0)
    )
    m = m0 + (y - _FN) / _K0
    mu = m / (_A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))

    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    )

    e2p = e2 / (1 - e2)
    c1 = e2p * math.cos(phi1) ** 2
    t1 = math.tan(phi1) ** 2
    n1 = _A / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    r1 = _A * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = (x - _FE) / (n1 * _K0)

    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * e2p) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * e2p - 3 * c1 ** 2) * d ** 6 / 720
    )
    lon = _LON0 + (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * e2p + 24 * t1 ** 2) * d ** 5 / 120
    ) / math.cos(phi1)

    return math.degrees(lon), math.degrees(lat)


# ---- 최소한의 순수 파이썬 dBase III(.dbf) 리더 ----
# (ESRI Shapefile의 속성 테이블은 dBase III 형식이다.)

def read_dbf(path: str, encoding: str = "utf-8") -> tuple[list[tuple[str, str, int]], list[dict | None]]:
    with open(path, "rb") as f:
        data = f.read()

    num_records = struct.unpack("<I", data[4:8])[0]
    header_len = struct.unpack("<H", data[8:10])[0]
    record_len = struct.unpack("<H", data[10:12])[0]

    fields = []
    pos = 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\x00")[0].decode("ascii")
        ftype = chr(data[pos + 11])
        flen = data[pos + 16]
        fields.append((name, ftype, flen))
        pos += 32

    records: list[dict | None] = []
    rec_start = header_len
    for i in range(num_records):
        offset = rec_start + i * record_len
        if data[offset:offset + 1] == b"*":
            records.append(None)
            continue
        row = {}
        fpos = offset + 1
        for name, ftype, flen in fields:
            raw = data[fpos:fpos + flen]
            fpos += flen
            row[name] = raw.decode(encoding, errors="replace").strip()
        records.append(row)

    return fields, records


# ---- 최소한의 순수 파이썬 ESRI Shapefile(.shp/.shx) 리더 (Polygon만 지원) ----

def read_shx_offsets(path: str) -> list[tuple[int, int]]:
    with open(path, "rb") as f:
        data = f.read()
    n = (len(data) - 100) // 8
    offsets = []
    for i in range(n):
        off, length = struct.unpack(">II", data[100 + i * 8: 100 + i * 8 + 8])
        offsets.append((off * 2, length * 2))  # 16비트 워드 단위 -> 바이트 단위
    return offsets


def read_polygon_record(f, byte_offset: int) -> list[list[tuple[float, float]]]:
    f.seek(byte_offset)
    _rec_num, content_len_words = struct.unpack(">II", f.read(8))
    content = f.read(content_len_words * 2)
    shape_type = struct.unpack("<i", content[0:4])[0]
    if shape_type != 5:
        raise ValueError(f"Polygon(5) 타입만 지원한다 (got shape_type={shape_type})")
    num_parts, num_points = struct.unpack("<ii", content[36:44])
    parts = struct.unpack(f"<{num_parts}i", content[44:44 + 4 * num_parts])
    pts_start = 44 + 4 * num_parts
    points = []
    for i in range(num_points):
        x, y = struct.unpack("<dd", content[pts_start + 16 * i: pts_start + 16 * i + 16])
        points.append((x, y))
    rings = []
    for i, start in enumerate(parts):
        end = parts[i + 1] if i + 1 < len(parts) else num_points
        rings.append(points[start:end])
    return rings


def _ring_signed_area(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def rings_to_geojson_geometry(rings: list[list[tuple[float, float]]]) -> dict:
    """Shapefile 링(외곽=시계방향, 구멍=반시계방향)을 GeoJSON
    Polygon/MultiPolygon 좌표(외곽=반시계방향, 구멍=시계방향, RFC 7946)로
    변환하면서 각 점을 EPSG:5179 -> WGS84로 재투영한다."""
    polygons: list[list[list[tuple[float, float]]]] = []
    for ring in rings:
        is_exterior = _ring_signed_area(ring) < 0  # shapefile 관례: 외곽=CW
        if is_exterior or not polygons:
            polygons.append([ring])
        else:
            polygons[-1].append(ring)

    def to_wgs84_and_fix_winding(ring):
        coords = [tm_inverse(x, y) for x, y in ring]
        coords.reverse()  # CW<->CCW 반전 (등각투영이므로 회전 방향은 보존됨)
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return coords

    geo_polygons = []
    for poly in polygons:
        exterior = to_wgs84_and_fix_winding(poly[0])
        holes = [to_wgs84_and_fix_winding(h) for h in poly[1:]]
        geo_polygons.append([exterior] + holes)

    if len(geo_polygons) == 1:
        return {"type": "Polygon", "coordinates": geo_polygons[0]}
    return {"type": "MultiPolygon", "coordinates": geo_polygons}


def find_shapefile_base(src_dir: str) -> str:
    """src_dir 안에서 .shp 파일을 찾아 확장자를 뺀 경로(base)를 반환한다."""
    candidates = glob.glob(os.path.join(src_dir, "*.shp"))
    candidates += glob.glob(os.path.join(src_dir, "**", "*.shp"), recursive=True)
    candidates = sorted(set(candidates))
    if not candidates:
        raise SystemExit(f"'{src_dir}' 안에서 .shp 파일을 찾지 못했다.")
    if len(candidates) > 1:
        # bnd_dong_00_2025_2Q.shp 처럼 이름에 "dong"이 들어간 것을 우선한다.
        preferred = [c for c in candidates if "dong" in os.path.basename(c).lower()]
        if len(preferred) == 1:
            candidates = preferred
        else:
            raise SystemExit(
                "'.shp' 파일이 여러 개 발견됐다. 정확한 폴더 경로를 지정해달라:\n"
                + "\n".join(candidates)
            )
    return candidates[0][: -len(".shp")]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "사용법: python scripts/extract_anyang_geojson.py <bnd_dong_00_2025_2Q.* 파일이 있는 폴더>\n"
            "(자세한 다운로드 방법은 이 파일 상단의 docstring 참고)"
        )
    src_dir = sys.argv[1]
    base = find_shapefile_base(src_dir)
    shp_path, shx_path, dbf_path = base + ".shp", base + ".shx", base + ".dbf"
    for p in (shp_path, shx_path, dbf_path):
        if not os.path.exists(p):
            raise SystemExit(f"필요한 파일이 없다: {p}")

    print(f"읽는 중: {base}.(shp|shx|dbf)")
    _fields, records = read_dbf(dbf_path)
    offsets = read_shx_offsets(shx_path)
    if len(records) != len(offsets):
        raise SystemExit(".dbf와 .shx의 레코드 수가 다르다 — 파일이 손상되었을 수 있다.")

    target_indices = [
        i for i, r in enumerate(records)
        if r and r.get("ADM_CD", "").startswith(ADM_CD_PREFIX)
    ]
    print(f"안양시 후보 레코드 {len(target_indices)}개 발견 (ADM_CD 접두사 {ADM_CD_PREFIX})")

    features = []
    found_dongs = set()
    with open(shp_path, "rb") as f:
        for idx in target_indices:
            rec = records[idx]
            raw_name = rec["ADM_NM"]
            dong = RENAME.get(raw_name, raw_name)
            if dong not in DONG_TO_GU:
                print(f"  [건너뜀] population_by_dong.csv에 없는 동: {raw_name} (adm_cd={rec['ADM_CD']})")
                continue
            found_dongs.add(dong)
            byte_off, _ = offsets[idx]
            rings = read_polygon_record(f, byte_off)
            geometry = rings_to_geojson_geometry(rings)
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "dong": dong,
                        "gu": DONG_TO_GU[dong],
                        "adm_nm": f"경기도 안양시{DONG_TO_GU[dong]} {dong}",
                        "adm_cd": rec["ADM_CD"],
                    },
                    "geometry": geometry,
                }
            )

    missing = set(DONG_TO_GU) - found_dongs
    if missing:
        raise SystemExit(f"[오류] 못 찾은 동 ({len(missing)}개): {sorted(missing)} — 매핑/이름변경 확인 필요.")
    print("  31개 행정동 전부 매칭 완료.")

    # 좌표를 소수점 6자리(≈0.11m)로 줄인다. choropleth·point-in-polygon에는
    # 차고 넘치는 정밀도이고, 원본 TM 역변환이 뱉는 14자리를 그대로 두면
    # 파일이 불필요하게 커진다(540KB → 300KB). (#59)
    def _round6(node):
        if isinstance(node, float):
            return round(node, 6)
        if isinstance(node, list):
            return [_round6(x) for x in node]
        return node

    for feat in features:
        feat["geometry"]["coordinates"] = _round6(feat["geometry"]["coordinates"])

    out = {"type": "FeatureCollection", "features": features}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"저장 완료: {OUT_PATH} ({len(features)}개 feature, {OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

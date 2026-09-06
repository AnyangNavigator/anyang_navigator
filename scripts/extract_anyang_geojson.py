"""
안양시 31개 행정동 경계 GeoJSON을 raqoon886/Local_HangJeongDong 저장소의
경기도 파일에서 추출해서 data/anyang_dong_boundaries.geojson 으로 저장한다.

이슈 #3: 지도 choropleth 고도화 — 행정동 경계 GeoJSON 반영
출처: https://github.com/raqoon886/Local_HangJeongDong (경기도.geojson)
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/vuski/admdongkor/master/"
    "ver20260401/HangJeongDong_ver20260401.geojson"
)

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

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "anyang_dong_boundaries.geojson"


def main() -> None:
    print(f"다운로드 중: {SOURCE_URL}")
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as resp:
        gj = json.load(resp)

    features = []
    found_dongs = set()
    for feat in gj["features"]:
        props = feat.get("properties", {})
        adm_nm = props.get("adm_nm", "")
        sggnm = props.get("sggnm", "")
        if "안양시" not in sggnm and "안양시" not in adm_nm:
            continue
        # adm_nm 예: "경기도 안양시만안구 안양1동" -> 마지막 토큰이 행정동명
        dong = adm_nm.split()[-1]
        if dong not in DONG_TO_GU:
            print(f"  [건너뜀] population_by_dong.csv에 없는 동: {adm_nm}")
            continue
        found_dongs.add(dong)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "dong": dong,
                    "gu": DONG_TO_GU[dong],
                    "adm_nm": adm_nm,
                    "adm_cd": props.get("adm_cd"),
                },
                "geometry": feat["geometry"],
            }
        )

    missing = set(DONG_TO_GU) - found_dongs
    if missing:
        print(f"  [경고] 못 찾은 동 ({len(missing)}개): {sorted(missing)}")
    else:
        print(f"  31개 행정동 전부 매칭 완료.")

    out = {"type": "FeatureCollection", "features": features}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"저장 완료: {OUT_PATH} ({len(features)}개 feature, {OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

"""규칙 기반 챗봇 (RAG 대신 구조화 쿼리).

문항 수가 적어 벡터DB 없이도 키워드 매칭 + 구조화 데이터 조회로 충분하다는
PROJECT_SPEC.md 5절의 판단에 따라 구현. 항상 "구 단위" 출처를 명시한다.
"""
from __future__ import annotations

from . import data

FACILITY_KEYWORDS = {
    "주차": "공영주차시설",
    "어린이집": "국공립어린이집",
    "보육": "국공립어린이집",
    "공원": "공원녹지산책로",
    "산책": "공원녹지산책로",
    "녹지": "공원녹지산책로",
    "보건": "보건의료시설",
    "의료": "보건의료시설",
    "병원": "보건의료시설",
    "복지": "사회복지시설",
    "문화": "문화예술회관",
    "예술": "문화예술회관",
    "도서관": "도서관",
    "체육": "체육시설",
    "운동": "체육시설",
}

OTHER_GU = {"만안구": "동안구", "동안구": "만안구"}


def _find_dong(question: str) -> str | None:
    for d in data.list_dong():
        if d.dong in question:
            return d.dong
    return None


def _find_facility(question: str) -> str | None:
    for kw, facility in FACILITY_KEYWORDS.items():
        if kw in question:
            return facility
    return None


def answer(question: str, current_dong: str | None = None) -> str:
    mentioned_dong = _find_dong(question)
    facility = _find_facility(question)

    dong_name = mentioned_dong or current_dong
    d = data.get_dong(dong_name) if dong_name else None

    if facility:
        needed = data.load_needed_facilities()
        manan = float(needed.loc["만안구", facility])
        dongan = float(needed.loc["동안구", facility])
        gap = round(manan - dongan, 1)
        base = (
            f"[구 단위, 2025 사회조사 기준] '{facility}' 향후 필요 응답률: "
            f"만안구 {manan}% / 동안구 {dongan}% (격차 {gap:+.1f}%p, +는 만안구가 더 높음)."
        )
        if d:
            base += f"\n{dong_name}은 {d.gu} 소속이므로 위 {d.gu} 수치가 참고 기준입니다."
        return base

    if "비교" in question and d:
        other_gu = OTHER_GU[d.gu]
        this_stats = data.get_gu_survey_snapshot(d.gu)
        other_stats = data.get_gu_survey_snapshot(other_gu)
        parking_this = this_stats["housing_satisfaction"]["parking_dissat_total"]
        parking_other = other_stats["housing_satisfaction"]["parking_dissat_total"]
        return (
            f"[구 단위 비교] {dong_name}이 속한 {d.gu} vs {other_gu}\n"
            f"- 주차장 불만족: {d.gu} {parking_this}% vs {other_gu} {parking_other}%\n"
            f"(주의: 동 단위 만족도 데이터는 없어 두 '구'의 평균으로만 비교합니다.)"
        )

    if d:
        return (
            f"{dong_name}은 {d.gu} 소속, 인구 {d.total_population:,}명입니다. "
            "주차/보건/복지/문화/체육 등 특정 시설에 대해 물어보시면 해당 구의 2025 사회조사 "
            "수치로 답해드릴 수 있습니다."
        )

    return (
        "질문을 이해하지 못했습니다. 예: '주차시설은 어때?', '옆 동이랑 비교해줘' "
        "처럼 시설 유형이나 비교 요청을 포함해 물어봐주세요."
    )

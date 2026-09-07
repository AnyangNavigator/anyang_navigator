"""챗봇: 구조화 쿼리로 관련 데이터를 찾아 컨텍스트로 LLM에 전달(RAG-lite).

벡터DB 없이, 키워드 매칭으로 질문에 관련된 구조화 데이터(동/시설/구 수치)를
추린 뒤 LLM에 넘겨 답을 생성한다(PROJECT_SPEC 5절). `OPENAI_API_KEY`가 없거나
LLM 호출이 실패하면 결정론적 규칙 기반 답변으로 폴백한다. 항상 "구 단위" 출처를
명시한다.
"""
from __future__ import annotations

import json

from . import data
from .report import _call_openai

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

_CHAT_SYSTEM = (
    "당신은 안양시 균형발전 데이터 안내 챗봇입니다. 아래 [컨텍스트]의 구조화 데이터만 "
    "근거로 2~4문장으로 답하세요. 규칙: "
    "(1) 사회조사 수치는 만안구/동안구 '구 단위'이며 행정동 단위 만족도는 존재하지 않음 — 지어내지 말 것. "
    "(2) 컨텍스트에 없는 값은 '데이터가 없다'고 답할 것. "
    "(3) 숫자는 컨텍스트 값 그대로 인용. "
    "(4) 마크다운 제목·표 없이 짧은 문단으로."
)


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


def _build_context(question: str, dong_name: str | None, facility: str | None) -> dict:
    """질문에 관련된 구조화 데이터만 추린다 (RAG의 retrieval 단계)."""
    ctx: dict = {"질문": question}
    d = data.get_dong(dong_name) if dong_name else None
    if d:
        ctx["대상 행정동"] = {
            "이름": d.dong,
            "소속 구": d.gu,
            "총인구": d.total_population,
            "세대수": d.households,
        }
        ctx["참고"] = "행정동 단위 만족도·필요도 데이터는 존재하지 않음. 아래는 소속 구 평균."
        ctx["소속 구 사회조사(2025)"] = data.get_gu_survey_snapshot(d.gu)
        other_gu = OTHER_GU[d.gu]
        ctx["반대편 구 사회조사(2025)"] = data.get_gu_survey_snapshot(other_gu)
    if facility:
        needed = data.load_needed_facilities()
        manan = float(needed.loc["만안구", facility])
        dongan = float(needed.loc["동안구", facility])
        ctx["문의 시설 필요도(구 단위, %)"] = {
            "시설": facility,
            "만안구": manan,
            "동안구": dongan,
            "격차(만안구-동안구, %p)": round(manan - dongan, 1),
        }
    if not d and not facility:
        ctx["안내"] = "동 이름이나 시설 유형(주차/보건/복지/문화/체육/도서관/공원/어린이집)을 포함해 물어보세요."
    return ctx


def _rule_based_answer(question: str, dong_name: str | None, facility: str | None) -> str:
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


def answer(question: str, current_dong: str | None = None) -> str:
    facility = _find_facility(question)
    dong_name = _find_dong(question) or current_dong

    context = _build_context(question, dong_name, facility)
    prompt = f"[컨텍스트]\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n위 데이터로 질문에 답하세요."
    llm = _call_openai(prompt, system=_CHAT_SYSTEM)
    if llm:
        return llm
    return _rule_based_answer(question, dong_name, facility)

"""LLM 기반(또는 미설정 시 규칙 기반 폴백) 자연어 진단 리포트 생성.

OPENAI_API_KEY 환경변수가 설정돼 있으면 OpenAI Chat Completions API를 호출하고,
없으면 구조화된 데이터로 결정론적 한국어 리포트를 만드는 규칙 기반 폴백을 쓴다.
프로토타입이 "API 키 없이도" 항상 작동해야 하므로 폴백을 기본 경로로 둔다.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error

from . import data
from .simulator import SimulationResult

SYSTEM_PROMPT = (
    "당신은 안양시 균형발전 데이터 분석 보조원입니다. 주어진 구조화 데이터만 근거로 "
    "간결한 한국어 진단 리포트를 작성하세요. 반드시 지켜야 할 규칙: "
    "(1) '구 단위 통계'(만안구/동안구 사회조사 결과)와 '동 단위 통계'(행정동 인구/시설밀도)를 "
    "명확히 구분해서 서술할 것 — 동 단위 만족도 데이터는 존재하지 않으므로 이를 지어내지 말 것. "
    "(2) 숫자를 과장하거나 임의로 추정하지 말고 주어진 값만 인용할 것. "
    "(3) 시뮬레이션 결과가 있다면 이는 실측이 아닌 추정 가정임을 명시할 것."
)


def _call_openai(prompt: str) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    body = json.dumps(
        {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            # 콘텐츠 필터·tool_calls 등으로 정상 200 응답에서도 content가
            # null로 올 수 있다 — 그 경우도 폴백으로 떨어져야 한다.
            return content.strip() if content else None
    except Exception:
        # 이 함수의 계약은 "성공하면 문자열, 그 외엔 항상 None" — 네트워크
        # 오류든 응답 형식이 예상과 다르든, 절대 새어나가지 않고 규칙 기반
        # 폴백으로 떨어져야 하므로 의도적으로 넓게 잡는다.
        return None


def _dong_prompt(dong_name: str, gu_stats: dict, density: dict) -> str:
    return (
        f"행정동: {dong_name} (소속 구: {density['gu']})\n\n"
        f"[구 단위 통계 — {density['gu']} 2025 사회조사]\n{json.dumps(gu_stats, ensure_ascii=False)}\n\n"
        f"[동 단위 통계 — {dong_name} 인구/세대]\n{json.dumps(density, ensure_ascii=False)}\n\n"
        "위 데이터를 바탕으로 3~5문장 진단 리포트를 작성하세요."
    )


def rule_based_dong_report(dong_name: str, gu_stats: dict, density: dict) -> str:
    gu = density["gu"]
    fac = gu_stats["needed_facilities"]
    reasons = gu_stats["dissatisfaction_reasons"]
    parking = gu_stats["housing_satisfaction"].get("parking_dissat_total")

    top_needed = sorted(
        ((k, v) for k, v in fac.items() if k != "기타"), key=lambda kv: kv[1], reverse=True
    )[:2]
    top_reason = max(
        ((k, v) for k, v in reasons.items() if k not in ("불만족_total",)), key=lambda kv: kv[1]
    )

    lines = [
        f"**{dong_name}** ({gu} 소속)의 이중 레이어 진단입니다.",
        "",
        f"- [동 단위] 총인구 {density['total_population']:,}명, 세대수 {density['households']:,}세대"
        f" (평균 가구원수 {density['avg_household_size']}명).",
        f"- [구 단위, {gu} 2025 사회조사] 주차장 체감 불만족률 {parking}%.",
        f"- [구 단위] 향후 필요 시설 응답 1순위: {top_needed[0][0]} {top_needed[0][1]}%"
        + (f", 2순위: {top_needed[1][0]} {top_needed[1][1]}%." if len(top_needed) > 1 else "."),
        f"- [구 단위] 지역 불만족 이유 중 가장 높은 항목: '{top_reason[0]}' {top_reason[1]}%.",
        "",
        "※ 위 구 단위 지표는 만안구/동안구 전체 평균이며, 이 동 자체의 만족도를 나타내는 것이 아닙니다.",
    ]
    return "\n".join(lines)


def generate_dong_report(dong_name: str) -> str:
    d = data.get_dong(dong_name)
    if d is None:
        raise ValueError(f"알 수 없는 행정동: {dong_name}")
    gu_stats = data.get_gu_survey_snapshot(d.gu)
    density = data.get_facility_density(dong_name)

    llm_result = _call_openai(_dong_prompt(dong_name, gu_stats, density))
    if llm_result:
        return llm_result
    return rule_based_dong_report(dong_name, gu_stats, density)


def _scenario_prompt(scenario: dict, result: SimulationResult) -> str:
    return (
        f"정책 시나리오: {scenario['name']}\n{scenario['description']}\n\n"
        f"[시뮬레이션 결과]\n{json.dumps(result.__dict__, ensure_ascii=False)}\n\n"
        "이 시뮬레이션 결과를 바탕으로 3~4문장 정책 브리핑을 작성하세요. "
        "이 수치가 실측이 아닌 가정 기반 추정임을 반드시 언급하세요."
    )


def rule_based_scenario_report(scenario: dict, result: SimulationResult) -> str:
    return "\n".join(
        [
            f"**{scenario['name']}**",
            scenario["description"],
            "",
            f"- 현재 격차({result.facility}, 만안구-동안구): {result.current_gap}%p"
            f" (만안구 {result.manan_current}% vs 동안구 {result.dongan_current}%)",
            f"- {result.region}에 {result.facility} {result.num_facilities}개소 신규 공급 시 "
            f"예상 감소폭: -{result.estimated_reduction}%p",
            f"- 시뮬레이션 후 예상 격차: {result.projected_gap}%p",
            "",
            f"※ {result.assumption_note}",
        ]
    )


def generate_scenario_report(scenario: dict, result: SimulationResult) -> str:
    llm_result = _call_openai(_scenario_prompt(scenario, result))
    if llm_result:
        return llm_result
    return rule_based_scenario_report(scenario, result)

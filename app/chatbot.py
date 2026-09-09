"""챗봇: 구조화 쿼리로 관련 데이터를 찾아 컨텍스트로 LLM에 전달(RAG-lite).

벡터DB 없이, 키워드 매칭으로 질문에 관련된 구조화 데이터(동/시설/구 수치)를
추린 뒤 LLM에 넘겨 답을 생성한다(PROJECT_SPEC 5절). `OPENAI_API_KEY`가 없거나
LLM 호출이 실패하면 결정론적 규칙 기반 답변으로 폴백한다.

retrieval은 사회조사 수요뿐 아니라 대시보드가 쓰는 다른 데이터도 태운다(#65):
- 시설 현황 개소수(`facilities`) — 안양시 전체/구/동
- 필요도 시계열(`data.facility_trend`) — 안양시 전체
- 행정동 군집(`cluster.cluster_dong`)
- 수요-공급 격차(`gap.demand_supply_gaps`)
- "N개 지으면" 질문이면 시뮬레이션(`simulator.simulate`)
사회조사 수치는 항상 "구 단위" 출처를 명시한다.
"""
from __future__ import annotations

import json
import re

from . import cluster, data, facilities, gap, simulator
from .report import _call_openai

# 키워드 → 사회조사 시설 문항명
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

# 사회조사 문항은 없지만 시설 현황(개소)은 있는 것
_EXTRA_FACILITY_KEYWORDS = {"약국": "약국"}

_SURVEY_FACILITIES = set(FACILITY_KEYWORDS.values())
# 시설명 → facilities.REGISTRY kind (현황 데이터가 있는 것만)
_FAC_TO_KIND: dict[str, str] = {**gap.SURVEY_TO_SUPPLY, "약국": "pharmacy"}

OTHER_GU = {"만안구": "동안구", "동안구": "만안구"}

_NUM = re.compile(r"(\d+)\s*개")
_BUILD_VERB = re.compile(r"지으|짓|세우|추가|신설|확충|늘리|공급")

_CHAT_SYSTEM = (
    "당신은 안양시 균형발전 데이터 안내 챗봇입니다. 아래 [컨텍스트]의 구조화 데이터만 "
    "근거로 필요하면 5문장까지 짧게 답하세요. 규칙: "
    "(1) 사회조사 수치(만족도·필요도)는 만안구/동안구 '구 단위'이며 행정동 단위 만족도는 "
    "존재하지 않음 — 지어내지 말 것. 시설 현황(개소수)은 행정동 단위로 존재함. "
    "(2) 컨텍스트에 없는 값은 '데이터가 없다'고 답할 것. "
    "(3) 숫자는 컨텍스트 값 그대로 인용. "
    "(4) 시뮬레이션·군집·계수 수치는 '가정/추정'이라고 밝힐 것. "
    "(5) 마크다운 제목·표 없이 짧은 문단으로."
)


def _find_facilities(question: str) -> list[str]:
    """질문에 걸리는 시설을 전부(등장 순서대로 중복 없이) 반환."""
    found: list[str] = []
    for kw, facility in {**FACILITY_KEYWORDS, **_EXTRA_FACILITY_KEYWORDS}.items():
        if kw in question and facility not in found:
            found.append(facility)
    return found


def _find_dongs(question: str) -> list[str]:
    return [d.dong for d in data.list_dong() if d.dong in question]


def _find_gu(question: str) -> str | None:
    for gu in data.GU_LIST:
        if gu in question:
            return gu
    return None


def _facility_gap(facility: str) -> tuple[float, float, float]:
    """시설 유형의 구별 필요도와 격차. (만안구, 동안구, 만안구-동안구 %p)

    LLM 컨텍스트와 규칙 기반 답변이 같은 수치를 써야 하므로 계산은 여기 한 곳에만 둔다 (#45).
    """
    needed = data.load_needed_facilities()
    manan = float(needed.loc["만안구", facility])
    dongan = float(needed.loc["동안구", facility])
    return manan, dongan, round(manan - dongan, 1)


def _places_by_dong(kind: str) -> dict[str, int]:
    """kind별 {행정동: 개소수}. weight_col과 무관하게 '시설 개수'를 센다."""
    out: dict[str, int] = {}
    for f in facilities.load_facilities(kind):
        if f["dong"]:
            out[f["dong"]] = out.get(f["dong"], 0) + 1
    return out


def _places_by_gu(kind: str) -> dict[str, int]:
    gu_of = {d.dong: d.gu for d in data.list_dong()}
    out = {"만안구": 0, "동안구": 0}
    for dong, n in _places_by_dong(kind).items():
        gu = gu_of.get(dong)
        if gu in out:
            out[gu] += n
    return out


def _supply_block(facility: str, dong_name: str | None) -> dict:
    kind = _FAC_TO_KIND.get(facility)
    if kind is None:
        return {"상태": "시설 현황(개소) 데이터 없음 — 사회복지·문화예술·체육시설은 미집계"}
    by_gu = _places_by_gu(kind)
    total = by_gu["만안구"] + by_gu["동안구"]
    block: dict = {
        "안양시 전체": f"{total}개소",
        "만안구": f"{by_gu['만안구']}개소",
        "동안구": f"{by_gu['동안구']}개소",
        "집계 기준": "공공·등록 시설만 (아파트 부설주차장·민간 의원 등 제외)",
    }
    if kind == "hospital":
        block["주의"] = "병원급 이상만 포함, 개인 의원 제외"
    if kind == "park":
        block["주의"] = "개소수 기준. 공원 면적(㎡)은 별도 지표"
    if dong_name:
        block[f"{dong_name} (행정동 단위)"] = f"{_places_by_dong(kind).get(dong_name, 0)}개소"
    return block


def _trend_block(facility: str) -> dict | None:
    if facility not in _SURVEY_FACILITIES:
        return None
    t = data.facility_trend(facility)
    if not t:
        return None
    return {
        "향후 필요 응답률 추세(%)": t,
        "주의": "안양시 전체 기준. 만안/동안으로 나눈 과거 시계열은 없음",
    }


def _gap_block(facility: str) -> dict | None:
    for r in gap.demand_supply_gaps():
        if r["facility"] == facility:
            return {
                "수요격차(만안-동안, %p)": r["demand_gap"],
                "공급격차(동안-만안, 인구 정규화)": r["supply_gap"],
                "수요·공급 신호 일치": r["agrees"],
                "두 신호 모두 불리한 구": r["disadvantaged"],
            }
    return None


def _cluster_block(dong_name: str) -> dict | None:
    c = cluster.cluster_dong()
    cid = c["dong_to_cluster"].get(dong_name)
    if cid is None:
        return None
    info = next((x for x in c["clusters"] if x["id"] == cid), None)
    if info is None:
        return None
    return {
        "군집 번호": cid,
        "군집 특징": info["traits"],
        "같은 군집 동 수": info["size"],
        "군집 구성(구별)": info["gu_mix"],
        "주의": "인구구조+공급 프로필로 묶은 유형 분류이며 우열이 아님. KMeans, random_state 고정",
    }


def _sim_block(question: str, facility: str, region: str | None) -> dict | None:
    """'N개 지으면' 류 질문이면 시뮬레이션 결과를 넣는다."""
    if facility not in simulator.FACILITY_IMPROVEMENT_COEF:
        return None
    m = _NUM.search(question)
    if not m or not _BUILD_VERB.search(question):
        return None
    region = region or "만안구"
    try:
        r = simulator.simulate(region=region, facility=facility, num_facilities=int(m.group(1)))
    except ValueError as e:
        return {"시뮬레이션 불가": str(e)}
    return {
        "가정": f"{region}에 {facility} {int(m.group(1))}개소 신규 공급",
        "현재 격차(%p)": r.current_gap,
        "시뮬레이션 후 격차(%p)": r.projected_gap,
        "경고": r.adverse_warning or "없음",
        "주의": "하드코딩 가정 계수 기반 추정. 실측 아님",
    }


def _ranked_needs(gu: str) -> dict:
    nf = data.get_gu_survey_snapshot(gu)["needed_facilities"]
    top = sorted(nf.items(), key=lambda kv: -kv[1])[:4]
    return {"구": gu, "향후 필요 응답률 상위(%)": {k: v for k, v in top}}


def _primary_gu(dongs: list[str], gu: str | None) -> str | None:
    """질문의 대표 구. 명시된 gu 우선, 없으면 첫 동의 소속 구.

    `dongs`에 유효하지 않은 동명(클라이언트가 임의로 채운 `dong` 등)이 있어도
    `None`을 흘려보낸다 — `.gu` 접근에서 터지지 않게 (#66 리뷰).
    """
    if gu:
        return gu
    for dn in dongs:
        d = data.get_dong(dn)
        if d:
            return d.gu
    return None


def _build_context(
    question: str, dongs: list[str], gu: str | None, facs: list[str]
) -> dict:
    """질문에 관련된 구조화 데이터만 추린다 (RAG의 retrieval 단계)."""
    ctx: dict = {"질문": question}
    dongs = [dn for dn in dongs[:2] if data.get_dong(dn)]  # 유효한 동만 (비교는 두 동까지)
    primary_gu = _primary_gu(dongs, gu)

    if dongs:
        ctx["대상 행정동"] = [
            {
                "이름": d.dong,
                "소속 구": d.gu,
                "총인구": d.total_population,
                "세대수": d.households,
            }
            for d in (data.get_dong(dn) for dn in dongs)
            if d
        ]
        ctx["참고"] = "행정동 단위 만족도·필요도는 없음. 아래 사회조사는 소속 구 평균."

    if primary_gu:
        ctx[f"사회조사 2025 · {primary_gu}"] = data.get_gu_survey_snapshot(primary_gu)
        ctx[f"사회조사 2025 · {OTHER_GU[primary_gu]}"] = data.get_gu_survey_snapshot(
            OTHER_GU[primary_gu]
        )

    if len(dongs) == 1:
        cb = _cluster_block(dongs[0])
        if cb:
            ctx["행정동 군집분석"] = cb

    if facs:
        entries: list[dict] = []
        for fac in facs:
            entry: dict = {"시설": fac}
            if fac in _SURVEY_FACILITIES:
                manan, dongan, g = _facility_gap(fac)
                entry["향후 필요 응답률(구 단위, %)"] = {
                    "만안구": manan,
                    "동안구": dongan,
                    "격차(만안구-동안구, %p)": g,
                }
            entry["시설 현황(개소)"] = _supply_block(fac, dongs[0] if dongs else None)
            for key, block in (
                ("추세", _trend_block(fac)),
                ("수요-공급 격차", _gap_block(fac)),
                ("시뮬레이션", _sim_block(question, fac, primary_gu)),
            ):
                if block:
                    entry[key] = block
            entries.append(entry)
        ctx["문의 시설"] = entries

    if (dongs or primary_gu) and not facs:
        ctx["향후 필요 시설 순위"] = _ranked_needs(primary_gu)

    if not dongs and not primary_gu and not facs:
        ctx["안내"] = (
            "동/구 이름이나 시설 유형(주차·보건·복지·문화·체육·도서관·공원·"
            "어린이집·약국)을 포함해 물어보세요."
        )
    return ctx


def _rule_based_answer(
    question: str, dongs: list[str], gu: str | None, facs: list[str]
) -> str:
    dongs = [dn for dn in dongs if data.get_dong(dn)]
    primary_gu = _primary_gu(dongs, gu)

    if len(dongs) == 1 and not facs and re.search(r"유형|군집|비슷|성격", question):
        cb = _cluster_block(dongs[0])
        if cb:
            return (
                f"{dongs[0]}은 군집분석에서 {cb['군집 번호']}번 군집({', '.join(cb['군집 특징'])})에 "
                f"속합니다. 같은 군집이 {cb['같은 군집 동 수']}개 동이며, 이 분류는 인구구조와 "
                "공급 프로필로 묶은 유형이지 우열이 아닙니다."
            )

    if facs:
        parts: list[str] = []
        for fac in facs:
            if fac in _SURVEY_FACILITIES:
                manan, dongan, g = _facility_gap(fac)
                s = (
                    f"'{fac}' 향후 필요 응답률은 만안구 {manan}%, 동안구 {dongan}% "
                    f"(격차 {g:+.1f}%p, 구 단위 2025 사회조사)."
                )
            else:
                s = f"'{fac}'"
            kind = _FAC_TO_KIND.get(fac)
            if kind:
                bg = _places_by_gu(kind)
                s += (
                    f" 시설 현황은 안양시 전체 {bg['만안구'] + bg['동안구']}개소"
                    f"(만안 {bg['만안구']}, 동안 {bg['동안구']})."
                )
                if dongs:
                    s += f" {dongs[0]}에는 {_places_by_dong(kind).get(dongs[0], 0)}개소."
            sim = _sim_block(question, fac, primary_gu)
            if sim and "시뮬레이션 불가" not in sim:
                s += (
                    f" {sim['가정']} 시 격차는 {sim['현재 격차(%p)']}%p → "
                    f"{sim['시뮬레이션 후 격차(%p)']}%p로 추정됩니다(가정 계수 기반)."
                )
                if sim["경고"] != "없음":
                    s += f" ⚠ {sim['경고']}"
            elif sim:
                s += f" (시뮬레이션 불가: {sim['시뮬레이션 불가']})"
            parts.append(s)
        tail = " 행정동 단위 만족도 데이터는 없어 구 평균 기준입니다."
        return " ".join(parts) + tail

    if primary_gu:
        nf = sorted(
            data.get_gu_survey_snapshot(primary_gu)["needed_facilities"].items(),
            key=lambda kv: -kv[1],
        )[:3]
        top = ", ".join(f"{k} {v}%" for k, v in nf)
        loc = dongs[0] if dongs else primary_gu
        return (
            f"{loc} 기준({primary_gu} 2025 사회조사) 향후 필요 응답이 높은 시설은 "
            f"{top} 순입니다. 특정 시설을 지정하면 개소수·추세까지 알려드립니다."
        )

    return (
        "동/구 이름이나 시설 유형(주차·보건·복지·문화·체육·도서관·공원·어린이집·"
        "약국)을 포함해 물어봐 주세요."
    )


def answer(question: str, current_dong: str | None = None) -> str:
    facs = _find_facilities(question)
    dongs = _find_dongs(question)
    # current_dong은 클라이언트가 임의로 채우는 필드라 검증 후에만 채택 (#66 리뷰).
    if not dongs and current_dong and data.get_dong(current_dong):
        dongs = [current_dong]
    gu = _find_gu(question)

    context = _build_context(question, dongs, gu, facs)
    prompt = (
        f"[컨텍스트]\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "위 데이터로 질문에 답하세요."
    )
    llm = _call_openai(prompt, system=_CHAT_SYSTEM)
    if llm:
        return llm
    return _rule_based_answer(question, dongs, gu, facs)

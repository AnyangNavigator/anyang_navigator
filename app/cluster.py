"""행정동 군집분석 — 인구 구조 + 공공시설 공급 프로필로 31개 동을 유형화한다.

만안구/동안구 이분법을 넘어 "실제 데이터가 만드는 동 그룹"을 보여준다. 비지도
학습(KMeans)이라 정답 라벨 없이 특징 벡터만으로 유형을 찾는다.

특징 변수 (모두 인구로 정규화된 비율/밀도라 규모 편향이 없다):
  - 고령인구비(65세 이상), 유소년비(0~14세), 생산연령비(15~64세)
  - 평균 가구원수
  - 공공시설 공급 6종 (`facilities.supply_by_dong()` — docs/METRICS.md 규격)

k는 실루엣 점수로 3~6 중 자동 선택하고, `random_state`를 고정해 재현 가능하게
둔다. 군집은 **유형 분류일 뿐 우열이 아니다** — UI/문서에 반드시 명시할 것.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from . import data, facilities

RANDOM_STATE = 42
K_RANGE = range(3, 7)

# 5세 구간 라벨 → 연령 그룹. '계'(합계)는 분모로만 쓴다.
_SENIOR = {"65~69세", "70~74세", "75~79세", "80~84세", "85~89세", "90~94세", "95~99세", "100세 이상"}
_YOUTH = {"0~4세", "5~9세", "10~14세"}


def _age_ratios() -> dict[str, dict[str, float]]:
    """동별 고령비·유소년비·생산연령비(0~1)."""
    df = data.read_csv("population_by_age.csv")
    out: dict[str, dict[str, float]] = {}
    for dong, grp in df.groupby("dong"):
        total = float(grp.loc[grp["age_band"] == "계", "total"].sum())
        if total <= 0:
            continue
        senior = float(grp.loc[grp["age_band"].isin(_SENIOR), "total"].sum())
        youth = float(grp.loc[grp["age_band"].isin(_YOUTH), "total"].sum())
        out[dong] = {
            "senior_ratio": round(senior / total, 4),
            "youth_ratio": round(youth / total, 4),
            "working_ratio": round((total - senior - youth) / total, 4),
        }
    return out


def feature_frame() -> pd.DataFrame:
    """군집 입력 특징 행렬 (index=행정동)."""
    ages = _age_ratios()
    supply = facilities.supply_by_dong()
    rows = []
    for d in data.list_dong():
        a = ages.get(d.dong)
        s = supply.get(d.dong)
        if a is None or s is None:
            continue
        rows.append(
            {
                "dong": d.dong,
                "gu": d.gu,
                **a,
                "household_size": round(d.total_population / d.households, 3) if d.households else 0.0,
                **{f"supply_{k}": v for k, v in s.items()},
            }
        )
    return pd.DataFrame(rows).set_index("dong")


@lru_cache
def cluster_dong() -> dict:
    """31개 동을 군집화해 라벨·군집 요약·선택된 k·실루엣 점수를 반환한다."""
    frame = feature_frame()
    features = frame.drop(columns=["gu"])
    scaled = StandardScaler().fit_transform(features)

    best = None
    for k in K_RANGE:
        model = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10).fit(scaled)
        score = silhouette_score(scaled, model.labels_)
        if best is None or score > best[1]:
            best = (k, score, model)
    k, score, model = best

    frame = frame.assign(cluster=model.labels_)
    clusters = []
    overall = features.mean()
    for cid in sorted(frame["cluster"].unique()):
        members = frame[frame["cluster"] == cid]
        means = members.drop(columns=["gu", "cluster"]).mean()
        # 전체 평균 대비 가장 두드러진 특징 2개(표준화 차이 기준)로 라벨을 만든다.
        spread = features.std().replace(0, 1)
        z = ((means - overall) / spread).sort_values(key=abs, ascending=False)
        traits = [
            f"{_FEATURE_LABEL.get(name, name)} {'높음' if val > 0 else '낮음'}"
            for name, val in z.head(2).items()
        ]
        clusters.append(
            {
                "id": int(cid),
                "size": int(len(members)),
                "dongs": list(members.index),
                "gu_mix": members["gu"].value_counts().to_dict(),
                "traits": traits,
                "means": {c: round(float(v), 3) for c, v in means.items()},
            }
        )
    clusters.sort(key=lambda c: -c["size"])
    return {
        "k": int(k),
        "silhouette": round(float(score), 3),
        "clusters": clusters,
        "dong_to_cluster": {d: int(c) for d, c in frame["cluster"].items()},
    }


_FEATURE_LABEL = {
    "senior_ratio": "고령인구비",
    "youth_ratio": "유소년비",
    "working_ratio": "생산연령비",
    "household_size": "평균 가구원수",
    "supply_parking": "공영주차장",
    "supply_library": "도서관",
    "supply_park": "공원면적",
    "supply_childcare": "어린이집",
    "supply_hospital": "병상",
    "supply_pharmacy": "약국",
}

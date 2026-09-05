"""CSV 데이터 로딩 및 조회 유틸리티.

주의: 사회조사(survey_*) 데이터는 만안구/동안구 '구' 단위까지만 존재한다.
population_by_dong.csv만 행정동(31개) 단위다. 이 둘을 절대 같은 레벨로 섞어서
"동별 만족도"처럼 보여주면 안 된다 (README.md 참고).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

GU_LIST = ["만안구", "동안구"]


@dataclass(frozen=True)
class DongInfo:
    gu: str
    dong: str
    total_population: int
    male: int
    female: int
    households: int


def _read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name, encoding="utf-8-sig")


@lru_cache
def load_population() -> pd.DataFrame:
    return _read_csv("population_by_dong.csv")


@lru_cache
def load_housing_satisfaction() -> pd.DataFrame:
    return _read_csv("survey_11_housing_satisfaction.csv").set_index("region")


@lru_cache
def load_needed_facilities() -> pd.DataFrame:
    return _read_csv("survey_12_needed_facilities.csv").set_index("region")


@lru_cache
def load_dissatisfaction_reasons() -> pd.DataFrame:
    return _read_csv("survey_16-3_dissatisfaction_reasons.csv").set_index("region")


def list_dong() -> list[DongInfo]:
    df = load_population()
    return [
        DongInfo(
            gu=row.gu,
            dong=row.dong,
            total_population=int(row.total_population),
            male=int(row.male),
            female=int(row.female),
            households=int(row.households),
        )
        for row in df.itertuples()
    ]


def get_dong(dong_name: str) -> DongInfo | None:
    for d in list_dong():
        if d.dong == dong_name:
            return d
    return None


def get_gu_survey_snapshot(gu: str) -> dict:
    """해당 구의 2025년 사회조사 지표(구 단위)를 반환한다."""
    housing = load_housing_satisfaction().loc[gu].to_dict()
    facilities = load_needed_facilities().loc[gu].to_dict()
    reasons = load_dissatisfaction_reasons().loc[gu].to_dict()
    return {
        "gu": gu,
        "housing_satisfaction": housing,
        "needed_facilities": facilities,
        "dissatisfaction_reasons": reasons,
    }


def get_facility_density(dong_name: str) -> dict | None:
    """동 자체의 인구 대비 시설밀도(동 단위). 현재는 인구 기초 통계만 존재.

    시설(주차장 개소, 복지시설 개소 등) 원자료는 아직 데이터셋에 없으므로,
    인구/세대 기반 지표만 제공한다. 향후 시설 위치 데이터가 추가되면 이 함수를
    확장한다.
    """
    d = get_dong(dong_name)
    if d is None:
        return None
    return {
        "dong": d.dong,
        "gu": d.gu,
        "total_population": d.total_population,
        "households": d.households,
        "avg_household_size": round(d.total_population / d.households, 2) if d.households else None,
    }


def gu_needed_facility_gap() -> dict[str, float]:
    """시설 유형별 만안구-동안구 필요도 격차(%p, 만안구-동안구)."""
    df = load_needed_facilities()
    manan = df.loc["만안구"]
    dongan = df.loc["동안구"]
    gap = (manan - dongan).round(1)
    return gap.to_dict()


def facility_trend(facility: str) -> dict[str, float]:
    """안양시 전체 2021->2023->2025 시계열 필요도 추세."""
    df = load_needed_facilities()
    return {
        "2021": float(df.loc["안양시 전체(2021)", facility]),
        "2023": float(df.loc["안양시 전체(2023)", facility]),
        "2025": float(df.loc["안양시 전체", facility]),
    }

# 데이터 출처

이 폴더의 모든 파일은 공개된 공공데이터에서 확보한 것입니다. 숫자를 인용할 때는
항상 이 CSV를 기준으로 삼습니다(`reference/`의 docx는 맥락 참고용이며 문항 16-3에
수치 오류가 있음).

## 사회조사 (구 단위)

| 파일 | 데이터 | 제공기관 | 출처 | 기준 |
|---|---|---|---|---|
| `survey_11_housing_satisfaction.csv` | 주택·기반시설·주차장 만족도 (문항 11) | 안양시 | 「2025년 제11회 안양시 사회조사」 결과 공표 — [anyang.go.kr 통계정보 > 사회조사](https://www.anyang.go.kr/main/selectBbsNttView.do?bbsNo=52&key=243&nttNo=427049) | 2025년 조사, 2025-12-23 공표 |
| `survey_12_needed_facilities.csv` | 향후 필요 공공시설 복수응답 (문항 12) + 안양시 전체 2021·2023·2025 시계열 | 안양시 | 위와 동일 | 위와 동일 |
| `survey_16-3_dissatisfaction_reasons.csv` | 지역 거주 불만족 이유 (문항 16-3) | 안양시 | 위와 동일 | 위와 동일 |

> 사회조사는 만안구/동안구 **2개 구 단위**까지만 집계됨. 행정동 단위 만족도 데이터는 존재하지 않음.
> 2021·2023 회차 원본: [2023년 제9회](https://www.anyang.go.kr/main/selectBbsNttView.do?bbsNo=52&key=243&nttNo=361118) 등 — 구 단위 시계열 확보 시도는 이슈 #33.

## 인구 (행정동 31개 단위)

| 파일 | 데이터 | 제공기관 | 출처 | 기준 |
|---|---|---|---|---|
| `population_by_dong.csv` | 행정동별 인구·세대수 | 행정안전부 | 주민등록인구통계 [jumin.mois.go.kr](https://jumin.mois.go.kr/) / [안양시 주민등록인구통계](https://www.anyang.go.kr/main/selectBbsNttList.do?bbsNo=55&key=246) | 2025.12.31 기준 |
| `population_by_age.csv` | 행정동별 5세 단위 연령 인구 (계 + 21개 구간) | 행정안전부 | 위와 동일 | 2025.12.31 기준 |

## 시설 현황 (시설 개별 — 좌표/주소)

| 파일 | 데이터 | 제공기관 | 출처 | 기준 |
|---|---|---|---|---|
| `facilities_parking.csv` | 안양시 공영주차장 (주차면수 포함) | 행정안전부 | data.go.kr 전국주차장정보표준데이터 (안양시분) | 2026-04-17 |
| `facilities_library.csv` | 안양시 도서관 | 문화체육관광부 | data.go.kr 전국도서관표준데이터 (안양시분) | 2026-01-02 |
| `facilities_park.csv` | 안양시 도시공원 | 국토교통부 | data.go.kr 전국도시공원정보표준데이터 (안양시분) | 2025-11-26 |
| `facilities_childcare.csv` | 안양시 어린이집·유치원 | 보건복지부 | 경기데이터드림 「어린이집 현황(제공표준)」 ([data.gg.go.kr](https://data.gg.go.kr/)) | 2025-07-25 |
| `facilities_hospital.csv` | 안양시 병원 (병원급 이상, **의원 제외**) | 경기도 | 경기데이터드림 「경기도 병원 현황」 | — |
| `facilities_pharmacy.csv` | 안양시 약국 | 경기도 | 경기데이터드림 「약국 현황」 | — |

> 병·의원 중 **개인 의원은 누락**됨(HIRA 병원정보서비스 별도 소싱 필요 — 이슈 #33).
> 원본 컬럼명 그대로 보존(영문 표준 필드명). 추출 스크립트: `scripts/extract_anyang_geojson.py`(경계), 시설은 각 포털에서 안양시 필터 후 다운로드.

## 행정동 경계

| 파일 | 데이터 | 출처 | 기준 |
|---|---|---|---|
| `anyang_dong_boundaries.geojson` | 안양시 31개 행정동 경계 폴리곤 | [vuski/admdongkor](https://github.com/vuski/admdongkor) ver20260401 — ⚠️ **공식 공공데이터(vworld/SGIS)로 교체 예정 (이슈 #30)** | 2026-04-01 |

## 지도 타일

- 네이버 지도(NCP Maps) Dynamic Map — Client ID는 도메인 화이트리스트로 보호되는 공개 키.
  이용약관은 NCP Maps 약관 준수(공모전/공공목적 이용).

## 라이선스

- data.go.kr 표준데이터: 대부분 「이용허락범위 제한 없음」(데이터셋별 확인).
- 경기데이터드림: 데이터셋별 이용조건 표기 확인.
- 안양시 사회조사·주민등록인구통계: 공표 통계로 출처 표기 후 활용.

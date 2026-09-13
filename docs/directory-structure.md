# 프로젝트 디렉토리 구조

마지막 갱신: 2026-09-13

- `scripts/`, `eda/`, `notebooks/`는 파일이 많고 이름 규칙이 뚜렷해서 패턴으로 표기
- 그 외(`data/`, `docs/`, `metadata/`, `outputs/`, `src/`)는 하위 디렉토리와 파일명을 전부 표기하였음
- 단, `data/raw/`와 `data/interim/`의 반복적인 대량 파일(주간/일간 원본 CSV, 월별 캐시 parquet 수백 개)은 패턴 + 개수 + 범위로 축약

---

## 최상위

```
sdot-analysis/
├── .env                  # KMA_API_KEY 등 실제 값 (git 추적 안 함)
├── .env.example           # KMA_API_KEY=your_apihub_authkey_here
├── .gitignore
├── data/
├── docs/
├── eda/
├── metadata/
├── notebooks/
├── outputs/
├── scripts/
└── src/
```

---

## scripts/ — 순차 번호가 붙은 ETL/분석 스크립트

```
scripts/script00-generate-inventory.py ~ scripts/script28-dedupe-identical-rows.py
```

- 번호 순서 = 작업 순서. 이름 뒤에 `-v2`, `-v3`, `-v5`... 처럼 버전이 붙은 게 많은데,
  **더 큰 버전이 항상 최신/정식은 아닙니다** — 옆에 있는 스크립트가 그걸 대체했는지
  먼저 커밋 로그나 `docs/data-source-notes.md`로 확인 바랍니다.
- 지금 기준 **현재 운영 중인(정식) 파이프라인**은:
  - `script22-merge-yearly-v8.py` — 연도별 원본 CSV → `data/interim/v8/` (measure_time 결정, 스키마 정규화, 병합 불변식 검증)
  - `script23-merge-all-years-v4.py` — `data/interim/v8/` → `data/processed/master-v2/` (통합 + 위치정보 매핑)
  - `script24-collect-kma-asos.py`, `script25-collect-kma-aws-seoul.py` - KMA 기상 데이터 수집(Phase 1)
  - `script26~28`은 감사/진단용 (센서 품질 진단, measure_time 12시간 접힘 검증, 중복 제거) — 현재 진행 중인 조사 작업, 아직 정식 파이프라인에 편입 안 됨
- `script00~21`은 위 v8/v4 파이프라인이 나오기 전 시행착오 과정(구버전 스키마 매핑, 구버전 병합 로직 등) 

## eda/ — 탐색적 분석 노트북

```
eda/{번호}-eda-{주제}.ipynb        예) eda/03-eda-sdot-overview.ipynb
eda/eda{번호}-{주제}-v2.ipynb      예) eda/eda10-air-quality-v2.ipynb
eda/.tmp/                          duckdb 임시 파일 (무시해도 됨)
```

## notebooks/ — 디버깅/일회성 확인용 노트북

```
notebooks/{번호}-{목적}.ipynb      예) notebooks/02-check-datetime-error.ipynb
notebooks/.tmp/
```

---

## data/ — 원본·중간·완성 데이터 (git track X, GoogleDrive에 공유)

```
data/
├── raw/                          # 원본, 절대 수정하지 않음
│   ├── S-DoT_2020/  ~  S-DoT_2026/     # 연도별 폴더 (파일명 규칙은 연도마다 다름 - 아래 참고)
│   ├── KMA_ASOS_108/asos_108_{YYYYMM}.txt              # 77개 (202004~202608)
│   ├── KMA_AWS_seoul/aws_seoul_{YYYYMM}_raw.txt        # 77개 (202004~202608)
│   └── 서울시 무더위쉼터.csv
├── interim/                      # 연도별/월별 중간 산출물
│   ├── sdot_{2020~2026}.parquet          # 구버전(v8 이전) 연도별 병합 - 참고용, 더 안 씀
│   ├── v8/
│   │   ├── sdot_{2020~2026}_v8.done      # 완료 마커 (파일 수, 행 수 기록)
│   │   └── sdot_{2020~2026}_v8.parquet   # 현재 정식 연도별 interim (script22 산출물)
│   ├── kma_asos_108.parquet
│   ├── kma_aws_seoul.parquet              # 최종본 (77개월 통합)
│   └── kma_aws_seoul/
│       └── {YYYYMM}.done / {YYYYMM}.parquet   # 월별 캐시, 202004~202608 (77개월 x 2파일)
└── processed/
    ├── master-v1/                # 구버전 마스터 (더 안 씀, 참고용)
    │   ├── sdot_master_2020_2026.parquet
    │   ├── sdot_master_2020_2026_cleaned.parquet
    │   └── sdot_master_2020_2026_geocoded.parquet
    ├── master-v2/
    │   └── sdot_master_2020_2026_v2.parquet   # ⭐ 현재 마스터 데이터셋
    ├── processed_merged_df.csv
    ├── processed_sensor_coords.csv
    ├── sensor_missing_rates_matrix.csv
    └── sensor_pairs_500m.csv
```

**`data/raw/S-DoT_{연도}/` 파일명 규칙** (연도마다 원본 제공 방식이 바뀌어서 다름):
| 연도 | 규칙 | 개수 |
|---|---|---|
| 2020 | `S-DoT_NATURE_{YYYY.MM.DD-MM.DD}.csv` (초반엔 월단위, 11월부터 주단위) | 16개 |
| 2021~2022 | `S-DoT_NATURE_{YYYY.MM.DD-MM.DD}.csv` (주단위) | 55개 / 54개 |
| 2023 | 동일(주단위) | 53개 |
| 2024 | `120_서울시 IOT 복합 센서(환경정보)_PUBDATA_{YYYYMM}.csv` (월단위, 파일명 형식이 바뀜) | 12개 |
| 2025 | 1~6월은 `S-DoT_NATURE_2025.{MM}/` 폴더 안에 일단위 파일, 7월 말부터 주단위 csv로 전환 | 폴더 6개(내부에 일별 파일 총 181개) + 주단위 29개 |
| 2026 | 주단위 csv | 34개 |

> `data/raw/S-DoT_2025/S-DoT_NATURE_2025.08.18-08.24.csv`는 스키마 인벤토리상 시작일이 `2023-11-22`로 잘못 나오는데, 이건 그 파일 안의 결측치 이상 행 1건 (`measure_time_year_outlier`) 때문이지 실제로 2023년 데이터가 섞인 게 아님
(`docs/data-source-notes.md` 2026-09-07 항목 참고).

---

## docs/ — 조사 기록·의사결정 문서

```
docs/
├── README.md                              # 프로젝트 소개 
├── data-source-notes.md                   # ⭐ 원본 데이터 이슈 발견/원인/조치 전체 기록
├── preregistration.md                     # ⭐ Phase 게이트, 임계값 사전등록 (결과 보기 전 확정한 기준들)
├── project-history-phase0.md              # Phase 0 감사·병합 체크리스트 대조 기록
├── lit-review.md                          # 관련 연구 리뷰
├── kma-asos-collection-audit.csv          # ASOS 수집 월별 기대/실제 행수 감사 로그
├── kma-aws-collection-audit.csv           # AWS 수집 월별 기대/실제 행수 감사 로그
└── sdot-sensor-quality-report.csv         # 센서별 품질 등급표 (script26 산출물)
```

## metadata/ — 스키마/위치 매핑용 참조 자료

```
metadata/
├── sdot-schema-mapping.xlsx                                        # ⭐ 파일 인벤토리 + 컬럼 매핑표
├── 서울시 도시데이터 센서(S-DoT) 환경정보 설치 위치정보.xlsx          # 센서별 위경도/주소
├── 스마트서울 도시데이터 센서(S-DoT) 환경정보 Open API 명세서(20250716).xlsx
├── kma_aws_stations_seoul.csv                                      # 서울 AWS 관측소 29개 지점 목록
└── sensor_category_map.csv
```

## outputs/ — 발표/보고용 산출물

```
outputs/
├── figures/                               # 현재 비어있음
└── tables/                                # 현재 비어있음
```

## src/ — 초기 프로토타입 노트북 (지금 파이프라인 이전)

```
src/
├── merge-6years-sdot.ipynb
├── paper-reproduction01-merge-data.ipynb
└── paper-reproduction02.ipynb
```

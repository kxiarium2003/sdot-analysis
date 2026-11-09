# 요청 파일 (2026-10-12)

압축을 공유 묶음(`RQ1_모듈_공유.zip`)을 푼 폴더에 그대로 풀면 같은 경로의 파일이 최신본으로 바뀐다.

| 파일 | 내용 | 만든 날 |
| --- | --- | --- |
| `phase2/anomaly_by_zone_2y_merged.parquet` | 집계구 × 연도 × 계절 × 시각 ΔT (최신) | 2026-10-10 |
| `phase3/absolute_temp_tract.parquet` | 집계구 × 연도 × 시각 기준 기온·ΔT·절대 기온 (여름) | 2026-10-10 |
| `phase1/variogram_monthly_2y_merged.csv` | 월별 배리오그램 (기준 기온 크리깅 설정) | 2026-10-10 |
| `phase3_absolute_temp.py` | 위 절대 기온 파일을 만드는 스크립트 (H5 docstring의 그 스크립트) | 2026-10-08 |
| `rq1_modules/` | 공유 모듈 최신 코드와 README (기대값 갱신) | 2026-10-10 |

## 수치가 README와 다른 이유

2026-10-10에 이상 센서 2대(ΔT 중앙값이 표본 중앙값에서 ±3°C 밖: `OC3CL200256` +6.16°C, `OC3CL200097` −3.16°C)를 빼고(1,085 → 1,083대) 전체를 다시 계산했다. 그래서 ΔT 파일이 바뀌었고 기대값도 바뀌었다. 결론은 같고 수치는 소수점 수준에서 바뀐다.

| H1, 15–64세 1인당 노출 (집계구) | 거주 기반 | 활동 기반 | Gap |
| --- | --- | --- | --- |
| 이전 묶음 (센서 1,085대) | 13,020 | 12,784 | −1.8% |
| **이번 파일 (센서 1,083대)** | **13,016** | **12,796** | **−1.7%** |

이번 파일로 `python -m rq1_modules.H1_how_much --scale=tract`를 돌리면 아래 줄이 나와야 한다.

```
15–64세 | 13,016 | 12,796 | -1.7% | -0.025°C | -0.9%
```

## 13,107 → 12,860이 나왔다면

이 값은 이전 ΔT 파일(13,020)로도 이번 ΔT 파일(13,016)로도 나오지 않는다. 그래서 ΔT 파일이 아니라 다른 입력이 다를 가능성이 크다. 아래를 확인하면 된다.

- `merged_data/D6_census/census2024_age3_tract16.parquet`, `merged_data/D5_livingpop/livingpop_agg_2024_2025_native.parquet`, `merged_data/D5_livingpop/age_scale.csv`가 공유 묶음의 것인지
- `common.py`의 `P["field"]`가 `phase2/anomaly_by_zone_2y_merged.parquet`(접미사 `_merged`)를 가리키는지. `_merged_poly`, `_strict_merged` 등 다른 설정의 파일을 쓰면 값이 달라진다
- 연령 보정을 바꾸지 않았는지(기본은 24시간 평균, 배율은 19,153개 집계구 전체 생활인구로 계산)

## phase3_absolute_temp.py 를 돌리려면

공유 묶음에 이미 있는 `merged_data/D2_aws/`, `merged_data/D9_boundary/bnd_oa_11_2016_4Q/`, `phase2/covariates_tract16_buf250.parquet`, 생활인구·인구총조사 파일과 이번 `phase2/anomaly_by_zone_2y_merged.parquet`, `phase1/variogram_monthly_2y_merged.csv`가 필요하다. 저장소 최상위 폴더에서 `python phase3_absolute_temp.py`로 실행하면 1분 정도 걸리고 `phase3/absolute_temp_tract.parquet`, `phase3/absolute_temp_summary.json`을 만든다.

"""
script38-check-sample-filter-funnel.py - 가이드라인 §3 표본 사전등록 필터 적용 여부 확인 (깔때기)

가이드라인 §3: "표본(사전등록): 정상 등급 + 커버리지 ≥ 0.5 + ΔT 중앙값 [−10, +10]°C".
script31은 '정상 등급'만 적용하고 나머지 두 조건은 코드에 없다. 이 스크립트는 세 조건을 순서대로
적용했을 때 단계별로 몇 개가 남는지 확인한다(재실행이 아니라 기존 산출물 조회).

정의는 새로 만들지 않고 기존 것을 그대로 쓴다:
- 정상 등급 / 커버리지 : docs/sdot-sensor-quality-report.csv (final_grade, coverage_ratio —
  센서 자신의 활동기간 대비 유효 유니크 시각 비율, preregistration §3)
- ΔT : data/interim/sdot_anomaly_field_202409_202608.parquet 의 delta_t (= S-DoT 실측 − KED 예측,
  script31). 센서별 중앙값은 분석기간 전체 시각의 중앙값.
- 위경도 / 집계구 매핑 : script32와 동일(master-v2의 latitude/longitude, D9 2025 Q2 집계구 within 조인)

보충(정의 변형, 필터로 쓰지 않음): 분석기간 기준 커버리지 = ΔT가 산출된 시각 수 ÷ KED 가능 시각 수.
"""
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUALITY = PROJECT_ROOT / 'docs' / 'sdot-sensor-quality-report.csv'
ANOMALY = PROJECT_ROOT / 'data' / 'interim' / 'sdot_anomaly_field_202409_202608.parquet'
MASTER = PROJECT_ROOT / 'data' / 'processed' / 'master-v2' / 'sdot_master_2020_2026_v2.parquet'
ZONES = PROJECT_ROOT / 'data' / 'interim' / 'seoul_census_oa_wgs84.geojson'
MODEL_DS = PROJECT_ROOT / 'data' / 'interim' / 'zone_night_anomaly_model_dataset.parquet'
OUT_CSV = PROJECT_ROOT / 'docs' / 'phase1-sample-filter-sensors.csv'


def main():
    q = pd.read_csv(QUALITY)
    con = duckdb.connect()

    a = pd.read_parquet(ANOMALY, columns=['sensor_id', 'measure_hour', 'delta_t', 'is_night'])
    med = a.groupby('sensor_id')['delta_t'].median().rename('dt_median')
    med_night = a[a['is_night']].groupby('sensor_id')['delta_t'].median().rename('dt_median_night')
    nhours = a.groupby('sensor_id')['measure_hour'].nunique().rename('dt_hours')
    ked_hours = a['measure_hour'].nunique()

    loc = con.execute(f"""
        SELECT sensor_id, ANY_VALUE(latitude) AS lat, ANY_VALUE(longitude) AS lon
        FROM read_parquet('{MASTER.as_posix()}') WHERE latitude IS NOT NULL GROUP BY sensor_id
    """).fetchdf()
    zones = gpd.read_file(ZONES)
    zones['TOT_OA_CD'] = zones['TOT_OA_CD'].astype(str)
    sg = gpd.GeoDataFrame(loc, geometry=gpd.points_from_xy(loc['lon'], loc['lat']), crs='EPSG:4326')
    zmap = gpd.sjoin(sg, zones[['TOT_OA_CD', 'geometry']], how='inner', predicate='within')[['sensor_id', 'TOT_OA_CD']]

    df = q.merge(med, left_on='sensor_id', right_index=True, how='left') \
          .merge(med_night, left_on='sensor_id', right_index=True, how='left') \
          .merge(nhours, left_on='sensor_id', right_index=True, how='left') \
          .merge(loc[['sensor_id']].assign(has_loc=True), on='sensor_id', how='left') \
          .merge(zmap.assign(has_zone=True), on='sensor_id', how='left')
    df['has_loc'] = df['has_loc'].fillna(False)
    df['has_zone'] = df['has_zone'].fillna(False)
    df['has_dt'] = df['dt_median'].notna()
    df['cov_window'] = df['dt_hours'].fillna(0) / ked_hours

    steps = []
    s = df
    steps.append(('(0) 전체 센서(등급표)', len(s), None))
    s1 = s[s.final_grade == '정상']; steps.append(('(1) 정상 등급', len(s1), len(s) - len(s1)))
    s2 = s1[s1.coverage_ratio >= 0.5]; steps.append(('(2) 커버리지 ≥ 0.5 (센서 활동기간 기준)', len(s2), len(s1) - len(s2)))
    s2b = s2[s2.has_dt]; steps.append(('(2b) 분석기간(2024-09~2026-08)에 ΔT 산출 있음', len(s2b), len(s2) - len(s2b)))
    s3 = s2b[(s2b.dt_median >= -10) & (s2b.dt_median <= 10)]; steps.append(('(3) ΔT 중앙값 [−10,+10]°C', len(s3), len(s2b) - len(s3)))
    s4 = s3[s3.has_loc]; steps.append(('(4) 위경도 보유', len(s4), len(s3) - len(s4)))
    s5 = s4[s4.has_zone]; steps.append(('(5) 집계구 매핑 성공', len(s5), len(s4) - len(s5)))
    print("=== 깔때기 ===")
    for name, n, drop in steps:
        print(f"{name:52s} 남음 {n:5d}   탈락 {'' if drop is None else drop}")
    zc = s5['TOT_OA_CD'].nunique()
    print(f"\n(5)의 고유 집계구 수: {zc}")
    final_ds = pd.read_parquet(MODEL_DS)
    print(f"최종 모델 표본(zone_night_anomaly_model_dataset): {len(final_ds)}개 집계구")

    print("\n=== 참고 지표 ===")
    print(f"정상 469 중 위경도 보유: {int(s1.has_loc.sum())}, 집계구 매핑: {int(s1.has_zone.sum())}, ΔT 산출: {int(s1.has_dt.sum())}")
    print(f"ΔT 산출 센서 {int(s1.has_dt.sum())}대의 ΔT 중앙값 범위: {s2b.dt_median.min():.3f} ~ {s2b.dt_median.max():.3f}°C")
    print(f"ΔT 야간 중앙값 범위: {s2b.dt_median_night.min():.3f} ~ {s2b.dt_median_night.max():.3f}°C, [-10,10] 밖 {int(((s2b.dt_median_night < -10) | (s2b.dt_median_night > 10)).sum())}대")
    print(f"(2)에서 분석기간 ΔT 없음으로 빠진 센서 {len(s2) - len(s2b)}대: 등급표상 활동기간 최후 시각 분포")
    gone = s2[~s2.has_dt]
    print(gone['last_valid_ts'].str[:7].value_counts().sort_index().to_string())

    print(f"\n=== 보충(정의 변형): 분석기간 기준 커버리지 = ΔT 산출 시각 ÷ {ked_hours:,} ===")
    print(s2b['cov_window'].describe().round(3).to_string())
    low = s2b[s2b.cov_window < 0.5].sort_values('cov_window')
    print(f"분석기간 커버리지 < 0.5: {len(low)}대")
    print(low[['sensor_id', 'coverage_ratio', 'cov_window', 'dt_median', 'TOT_OA_CD']].round(3).to_string(index=False))
    zones_all = s2b.groupby('TOT_OA_CD').size()
    zones_after = s2b[s2b.cov_window >= 0.5].groupby('TOT_OA_CD').size()
    print(f"\n보충 필터 적용 시: 센서 {len(s2b)} → {int((s2b.cov_window >= 0.5).sum())}대, 집계구(센서 있는) {zones_all.shape[0]} → {zones_after.shape[0]}개")

    df.assign(pass_normal=df.final_grade == '정상').to_csv(OUT_CSV, index=False)
    print(f"\n센서별 상세 저장 → {OUT_CSV}")


if __name__ == '__main__':
    main()

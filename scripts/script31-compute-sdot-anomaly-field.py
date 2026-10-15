"""
script31-compute-sdot-anomaly-field.py - S-DoT 이상장(ΔT = 실측-예측) 계산 (Phase 1, G2 게이트)

docs/sdot-sensor-quality-report.csv에서 "정상" 등급 센서만 골라 v2 마스터
(data/processed/master-v2/sdot_master_2020_2026_v2.parquet)의 2024-09-01~2026-08-30
구간 데이터와 대조하고, 시간마다 AWS 29개 지점 전체로 적합한 KED(script29와 동일
설정: 외부표류=DEM, variogram_model='exponential')로 각 S-DoT 센서 위치의 예측
기온을 구해 ΔT = 실측 temp_avg - KED 예측값을 계산한다.

주의:
- v2 마스터의 (sensor_id, measure_time) 중복 그룹 중 온도값이 서로 다른
  "충돌" 그룹(2024-09~2026-08 구간에서 3,096건, 전체 행의 0.019% 확인됨,
  docs/preregistration.md 참고)은 어느 값이 맞는지 판단할 근거가 없으므로
  이 스크립트에서 완전히 제외한다(둘 중 하나를 임의로 고르지 않음). 값이
  동일한 순수 중복(cause A)은 1개만 남긴다.
- script29의 LOOCV와 달리 여기서는 지점을 제외하지 않고 AWS 29개 지점 전체로
  적합한 뒤, S-DoT 센서 위치(최대 469곳)에 한 번에 예측한다 - 시간당 1회
  적합이므로 LOOCV(시간당 29회 적합)보다 훨씬 빠르다.
"""
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import rasterio
from pykrige.uk import UniversalKriging

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AWS_PARQUET = PROJECT_ROOT / 'data' / 'interim' / 'kma_aws_seoul.parquet'
STATIONS_CSV = PROJECT_ROOT / 'metadata' / 'kma_aws_stations_seoul.csv'
DEM_TIF = PROJECT_ROOT / 'data' / 'raw' / 'D4_DEM' / 'seoul_srtm30m.tif'
MASTER_V2 = PROJECT_ROOT / 'data' / 'processed' / 'master-v2' / 'sdot_master_2020_2026_v2.parquet'
QUALITY_CSV = PROJECT_ROOT / 'docs' / 'sdot-sensor-quality-report.csv'
OUTPUT_FILE = PROJECT_ROOT / 'data' / 'interim' / 'sdot_anomaly_field_202409_202608.parquet'

ANALYSIS_START = '2024-09-01 00:00:00'
ANALYSIS_END = '2026-08-30 23:59:59'
VARIOGRAM_MODEL = 'exponential'
NIGHT_HOURS = set(list(range(22, 24)) + list(range(0, 6)))


def load_dem_grid():
    with rasterio.open(DEM_TIF) as src:
        dem = src.read(1).astype(float)
        transform = src.transform
        xs = np.array([transform * (c + 0.5, 0) for c in range(src.width)])[:, 0]
        ys = np.array([transform * (0, r + 0.5) for r in range(src.height)])[:, 1]
    return dem[::-1, :], xs, ys[::-1]


def load_normal_sdot_data():
    quality = pd.read_csv(QUALITY_CSV)
    normal_sensors = quality.loc[quality['final_grade'] == '정상', 'sensor_id'].tolist()
    print(f"'정상' 등급 센서 수: {len(normal_sensors)}")

    con = duckdb.connect()
    con.register('normal_sensors', pd.DataFrame({'sensor_id': normal_sensors}))
    q = f"""
    WITH base AS (
        SELECT sensor_id, measure_time, temp_avg, latitude, longitude
        FROM read_parquet('{MASTER_V2.as_posix()}')
        WHERE measure_time >= '{ANALYSIS_START}' AND measure_time <= '{ANALYSIS_END}'
          AND sensor_id IN (SELECT sensor_id FROM normal_sensors)
          AND temp_avg IS NOT NULL
    ),
    grp AS (
        SELECT sensor_id, measure_time,
               COUNT(DISTINCT temp_avg) AS n_distinct,
               MIN(temp_avg) AS temp_avg, ANY_VALUE(latitude) AS latitude,
               ANY_VALUE(longitude) AS longitude
        FROM base GROUP BY sensor_id, measure_time
    )
    SELECT sensor_id, measure_time, temp_avg, latitude, longitude
    FROM grp WHERE n_distinct = 1
    """
    df = con.execute(q).fetchdf()
    df['measure_time'] = pd.to_datetime(df['measure_time'])
    print(f"충돌 없는 (센서,시각) 행수: {len(df):,}")
    return df


def main():
    print("🚀 [ S-DoT 이상장(ΔT) 계산 시작 ]")

    stations = pd.read_csv(STATIONS_CSV)
    stations['stn_id'] = stations['stn_id'].astype(str)
    dem_grid, dem_x, dem_y = load_dem_grid()
    with rasterio.open(DEM_TIF) as src:
        elev = [v[0] for v in src.sample([(r.lon, r.lat) for r in stations.itertuples()])]
    stations['elevation'] = elev
    stn_lookup = stations.set_index('stn_id')[['lat', 'lon', 'elevation']]

    aws = pd.read_parquet(AWS_PARQUET)
    aws = aws[(aws['measure_time'] >= ANALYSIS_START) & (aws['measure_time'] <= ANALYSIS_END)]
    aws = aws.dropna(subset=['ta'])

    sdot = load_normal_sdot_data()
    sensor_locations = sdot[['sensor_id', 'latitude', 'longitude']].drop_duplicates('sensor_id')
    print(f"고유 센서 위치 수: {len(sensor_locations)}")

    hours = sorted(aws['measure_time'].unique())
    print(f"대상 시간 수: {len(hours):,}\n")

    all_preds = []
    skipped = 0
    start_time = time.time()

    for i, hour in enumerate(hours):
        hour_df = aws[aws['measure_time'] == hour].merge(
            stn_lookup, left_on='stn_id', right_index=True)
        if len(hour_df) < 10:
            skipped += 1
            continue

        lons = hour_df['lon'].values
        lats = hour_df['lat'].values
        temps = hour_df['ta'].values

        try:
            uk = UniversalKriging(
                lons, lats, temps, drift_terms=['external_Z'],
                external_drift=dem_grid, external_drift_x=dem_x, external_drift_y=dem_y,
                variogram_model=VARIOGRAM_MODEL, verbose=False, enable_plotting=False,
            )
            pred, _ = uk.execute(
                'points', sensor_locations['longitude'].values, sensor_locations['latitude'].values)
        except Exception:
            skipped += 1
            continue

        hour_pred = pd.DataFrame({
            'sensor_id': sensor_locations['sensor_id'].values,
            'measure_time': pd.Timestamp(hour),
            'predicted': np.asarray(pred),
        })
        all_preds.append(hour_pred)

        if (i + 1) % 1000 == 0 or (i + 1) == len(hours):
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            remaining = (len(hours) - i - 1) / rate if rate > 0 else float('nan')
            print(f"[{i+1:,}/{len(hours):,}] {elapsed/60:.1f}분 경과, "
                  f"예상 잔여 {remaining/60:.1f}분 (건너뛴 시간 {skipped}개)")

    print(f"\n건너뛴 시간: {skipped}개")
    pred_df = pd.concat(all_preds, ignore_index=True)
    pred_df.to_parquet(PROJECT_ROOT / 'data' / 'interim' / 'ked_hourly_predictions_202409_202608.parquet', index=False)

    # S-DoT는 매시 정각이 아니라 :07분 등에 관측되므로(예: 00:07, 01:07 ...),
    # KED 예측(정시 기준)과 조인하려면 정시로 내림(floor)한 컬럼이 필요하다.
    # (처음에 이걸 놓쳐서 merge 결과가 0행이 나온 적이 있음 - 2026-09-13)
    sdot['measure_hour'] = sdot['measure_time'].dt.floor('h')
    merged = sdot.merge(pred_df.rename(columns={'measure_time': 'measure_hour'}),
                         on=['sensor_id', 'measure_hour'], how='inner')
    merged['delta_t'] = merged['temp_avg'] - merged['predicted']
    merged['hour'] = merged['measure_hour'].dt.hour
    merged['is_night'] = merged['hour'].isin(NIGHT_HOURS)

    merged.to_parquet(OUTPUT_FILE, index=False)
    print(f"✅ 이상장 저장 → {OUTPUT_FILE} ({len(merged):,}행)")

    print("\n" + "=" * 60)
    print("G2 게이트 확인: 표본>=300대 / 야간 ΔT SD>=0.5°C")
    print("=" * 60)
    n_sensors = merged['sensor_id'].nunique()
    night_sd = merged.loc[merged['is_night'], 'delta_t'].std()
    print(f"표본(고유 센서 수): {n_sensors} -> {'통과' if n_sensors >= 300 else '미통과'}")
    print(f"야간 ΔT SD: {night_sd:.3f}°C -> {'통과' if night_sd >= 0.5 else '미통과'}")


if __name__ == '__main__':
    main()

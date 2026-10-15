"""
script29-build-ked-reference-loocv.py - KED(외부표류 크리깅) 참조장 LOOCV 검증 (Phase 1, G1 게이트)

AWS 서울 29개 지점(D2, 108 종로 포함 - ASOS 108과는 별개 취급, docs/preregistration.md
§3 참고) 기온 + DEM(SRTM 30m) 고도를 외부 표류변수로 사용해 시간별 KED 참조장을
만들고, 분석 대상 기간(2024-09-01~2026-08-30, v3 S-DoT 마스터와 동일 범위) 전체
시간에 대해 지점별 LOOCV(leave-one-out)를 수행한다.

방법:
- 시간마다 그 시각 유효 관측치가 있는 지점들로 UniversalKriging(외부표류=DEM,
  variogram_model='exponential')을 적합하고, 한 지점씩 제외한 뒤 그 지점 위치를
  예측 - 실측과 비교해 잔차를 기록한다 (지점 수만큼 재적합, 1시간당 29회).
- 고정 시간대 기준(사전등록, 2026-09-13): KST 22:00~05:59=야간, 06:00~21:59=주간.
- 유효 지점이 10개 미만인 시간은 KED가 불안정해질 수 있어 건너뛰고 별도 기록한다
  (실제로는 결측률이 낮아 거의 발생하지 않을 것으로 예상).

출력:
- data/interim/ked_loocv_residuals.parquet - 시간x지점별 잔차 전체
- 터미널에 G1 게이트(야간 RMSE<=1.0, 주간 RMSE<=1.5) 통과 여부 출력
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pykrige.uk import UniversalKriging

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AWS_PARQUET = PROJECT_ROOT / 'data' / 'interim' / 'kma_aws_seoul.parquet'
STATIONS_CSV = PROJECT_ROOT / 'metadata' / 'kma_aws_stations_seoul.csv'
DEM_TIF = PROJECT_ROOT / 'data' / 'raw' / 'D4_DEM' / 'seoul_srtm30m.tif'
OUTPUT_FILE = PROJECT_ROOT / 'data' / 'interim' / 'ked_loocv_residuals.parquet'

ANALYSIS_START = '2024-09-01 00:00:00'
ANALYSIS_END = '2026-08-30 23:00:00'
VARIOGRAM_MODEL = 'exponential'
MIN_VALID_STATIONS = 10
NIGHT_HOURS = set(list(range(22, 24)) + list(range(0, 6)))  # 22,23,0,1,2,3,4,5


def load_dem_grid():
    with rasterio.open(DEM_TIF) as src:
        dem = src.read(1).astype(float)
        transform = src.transform
        ncols, nrows = src.width, src.height
        xs = np.array([transform * (c + 0.5, 0) for c in range(ncols)])[:, 0]
        ys = np.array([transform * (0, r + 0.5) for r in range(nrows)])[:, 1]
    # rasterio 배열은 y가 내림차순(위->아래) - pykrige는 오름차순 좌표를 기대하므로 뒤집는다.
    return dem[::-1, :], xs, ys[::-1]


def main():
    print("🚀 [ KED 참조장 LOOCV 검증 시작 ]")
    stations = pd.read_csv(STATIONS_CSV)
    stations['stn_id'] = stations['stn_id'].astype(str)

    dem_grid, dem_x, dem_y = load_dem_grid()
    with rasterio.open(DEM_TIF) as src:
        elev_samples = [v[0] for v in src.sample(
            [(row.lon, row.lat) for row in stations.itertuples()])]
    stations['elevation'] = elev_samples
    stn_lookup = stations.set_index('stn_id')[['lat', 'lon', 'elevation']]

    aws = pd.read_parquet(AWS_PARQUET)
    aws = aws[(aws['measure_time'] >= ANALYSIS_START) & (aws['measure_time'] <= ANALYSIS_END)]
    aws = aws.dropna(subset=['ta'])
    print(f"분석 기간: {ANALYSIS_START} ~ {ANALYSIS_END}")
    print(f"대상 관측행 수: {len(aws):,}")

    hours = sorted(aws['measure_time'].unique())
    print(f"대상 시간 수: {len(hours):,}\n")

    residual_rows = []
    skipped_hours = 0
    start_time = time.time()

    for i, hour in enumerate(hours):
        hour_df = aws[aws['measure_time'] == hour].merge(
            stn_lookup, left_on='stn_id', right_index=True)
        n = len(hour_df)
        if n < MIN_VALID_STATIONS:
            skipped_hours += 1
            continue

        lons = hour_df['lon'].values
        lats = hour_df['lat'].values
        temps = hour_df['ta'].values
        stn_ids = hour_df['stn_id'].values
        hour_ts = pd.Timestamp(hour)
        is_night = hour_ts.hour in NIGHT_HOURS

        for j in range(n):
            mask = np.arange(n) != j
            try:
                uk = UniversalKriging(
                    lons[mask], lats[mask], temps[mask],
                    drift_terms=['external_Z'],
                    external_drift=dem_grid, external_drift_x=dem_x, external_drift_y=dem_y,
                    variogram_model=VARIOGRAM_MODEL, verbose=False, enable_plotting=False,
                )
                pred, _ = uk.execute('points', np.array([lons[j]]), np.array([lats[j]]))
                pred_val = float(pred[0])
            except Exception:
                pred_val = np.nan

            residual_rows.append({
                'measure_time': hour_ts, 'stn_id': stn_ids[j],
                'actual': temps[j], 'predicted': pred_val,
                'is_night': is_night,
            })

        if (i + 1) % 500 == 0 or (i + 1) == len(hours):
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            remaining = (len(hours) - i - 1) / rate if rate > 0 else float('nan')
            print(f"[{i+1:,}/{len(hours):,}] {elapsed/60:.1f}분 경과, "
                  f"예상 잔여 {remaining/60:.1f}분 (건너뛴 시간 {skipped_hours}개)")

    print(f"\n건너뛴 시간(유효지점<{MIN_VALID_STATIONS}): {skipped_hours}개")

    resid_df = pd.DataFrame(residual_rows)
    resid_df['error'] = resid_df['predicted'] - resid_df['actual']
    resid_df.to_parquet(OUTPUT_FILE, index=False)
    print(f"✅ 잔차 테이블 저장 → {OUTPUT_FILE} ({len(resid_df):,}행)")

    valid = resid_df.dropna(subset=['error'])
    fail_count = len(resid_df) - len(valid)
    if fail_count:
        print(f"⚠️  KED 피팅 실패(예외 발생) {fail_count}건은 RMSE 계산에서 제외")

    def rmse(x):
        return np.sqrt(np.mean(x ** 2))

    night_rmse = rmse(valid.loc[valid['is_night'], 'error'])
    day_rmse = rmse(valid.loc[~valid['is_night'], 'error'])
    n_night = valid['is_night'].sum()
    n_day = (~valid['is_night']).sum()

    print("\n" + "=" * 60)
    print("G1 게이트 확인: LOOCV RMSE 야간<=1.0°C / 주간<=1.5°C")
    print("=" * 60)
    print(f"야간 RMSE: {night_rmse:.3f}°C (n={n_night:,}) -> {'통과' if night_rmse <= 1.0 else '미통과'}")
    print(f"주간 RMSE: {day_rmse:.3f}°C (n={n_day:,}) -> {'통과' if day_rmse <= 1.5 else '미통과'}")


if __name__ == '__main__':
    main()

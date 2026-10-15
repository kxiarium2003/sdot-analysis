"""
script36-asos-holdout-validation.py - ASOS 종로(108) 홀드아웃 검증 (Phase 1, G1 보조)

가이드라인 §3: "검증: AWS LOOCV(주/야·계절별 RMSE), ASOS 종로 홀드아웃(크리깅 미포함)".
script29는 AWS LOOCV만 구현하고 있어 ASOS 홀드아웃을 별도 스크립트로 추가한다.

두 가지 변형을 같은 시간·같은 방식(script29와 동일한 UniversalKriging, 외부표류=DEM,
exponential)으로 계산하고 ASOS 108 실측과 대조한다:
- A(요청 사양): AWS 29개 지점 전체(AWS-108 포함)로 적합 → ASOS 108 위치 예측.
  AWS-108이 학습에 들어가 있으므로 이 값은 크리깅 자체의 독립 검증이 아니라
  "AWS 108 관측 ≈ 예측(정확 보간) vs ASOS 108 실측"의 기기 간 차이를 주로 반영한다.
- B(참고, 독립): AWS-108을 제외한 28개 지점으로 적합 → ASOS 108 위치 예측.
  108 위치는 어느 학습 관측에도 들어가지 않으므로 가이드라인이 의도한 독립 홀드아웃에 해당.
비교용으로 AWS-108 관측 vs ASOS-108 실측 차이(기기 간 차이)도 함께 기록한다.

TA sentinel(-9.0) 27건(`ta_at_sentinel`)의 처리는 아직 미확정이므로 삭제·대체하지 않고,
분석기간 내 해당 행(11건)을 포함/제외한 RMSE를 모두 보고한다.

출력:
- data/interim/asos_holdout_residuals.parquet - 시간별 실측·예측·오차
- 터미널에 야간/주간·계절별 RMSE와 G1 판정 출력

사용법: python scripts/script36-asos-holdout-validation.py [--limit N]
"""
import os
import sys
import time

# 워커 프로세스마다 BLAS 스레드가 폭증하면 fit 하나가 수백 배 느려지므로 1로 고정한다.
for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_v] = '1'

from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pykrige.uk import UniversalKriging

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AWS_PARQUET = PROJECT_ROOT / 'data' / 'interim' / 'kma_aws_seoul.parquet'
ASOS_PARQUET = PROJECT_ROOT / 'data' / 'interim' / 'kma_asos_108.parquet'
STATIONS_CSV = PROJECT_ROOT / 'metadata' / 'kma_aws_stations_seoul.csv'
LOOCV_FILE = PROJECT_ROOT / 'data' / 'interim' / 'ked_loocv_residuals.parquet'
OUTPUT_FILE = PROJECT_ROOT / 'data' / 'interim' / 'asos_holdout_residuals.parquet'


def find_dem():
    p = PROJECT_ROOT / 'data' / 'raw' / 'D4_DEM' / 'seoul_srtm30m.tif'
    if not p.exists():
        raise FileNotFoundError(p)
    return p


ANALYSIS_START = '2024-09-01 00:00:00'
ANALYSIS_END = '2026-08-30 23:00:00'
VARIOGRAM_MODEL = 'exponential'
MIN_VALID_STATIONS = 10
NIGHT_HOURS = set(list(range(22, 24)) + list(range(0, 6)))
TARGET_STN = '108'

_G = {}


def _init_worker(dem_path):
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(float)
        t = src.transform
        xs = np.array([t * (c + 0.5, 0) for c in range(src.width)])[:, 0]
        ys = np.array([t * (0, r + 0.5) for r in range(src.height)])[:, 1]
    _G['dem'], _G['x'], _G['y'] = dem[::-1, :], xs, ys[::-1]


def _predict(lons, lats, temps, x0, y0):
    try:
        uk = UniversalKriging(
            lons, lats, temps, drift_terms=['external_Z'],
            external_drift=_G['dem'], external_drift_x=_G['x'], external_drift_y=_G['y'],
            variogram_model=VARIOGRAM_MODEL, verbose=False, enable_plotting=False)
        pred, _ = uk.execute('points', np.array([x0]), np.array([y0]))
        return float(pred[0])
    except Exception:
        return np.nan


def _work(args):
    hour, lons, lats, temps, stn_ids, x0, y0 = args
    pred_all = _predict(lons, lats, temps, x0, y0)
    keep = stn_ids != TARGET_STN
    pred_ex = _predict(lons[keep], lats[keep], temps[keep], x0, y0) if keep.sum() >= MIN_VALID_STATIONS else np.nan
    aws108 = temps[stn_ids == TARGET_STN]
    return hour, pred_all, pred_ex, (float(aws108[0]) if len(aws108) else np.nan), len(temps)


def season(m):
    return {12: '겨울', 1: '겨울', 2: '겨울', 3: '봄', 4: '봄', 5: '봄',
            6: '여름', 7: '여름', 8: '여름', 9: '가을', 10: '가을', 11: '가을'}[m]


def rmse(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else float('nan')


def summarize(df, err_col, label):
    print(f"\n[{label}]  n={df[err_col].notna().sum():,}")
    print(f"  야간 RMSE {rmse(df.loc[df.is_night, err_col]):.3f}°C (기준 ≤1.0) / "
          f"주간 RMSE {rmse(df.loc[~df.is_night, err_col]):.3f}°C (기준 ≤1.5) / "
          f"전체 {rmse(df[err_col]):.3f}°C")
    for s in ['봄', '여름', '가을', '겨울']:
        d = df[df.season == s]
        print(f"  {s}: 야간 {rmse(d.loc[d.is_night, err_col]):.3f} / 주간 {rmse(d.loc[~d.is_night, err_col]):.3f} (n={d[err_col].notna().sum():,})")


def main():
    limit = None
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    dem_path = find_dem()
    stations = pd.read_csv(STATIONS_CSV)
    stations['stn_id'] = stations['stn_id'].astype(str)
    st = stations.set_index('stn_id')
    x0, y0 = float(st.loc[TARGET_STN, 'lon']), float(st.loc[TARGET_STN, 'lat'])
    print(f"ASOS 108 예측 위치(AWS 108 좌표와 동일 지점): lon={x0}, lat={y0}")

    aws = pd.read_parquet(AWS_PARQUET)
    aws = aws[(aws['measure_time'] >= ANALYSIS_START) & (aws['measure_time'] <= ANALYSIS_END)].dropna(subset=['ta'])
    aws['stn_id'] = aws['stn_id'].astype(str)
    aws = aws.merge(st[['lon', 'lat']], left_on='stn_id', right_index=True)
    asos = pd.read_parquet(ASOS_PARQUET)
    asos = asos[(asos['measure_time'] >= ANALYSIS_START) & (asos['measure_time'] <= ANALYSIS_END)]

    jobs = []
    for hour, g in aws.groupby('measure_time'):
        if len(g) < MIN_VALID_STATIONS:
            continue
        jobs.append((pd.Timestamp(hour), g['lon'].values, g['lat'].values, g['ta'].values,
                     g['stn_id'].values, x0, y0))
    if limit:
        jobs = jobs[:limit]
    print(f"대상 시간 수: {len(jobs):,} (script29와 동일 조건: 유효 AWS 지점 ≥{MIN_VALID_STATIONS})")

    t0 = time.time()
    rows = []
    with Pool(6, initializer=_init_worker, initargs=(dem_path,)) as pool:
        for i, r in enumerate(pool.imap(_work, jobs, chunksize=20)):
            rows.append(r)
            if (i + 1) % 1000 == 0:
                el = time.time() - t0
                print(f"[{i+1:,}/{len(jobs):,}] {el/60:.1f}분 경과, 예상 잔여 {(len(jobs)-i-1)/((i+1)/el)/60:.1f}분", flush=True)
    df = pd.DataFrame(rows, columns=['measure_time', 'pred_all29', 'pred_ex108', 'aws108_obs', 'n_stations'])
    df = df.merge(asos[['measure_time', 'ta', 'ta_at_sentinel']].rename(columns={'ta': 'asos_ta'}),
                  on='measure_time', how='left')
    df['err_all29'] = df['pred_all29'] - df['asos_ta']
    df['err_ex108'] = df['pred_ex108'] - df['asos_ta']
    df['err_aws_vs_asos'] = df['aws108_obs'] - df['asos_ta']
    df['is_night'] = df['measure_time'].dt.hour.isin(NIGHT_HOURS)
    df['season'] = df['measure_time'].dt.month.map(season)
    df['ta_at_sentinel'] = df['ta_at_sentinel'].fillna(False).astype(bool)
    if not limit:
        df.to_parquet(OUTPUT_FILE, index=False)
        print(f"\n✅ 저장 → {OUTPUT_FILE} ({len(df):,}행)")

    print(f"\nASOS 실측 결측 {df['asos_ta'].isna().sum()}시간, ta_at_sentinel 표시 {int(df['ta_at_sentinel'].sum())}시간")
    for label, sub in [('sentinel 포함(전체)', df), ('sentinel 행 제외', df[~df.ta_at_sentinel])]:
        print("\n" + "=" * 70 + f"\n{label}\n" + "=" * 70)
        summarize(sub, 'err_all29', 'A. AWS 29지점(108 포함) 적합 → ASOS 108 실측')
        summarize(sub, 'err_ex108', 'B. AWS 108 제외 28지점 적합 → ASOS 108 실측 (독립 홀드아웃)')
        summarize(sub, 'err_aws_vs_asos', 'C. 참고: AWS 108 관측 − ASOS 108 실측 (기기 간 차이)')

    if LOOCV_FILE.exists() and not limit:
        lo = pd.read_parquet(LOOCV_FILE).dropna(subset=['error'])
        lo['season'] = lo['measure_time'].dt.month.map(season)
        chk = df.merge(lo[lo.stn_id == TARGET_STN][['measure_time', 'predicted']], on='measure_time', how='inner')
        d = (chk['pred_ex108'] - chk['predicted']).abs()
        print(f"\n[검증] B(108 제외 재적합) vs script29 LOOCV의 108 회차 예측: {len(chk):,}시간 비교, 최대 |차이| {d.max():.2e}°C")
        eq = (df['aws108_obs'] == df['asos_ta']).sum()
        print(f"[검증] AWS 108 관측 == ASOS 108 실측인 시간: {eq:,}/{df['asos_ta'].notna().sum():,}")
        print("\n" + "=" * 70 + "\n참고: 기존 AWS LOOCV (script29 산출물)\n" + "=" * 70)
        for name, d in [('전체 29지점', lo), ('AWS 108 지점만', lo[lo.stn_id == '108'])]:
            print(f"\n[{name}] 야간 {rmse(d.loc[d.is_night, 'error']):.3f} / 주간 {rmse(d.loc[~d.is_night, 'error']):.3f}")
            for s in ['봄', '여름', '가을', '겨울']:
                x = d[d.season == s]
                print(f"  {s}: 야간 {rmse(x.loc[x.is_night, 'error']):.3f} / 주간 {rmse(x.loc[~x.is_night, 'error']):.3f}")


if __name__ == '__main__':
    main()

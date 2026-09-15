"""
script34-phase2-validation-map.py - Phase 2 검증 지도(산점도 + 공간잔차) 시각화

script32의 XGBoost 모델(공간블록 CV, GroupKFold by 자치구)의 out-of-fold 예측값을
441개 집계구의 실제 야간ΔT와 비교하는 산점도, 그리고 잔차(예측-실제)를 집계구
지도 위에 칠한 공간분포도를 만든다. Phase 1(G1)에서 이미 문제였던 5개 AWS
지점(412 서대문/407 노원/416 은평/419 중구/415 용산)에 가장 가까운 집계구를
색으로 구분해 체계적 편향 여부를 확인한다.

산출물: docs/phase2-validation-map.png
"""
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupKFold

plt.rcParams['font.family'] = 'AppleGothic'
plt.rcParams['axes.unicode_minus'] = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DATASET = PROJECT_ROOT / 'data' / 'interim' / 'zone_night_anomaly_model_dataset.parquet'
ZONES_FILE = PROJECT_ROOT / 'data' / 'interim' / 'seoul_census_oa_wgs84.geojson'
STATIONS_CSV = PROJECT_ROOT / 'metadata' / 'kma_aws_stations_seoul.csv'
OUTPUT_PNG = PROJECT_ROOT / 'docs' / 'phase2-validation-map.png'

RANDOM_STATE = 42
N_FOLDS = 5
PROBLEM_STATIONS = ['412', '407', '416', '419', '415']  # G1에서 이미 확인된 야간 RMSE 불량 지점


def main():
    print("🚀 [ Phase 2 검증 지도 생성 시작 ]")
    df = pd.read_parquet(MODEL_DATASET)
    feature_cols = [c for c in df.columns if c.startswith('lc_')] + \
        ['mean_elevation', 'total_pop', 'mean_age', 'pop_density', 'aging_index',
         'elderly_dependency', 'youth_dependency']
    X = df[feature_cols].values
    y = df['night_delta_t_mean'].values
    groups = df['gu_code'].values

    # --- 공간블록(자치구) GroupKFold의 out-of-fold 예측 수집 ---
    oof_pred = np.full(len(df), np.nan)
    gkf = GroupKFold(n_splits=N_FOLDS)
    for train_idx, test_idx in gkf.split(X, y, groups):
        model = xgb.XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.05,
                                  random_state=RANDOM_STATE)
        model.fit(X[train_idx], y[train_idx])
        oof_pred[test_idx] = model.predict(X[test_idx])
    df['predicted'] = oof_pred
    df['residual'] = df['predicted'] - df['night_delta_t_mean']
    print(f"out-of-fold 예측 완료: {df['predicted'].notna().sum()}/{len(df)}")

    # --- 집계구 중심점에서 가장 가까운 AWS 지점 찾기 ---
    zones = gpd.read_file(ZONES_FILE)
    zones['TOT_OA_CD'] = zones['TOT_OA_CD'].astype(str)
    zones_m = zones.to_crs('EPSG:5179')
    zones_m['centroid'] = zones_m.geometry.centroid
    centroids = zones_m[['TOT_OA_CD', 'centroid']].copy()

    stations = pd.read_csv(STATIONS_CSV, dtype={'stn_id': str})
    stn_gdf = gpd.GeoDataFrame(stations, geometry=gpd.points_from_xy(stations['lon'], stations['lat']),
                                crs='EPSG:4326').to_crs('EPSG:5179')

    nearest_stn = []
    for pt in centroids['centroid']:
        dists = stn_gdf.geometry.distance(pt)
        nearest_stn.append(stn_gdf.loc[dists.idxmin(), 'stn_id'])
    centroids['nearest_stn'] = nearest_stn
    centroids['near_problem_station'] = centroids['nearest_stn'].isin(PROBLEM_STATIONS)

    df = df.merge(centroids[['TOT_OA_CD', 'nearest_stn', 'near_problem_station']],
                  on='TOT_OA_CD', how='left')
    n_problem = df['near_problem_station'].sum()
    print(f"5개 문제지점이 최근접인 집계구: {n_problem}/{len(df)}")

    # --- 편향 통계 ---
    bias_problem = df.loc[df['near_problem_station'], 'residual'].mean()
    bias_other = df.loc[~df['near_problem_station'], 'residual'].mean()
    rmse_problem = np.sqrt((df.loc[df['near_problem_station'], 'residual'] ** 2).mean())
    rmse_other = np.sqrt((df.loc[~df['near_problem_station'], 'residual'] ** 2).mean())
    print(f"문제지점 인근 집계구({n_problem}개): 평균잔차={bias_problem:.3f}, RMSE={rmse_problem:.3f}")
    print(f"그 외 집계구({len(df)-n_problem}개): 평균잔차={bias_other:.3f}, RMSE={rmse_other:.3f}")

    # ================= 그림 =================
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))

    # --- 왼쪽: 산점도 ---
    ax = axes[0]
    colors = df['near_problem_station'].map({True: '#d62728', False: '#1f77b4'})
    ax.scatter(df.loc[~df['near_problem_station'], 'night_delta_t_mean'],
               df.loc[~df['near_problem_station'], 'predicted'],
               c='#1f77b4', alpha=0.6, s=25, label=f'그 외 집계구 (n={len(df)-n_problem})')
    ax.scatter(df.loc[df['near_problem_station'], 'night_delta_t_mean'],
               df.loc[df['near_problem_station'], 'predicted'],
               c='#d62728', alpha=0.8, s=35, label=f'문제지점(412/407/416/419/415) 인근 (n={n_problem})')
    lims = [df[['night_delta_t_mean', 'predicted']].min().min() - 0.2,
            df[['night_delta_t_mean', 'predicted']].max().max() + 0.2]
    ax.plot(lims, lims, 'k--', alpha=0.5, label='y=x (완전 일치)')
    ax.set_xlim(lims)
    ax.set_ylim(lims)
    ax.set_xlabel('실제 야간 ΔT (°C)')
    ax.set_ylabel('예측 야간 ΔT (°C, 공간블록 CV out-of-fold)')
    ax.set_title('Phase 2 XGBoost 검증: 실제 vs 예측 (441개 집계구)')
    ax.legend(loc='upper left', fontsize=9)
    ax.set_aspect('equal', adjustable='box')

    # --- 오른쪽: 공간 잔차 지도 ---
    ax2 = axes[1]
    zones_with_resid = zones.merge(df[['TOT_OA_CD', 'residual']], on='TOT_OA_CD', how='inner')
    vmax = zones_with_resid['residual'].abs().max()
    zones_with_resid.plot(column='residual', cmap='RdBu_r', vmin=-vmax, vmax=vmax,
                           legend=True, ax=ax2, markersize=1,
                           legend_kwds={'label': '잔차(예측-실제, °C)', 'shrink': 0.7})
    # 전체 서울 윤곽(참고용, 얇은 회색 경계)
    zones.boundary.plot(ax=ax2, linewidth=0.05, color='lightgray')
    # 문제지점 인근 집계구 테두리 강조
    problem_zones = zones_with_resid.merge(
        df.loc[df['near_problem_station'], ['TOT_OA_CD']], on='TOT_OA_CD')
    problem_zones.boundary.plot(ax=ax2, linewidth=0.8, color='black')
    ax2.set_title('공간 잔차 분포 (검은 테두리 = 문제지점 인근 집계구)')
    ax2.set_axis_off()

    plt.tight_layout()
    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches='tight')
    print(f"\n✅ 저장 완료: {OUTPUT_PNG}")

    return df, bias_problem, bias_other, rmse_problem, rmse_other


if __name__ == '__main__':
    main()

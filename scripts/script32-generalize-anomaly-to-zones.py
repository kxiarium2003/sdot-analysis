"""
script32-generalize-anomaly-to-zones.py - 이상장(ΔT)의 집계구 일반화 (Phase 2, G3 게이트)

script31에서 계산한 S-DoT 센서별 야간 이상장(ΔT)을 집계구(D9) 단위로 집계하고,
집계구 공변량(D10 토지피복 비율, D6 인구통계, D4 평균고도)으로 XGBoost/OLS 모델을
학습해 K-fold 교차검증한다.

G3 게이트: 교차검증 예측오차(RMSE) < 야간 이상장의 집계구간 공간표준편차.
이 비교가 의미하는 것: 모델이 "그냥 전체 평균으로 찍는 것"보다 얼마나 나은지를
정확히 보여준다(공간SD = 상수 예측의 RMSE와 사실상 같음). 또한 Phase 1에서
G1 야간 LOOCV가 미달했던 사실(docs/preregistration.md §4.1)이 이 단계 오차에도
어느 정도 섞여 들어올 수 있으므로, G3 결과를 "집계구 일반화 모델 자체의 한계"로만
해석하지 않고 "입력(이상장)에 이미 있던 잡음"과 분리해서 봐야 한다(연구자 지시,
2026-09-13).
"""
import os
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import statsmodels.api as sm
import xgboost as xgb
from rasterio.mask import mask
from sklearn.model_selection import GroupKFold, KFold

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANOMALY_FILE = PROJECT_ROOT / 'data' / 'interim' / 'sdot_anomaly_field_202409_202608.parquet'
ZONES_FILE = PROJECT_ROOT / 'data' / 'interim' / 'seoul_census_oa_wgs84.geojson'
LANDCOVER_FILE = PROJECT_ROOT / 'data' / 'interim' / 'seoul_landcover_l2_wgs84.geojson'
DEM_TIF = PROJECT_ROOT / 'data' / 'raw' / 'D4_DEM' / 'seoul_srtm30m.tif'
POP_DIR = PROJECT_ROOT / 'data' / 'raw' / 'D6_SGIS_stats'
MASTER_V2 = PROJECT_ROOT / 'data' / 'processed' / 'master-v2' / 'sdot_master_2020_2026_v2.parquet'
OUTPUT_FILE = PROJECT_ROOT / 'data' / 'interim' / 'zone_night_anomaly_model_dataset.parquet'

N_FOLDS = 5
RANDOM_STATE = 42
POP_ITEM_LABELS = {
    'to_in_001': 'total_pop', 'to_in_002': 'mean_age', 'to_in_003': 'pop_density',
    'to_in_004': 'aging_index', 'to_in_005': 'elderly_dependency', 'to_in_006': 'youth_dependency',
}


def build_zone_night_target():
    import duckdb
    con = duckdb.connect()
    zones = gpd.read_file(ZONES_FILE)
    zones['TOT_OA_CD'] = zones['TOT_OA_CD'].astype(str)

    sc = con.execute(f"""
        SELECT sensor_id, ANY_VALUE(latitude) AS lat, ANY_VALUE(longitude) AS lon
        FROM read_parquet('{MASTER_V2.as_posix()}')
        WHERE latitude IS NOT NULL GROUP BY sensor_id
    """).fetchdf()
    sensor_gdf = gpd.GeoDataFrame(sc, geometry=gpd.points_from_xy(sc['lon'], sc['lat']), crs='EPSG:4326')
    joined = gpd.sjoin(sensor_gdf, zones[['TOT_OA_CD', 'geometry']], how='inner', predicate='within')
    zone_map = joined[['sensor_id', 'TOT_OA_CD']]

    anomaly = pd.read_parquet(ANOMALY_FILE)
    anomaly = anomaly.merge(zone_map, on='sensor_id', how='inner')
    night = anomaly[anomaly['is_night']]
    zone_night = night.groupby('TOT_OA_CD')['delta_t'].agg(['mean', 'std', 'count']).reset_index()
    zone_night.columns = ['TOT_OA_CD', 'night_delta_t_mean', 'night_delta_t_std', 'n_obs']
    return zone_night, zones


def build_landcover_fractions(zones_subset):
    landcover = gpd.read_file(LANDCOVER_FILE)
    lc_filtered = gpd.sjoin(landcover, zones_subset[['TOT_OA_CD', 'geometry']],
                             how='inner', predicate='intersects')[['L2_NAME', 'geometry']]
    zones_m = zones_subset[['TOT_OA_CD', 'geometry']].to_crs('EPSG:5179')
    lc_m = lc_filtered.to_crs('EPSG:5179')
    overlay = gpd.overlay(lc_m, zones_m, how='intersection')
    overlay['area'] = overlay.geometry.area
    zone_total_area = zones_m.set_index('TOT_OA_CD').geometry.area
    frac = overlay.groupby(['TOT_OA_CD', 'L2_NAME'])['area'].sum().unstack(fill_value=0)
    frac = frac.div(zone_total_area.reindex(frac.index), axis=0)
    frac.columns = [f'lc_{c}' for c in frac.columns]
    return frac.reset_index()


def build_elevation(zones_subset):
    with rasterio.open(DEM_TIF) as src:
        elevs = []
        for geom in zones_subset.geometry:
            out_img, _ = mask(src, [geom], crop=True, nodata=-32768)
            vals = out_img[0].astype(float)
            vals[vals == -32768] = np.nan
            elevs.append(np.nanmean(vals))
    return pd.DataFrame({'TOT_OA_CD': zones_subset['TOT_OA_CD'].values, 'mean_elevation': elevs})


def build_population():
    frames = []
    for f in os.listdir(POP_DIR):
        if '인구총괄' in unicodedata.normalize('NFC', f):
            df = pd.read_csv(POP_DIR / f, header=None, encoding='cp949',
                              names=['year', 'oa_cd', 'item_cd', 'value'])
            frames.append(df)
    pop = pd.concat(frames, ignore_index=True)
    pop['oa_cd'] = pop['oa_cd'].astype(str)
    pivot = pop.pivot_table(index='oa_cd', columns='item_cd', values='value').rename(columns=POP_ITEM_LABELS)
    pivot = pivot[[c for c in POP_ITEM_LABELS.values() if c in pivot.columns]]
    return pivot.reset_index().rename(columns={'oa_cd': 'TOT_OA_CD'})


def main():
    print("🚀 [ 이상장 집계구 일반화(Phase 2, G3) 시작 ]")
    zone_night, zones = build_zone_night_target()
    zones_subset = zones[zones['TOT_OA_CD'].isin(zone_night['TOT_OA_CD'])].copy()
    print(f"야간 이상장 있는 집계구: {len(zone_night)}개")

    landcover_frac = build_landcover_fractions(zones_subset)
    elevation = build_elevation(zones_subset)
    population = build_population()

    # 자치구(구) 코드 - ADM_CD(8자리 행정동코드) 앞 5자리 = 시도(2)+시군구(3).
    # 공간블록 CV(GroupKFold)에서 "같은 동네끼리 몰려서 생기는 과대평가"를
    # 걸러내기 위한 그룹 단위로 사용(2026-09-14, 연구자 지시).
    zones_subset['gu_code'] = zones_subset['ADM_CD'].astype(str).str[:5]

    df = zone_night.merge(landcover_frac, on='TOT_OA_CD', how='left') \
                    .merge(elevation, on='TOT_OA_CD', how='left') \
                    .merge(population, on='TOT_OA_CD', how='left') \
                    .merge(zones_subset[['TOT_OA_CD', 'gu_code']], on='TOT_OA_CD', how='left')
    df = df.dropna()
    print(f"결측 제거 후 최종 표본: {len(df)}개 집계구, {df['gu_code'].nunique()}개 자치구")
    df.to_parquet(OUTPUT_FILE, index=False)

    feature_cols = [c for c in df.columns if c.startswith('lc_')] + \
        ['mean_elevation', 'total_pop', 'mean_age', 'pop_density', 'aging_index',
         'elderly_dependency', 'youth_dependency']
    X = df[feature_cols].values
    y = df['night_delta_t_mean'].values
    spatial_sd = y.std()
    print(f"\n야간 ΔT 집계구간 공간SD: {spatial_sd:.3f}°C (n={len(y)})")

    def run_cv(splitter, groups=None):
        xgb_errors, ols_errors = [], []
        split_args = (X, y, groups) if groups is not None else (X,)
        for train_idx, test_idx in splitter.split(*split_args):
            model = xgb.XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.05,
                                      random_state=RANDOM_STATE)
            model.fit(X[train_idx], y[train_idx])
            xgb_errors.extend(model.predict(X[test_idx]) - y[test_idx])

            X_train = sm.add_constant(X[train_idx])
            X_test = sm.add_constant(X[test_idx], has_constant='add')
            ols_model = sm.OLS(y[train_idx], X_train).fit()
            ols_errors.extend(ols_model.predict(X_test) - y[test_idx])
        xgb_rmse = np.sqrt(np.mean(np.array(xgb_errors) ** 2))
        ols_rmse = np.sqrt(np.mean(np.array(ols_errors) ** 2))
        return xgb_rmse, ols_rmse

    # --- 방식 1: 랜덤 K-fold (기존, 2026-09-13) ---
    kf = KFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    xgb_rmse_random, ols_rmse_random = run_cv(kf)

    # --- 방식 2: 공간블록 CV - 자치구 단위 GroupKFold (2026-09-14 추가, 연구자 지시) ---
    # 가이드라인이 "랜덤 CV 단독 평가 금지, 공간 블록(자치구) CV 병행"을 명시함.
    # 같은 자치구의 집계구들은 지형/피복/인구 특성이 비슷해 랜덤 분할이면 test
    # fold에도 train과 매우 유사한 이웃 집계구가 섞여 들어가 성능이 과대평가될
    # 위험이 있음 - GroupKFold로 자치구 전체를 통째로 train 또는 test에만 넣어서
    # "본 적 없는 동네에 대한 일반화 성능"을 본다.
    groups = df['gu_code'].values
    gkf = GroupKFold(n_splits=N_FOLDS)
    xgb_rmse_spatial, ols_rmse_spatial = run_cv(gkf, groups=groups)

    print(f"\n야간 ΔT 집계구간 공간SD(G3 기준값): {spatial_sd:.3f}°C\n")
    print(f"{'모델':<10} {'랜덤 CV':>12} {'공간블록 CV(자치구)':>20}")
    print(f"{'XGBoost':<10} {xgb_rmse_random:>10.3f}°C {xgb_rmse_spatial:>18.3f}°C")
    print(f"{'OLS':<10} {ols_rmse_random:>10.3f}°C {ols_rmse_spatial:>18.3f}°C")

    print("\n" + "=" * 60)
    print("G3 게이트 확인: 예측오차(CV RMSE) < 야간 이상장 공간SD")
    print("=" * 60)
    print(f"공간SD 기준값: {spatial_sd:.3f}°C\n")
    print("[랜덤 CV]")
    print(f"  XGBoost: {xgb_rmse_random:.3f}°C -> {'통과' if xgb_rmse_random < spatial_sd else '미통과'}")
    print(f"  OLS:     {ols_rmse_random:.3f}°C -> {'통과' if ols_rmse_random < spatial_sd else '미통과'}")
    print("[공간블록 CV(자치구)]")
    print(f"  XGBoost: {xgb_rmse_spatial:.3f}°C -> {'통과' if xgb_rmse_spatial < spatial_sd else '미통과'}")
    print(f"  OLS:     {ols_rmse_spatial:.3f}°C -> {'통과' if ols_rmse_spatial < spatial_sd else '미통과'}")


if __name__ == '__main__':
    main()

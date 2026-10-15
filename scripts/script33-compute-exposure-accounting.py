"""
script33-compute-exposure-accounting.py - 거주 기반(E^R) vs 활동 기반(E^A) 열노출 회계 (Phase 3, RQ1/G4)

⚠️ 준비 스크립트입니다. D5(생활인구) 전체 수집(2024-09~2026-07, 23개월)이 끝나기
전까지는 --full 없이 --test 모드로만 돌려서 로직/문법만 검증하십시오. 전체 실행은
D5 전체 완료를 확인한 뒤 사용자 지시에 따라 진행합니다.

구성:
1. extend_delta_t_to_all_zones() - script32에서 441개 집계구로 검증한 XGBoost 모델을
   전체 데이터로 재학습해 D9 전체(19,097개, 또는 --test 시 일부) 집계구로 ΔT 예측 확장
2. compute_residential_exposure() - D6(거주인구, 이미 완료)로 E^R 계산
3. compute_activity_exposure() - D5(생활인구)로 E^A 계산. 스키마는 아래 "중요 발견"
   섹션 참고. --test 모드에서는 지금까지 완료된 달(native만, 202410~202502 중
   그 시점에 로컬에 남아있는 파일)로 로직만 검증한다 - 전체 기간 커버 못 하므로
   결과 수치를 최종으로 쓰지 않는다.
4. compute_gap_and_gate() - Gap = E^A - E^R, G4(순위상관>0.98이면 회귀) 확인

중요 발견 (2026-09-13, 반드시 인지하고 쓸 것):
- D5(생활인구)의 `집계구코드`는 13자리이고 D9(SGIS 2025 Q2, `TOT_OA_CD`)의 14자리와
  코드 체계 자체가 다르다(행정동코드 기준 비교 시 7.5%만 겹침 - 단순 자릿수 문제가
  아니라 행정동 통폐합으로 인한 코드 개편 때문으로 추정). 사용자가 D5와 정확히
  일치하는 2016년 집계구 경계(`data/raw/D9_zone_boundary/seoul_census_oa_boundary_2016/집계구.shp`,
  `TOT_REG_CD` 13자리, D5와 100% 일치 확인됨)를 구해서, 2016년 폴리곤 중심점이
  2025년 어느 D9 폴리곤 안에 들어가는지로 공간 매핑 크로스워크를 만들었다
  (`data/interim/oa_code_crosswalk_2016_to_2025.csv`, 19,152/19,153=99.99% 매칭,
  1건 미매칭은 조사 안 함 - 무시 가능한 수준). **D5를 쓸 때는 반드시 이 크로스워크로
  TOT_OA_CD로 변환한 뒤에 D9/D6/ΔT와 조인할 것 - 원본 집계구코드로 직접 조인하면
  안 됨.**
- D5 컬럼명에 BOM 아티팩트가 섞여 있음(예: `?"기준일ID"`) - script30의 CSV 파싱
  이슈로 보임, 이 스크립트에서는 그 컬럼을 안 쓰므로 무시하고 진행하되, 나중에
  손대게 되면 이 아티팩트부터 정리할 것.
- D5는 `시간대구분`(0~23시)으로 시간 해상도가 있고 성별×10세 단위 연령 인구수
  컬럼이 있음(예: `남자20세부터24세생활인구수`). 이번 준비 단계에서는 **총생활인구수만
  사용**(연령×SES 세부 분해는 Gap/G4 로직이 먼저 검증된 뒤 추가할 것 - 지금 단계의
  의도적 단순화, 원 연구설계의 "연령집단별" 요구사항은 아직 미구현).
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xgboost as xgb
from rasterio.mask import mask
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ZONES_FILE = PROJECT_ROOT / 'data' / 'interim' / 'seoul_census_oa_wgs84.geojson'
LANDCOVER_FILE = PROJECT_ROOT / 'data' / 'interim' / 'seoul_landcover_l2_wgs84.geojson'
DEM_TIF = PROJECT_ROOT / 'data' / 'raw' / 'D4_DEM' / 'seoul_srtm30m.tif'
MODEL_DATASET = PROJECT_ROOT / 'data' / 'interim' / 'zone_night_anomaly_model_dataset.parquet'
CROSSWALK_FILE = PROJECT_ROOT / 'data' / 'interim' / 'oa_code_crosswalk_2016_to_2025.csv'
D5_DIR = PROJECT_ROOT / 'data' / 'interim' / 'seoul_living_population' / 'native'
POP_DIR = PROJECT_ROOT / 'data' / 'raw' / 'D6_SGIS_stats'
GAP_OUTPUT_FILE = PROJECT_ROOT / 'data' / 'interim' / 'phase3_gap_by_zone.parquet'

RANDOM_STATE = 42
G4_RANK_CORR_THRESHOLD = 0.98


def build_zone_features(zones_subset):
    """
    집계구별 토지피복비율+고도.

    ⚠️ 성능 수정(2026-09-14): 원래 벡터 overlay(gpd.overlay) 방식은 441개
    집계구에서 126초였는데, 서울 전체(19,097개)로 확장 시도하니 2,000개도
    12분 넘게 안 끝나 중단함(선형이 아니라 훨씬 나쁘게 스케일링됨). **래스터
    기반 zonal stats로 교체** - 토지피복 폴리곤을 DEM과 같은 그리드로 1회
    rasterize한 뒤, 집계구마다 그 창(window)만 잘라 픽셀 값 개수를 세는
    방식(픽셀=30m). 검증: 441개 임의 표본 기준 래스터화 24초(1회) + 집계구
    처리 0.7초 - 벡터 방식보다 수백 배 빠르고 19,097개로도 선형에 가깝게
    확장됨(예상 ~30초).
    """
    landcover = gpd.read_file(LANDCOVER_FILE)
    code_map = {code: i + 1 for i, code in enumerate(sorted(landcover['L2_CODE'].unique()))}
    name_map = landcover.drop_duplicates('L2_CODE').set_index('L2_CODE')['L2_NAME'].to_dict()
    inv_code_map = {v: k for k, v in code_map.items()}

    with rasterio.open(DEM_TIF) as src:
        out_shape = src.shape
        transform = src.transform
        crs = src.crs

    from rasterio.features import rasterize
    shapes = [(geom, code_map[code]) for geom, code in zip(landcover.geometry, landcover['L2_CODE'])]
    lc_raster = rasterize(shapes, out_shape=out_shape, transform=transform, fill=0, dtype='uint8')

    from rasterio.io import MemoryFile
    lc_rows, elevs = [], []
    with MemoryFile() as lc_memfile:
        with lc_memfile.open(driver='GTiff', height=out_shape[0], width=out_shape[1], count=1,
                              dtype='uint8', crs=crs, transform=transform) as tmp:
            tmp.write(lc_raster, 1)
        lc_src = lc_memfile.open()
        dem_src = rasterio.open(DEM_TIF)
        try:
            for _, row in zones_subset.iterrows():
                geom = [row.geometry]
                lc_img, _ = mask(lc_src, geom, crop=True, nodata=0)
                vals, counts = np.unique(lc_img[0], return_counts=True)
                keep = vals != 0
                total = counts[keep].sum()
                d = {'TOT_OA_CD': row['TOT_OA_CD']}
                for v, c in zip(vals[keep], counts[keep]):
                    code = inv_code_map[v]
                    d[f'lc_{name_map[code]}'] = c / total if total > 0 else np.nan
                lc_rows.append(d)

                dem_img, _ = mask(dem_src, geom, crop=True, nodata=-32768)
                dvals = dem_img[0].astype(float)
                dvals[dvals == -32768] = np.nan
                elevs.append(np.nanmean(dvals))
        finally:
            lc_src.close()
            dem_src.close()

    frac = pd.DataFrame(lc_rows).fillna(0)
    frac['mean_elevation'] = elevs
    return frac


def load_population_covariates():
    import os
    import unicodedata
    item_labels = {
        'to_in_001': 'total_pop', 'to_in_002': 'mean_age', 'to_in_003': 'pop_density',
        'to_in_004': 'aging_index', 'to_in_005': 'elderly_dependency', 'to_in_006': 'youth_dependency',
    }
    frames = []
    for f in os.listdir(POP_DIR):
        if '인구총괄' in unicodedata.normalize('NFC', f):
            df = pd.read_csv(POP_DIR / f, header=None, encoding='cp949',
                              names=['year', 'oa_cd', 'item_cd', 'value'])
            frames.append(df)
    pop = pd.concat(frames, ignore_index=True)
    pop['oa_cd'] = pop['oa_cd'].astype(str)
    pivot = pop.pivot_table(index='oa_cd', columns='item_cd', values='value').rename(columns=item_labels)
    pivot = pivot[[c for c in item_labels.values() if c in pivot.columns]]
    return pivot.reset_index().rename(columns={'oa_cd': 'TOT_OA_CD'})


def extend_delta_t_to_all_zones(test_n_zones=None):
    """
    441개 집계구 학습 데이터 전체로 최종 XGBoost를 학습하고, D9 전체(또는 테스트용
    일부) 집계구에 대해 야간 ΔT를 예측한다.

    test_n_zones: None이면 D9 전체(19,097개) - 매우 오래 걸림(토지피복 overlay가
    441개에서 126초였으므로 전체는 수십 배). 정수를 주면 그 개수만큼 무작위 표본
    집계구로만 계산해 로직만 빠르게 검증한다(--test 모드 기본값).
    """
    train_df = pd.read_parquet(MODEL_DATASET)
    feature_cols = [c for c in train_df.columns if c.startswith('lc_')] + \
        ['mean_elevation', 'total_pop', 'mean_age', 'pop_density', 'aging_index',
         'elderly_dependency', 'youth_dependency']

    model = xgb.XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.05,
                              random_state=RANDOM_STATE)
    model.fit(train_df[feature_cols].values, train_df['night_delta_t_mean'].values)

    zones = gpd.read_file(ZONES_FILE)
    zones['TOT_OA_CD'] = zones['TOT_OA_CD'].astype(str)
    if test_n_zones is not None:
        zones = zones.sample(n=min(test_n_zones, len(zones)), random_state=RANDOM_STATE)
        print(f"⚠️  테스트 모드: 전체 {len(gpd.read_file(ZONES_FILE))}개 중 {len(zones)}개 표본만 예측")

    zone_features = build_zone_features(zones)
    # 대상 집계구 수가 적으면(특히 --test) 토지피복 20종 중 일부가 아예 안 나타나서
    # 그 lc_ 컬럼 자체가 생성 안 될 수 있음 - 학습 때 쓴 컬럼 기준으로 맞추고
    # 없는 분류는 그 집계구에 0%(실제로 없는 게 맞음)로 채운다.
    lc_cols = [c for c in feature_cols if c.startswith('lc_')]
    for c in lc_cols:
        if c not in zone_features.columns:
            zone_features[c] = 0.0

    population = load_population_covariates()
    full = zone_features.merge(population, on='TOT_OA_CD', how='left')

    missing_before = len(full)
    full = full.dropna(subset=feature_cols)
    if len(full) < missing_before:
        print(f"⚠️  공변량 결측으로 {missing_before - len(full)}개 집계구 제외됨")

    full['predicted_night_delta_t'] = model.predict(full[feature_cols].values)
    return full[['TOT_OA_CD', 'predicted_night_delta_t']]


def compute_residential_exposure(zone_delta_t, population):
    """
    E^R: 거주지 기준 열노출.

    ⚠️ 설계 수정(2026-09-13, --test 로직검증 중 발견): 처음엔 집계구별 exposure를
    그냥 ΔT_zone으로 뒀는데, 이러면 E^R_zone과 E^A_zone이 항상 완전히 같아져서
    (같은 집계구의 같은 ΔT값이므로) G4 순위상관이 무조건 1.0이 나오는 무의미한
    비교가 됨 - 실제로 --test 1차 실행에서 이 버그를 확인함(corr=1.0000,
    gap std=0.000). 인구가 "가중치"로만 쓰이고 집계구별 값 자체엔 반영이 안 됐던
    게 원인.
    → **exposure_contribution = 인구 x ΔT** ("이 집계구가 기여하는 총 노출량",
    person-degree 단위)로 바꿔서, 거주인구 분포와 활동인구 분포가 다른 집계구는
    실제로 다른 값이 나오게 함. 도시 전체 대표값은 이 접근과 별개로 인구가중평균
    ΔT(citywide_weighted_mean)로 계속 보고한다(직관적인 "평균 몇 도 더 덥게
    느끼는가" 지표로서 의미 있음, exposure_contribution과 용도가 다를 뿐 둘 다
    유지). **이 정의도 실행 전 연구자 확인 필요** - 아직 사전등록 안 됨.
    """
    df = zone_delta_t.merge(population[['TOT_OA_CD', 'total_pop']], on='TOT_OA_CD', how='inner')
    df['exposure_contribution'] = df['total_pop'] * df['predicted_night_delta_t']
    citywide_weighted_mean = np.average(df['predicted_night_delta_t'], weights=df['total_pop'])
    out = df.rename(columns={'total_pop': 'weight'})[['TOT_OA_CD', 'exposure_contribution', 'weight']]
    return out, citywide_weighted_mean


def compute_activity_exposure(zone_delta_t, crosswalk, test_mode=True):
    """
    E^A: 활동(생활인구) 기준 열노출. D5 야간시간대(22~05시, script29/31과 동일
    정의) 평균 생활인구로 가중평균.

    test_mode=True: 로컬에 남아있는 D5 native 달만 사용(전체 기간 아님 - 로직
    검증용).

    ⚠️ 스트리밍 다운로드로 변경(2026-09-14): D5 파이프라인(script30)이 로컬
    parquet을 Google Drive 업로드 검증 후 삭제하는 방식이라 --full 시점엔 로컬에
    파일이 하나도 안 남아있었음(23개월 전부 `.done`만 있고 parquet 없음). 전체를
    한 번에 rclone copy하면 44.98GiB인데 로컬 여유공간이 33GiB뿐이라 다 못 받음
    → 월별로 하나씩 rclone copy로 받고, 필요한 3개 컬럼만 뽑아 야간평균 집계한
    뒤 즉시 로컬 파일을 지우는 스트리밍 방식으로 처리(피크 디스크 사용량 ~2GB).
    """
    import glob
    import subprocess
    RCLONE_REMOTE_D5 = 'googledrive:sdot-analysis/interim/seoul_living_population/native'
    night_hours = list(range(22, 24)) + list(range(0, 6))

    local_files = sorted(glob.glob(str(D5_DIR / '*.parquet')))
    done_files = sorted(glob.glob(str(D5_DIR / '*.done')))
    if test_mode:
        if local_files:
            print(f"⚠️  테스트 모드: 현재 로컬에 있는 D5 {len(local_files)}개월치만 사용 "
                  f"({[Path(f).stem for f in local_files]}) - 전체 기간 아님, 결과 수치 최종 아님")
            target_months = [Path(f).stem for f in local_files]
        else:
            # 로컬 파일이 하나도 없으면(업로드 후 전부 삭제된 상태) 전체를 받지
            # 않고 앞쪽 2개월만 Drive에서 받아 로직만 검증한다.
            target_months = [Path(f).stem for f in done_files][:2]
            print(f"⚠️  테스트 모드: 로컬에 D5 파일이 없어 Drive에서 {len(target_months)}개월만 "
                  f"받아 테스트({target_months}) - 전체 기간 아님, 결과 수치 최종 아님")
    else:
        # .done 마커 기준으로 완료된 전체 달 목록 확보 (--full 기본 경로)
        target_months = [Path(f).stem for f in done_files]
        print(f"D5 대상 월: {len(target_months)}개월 ({target_months[0]}~{target_months[-1]}) "
              f"- Google Drive에서 월별로 스트리밍 다운로드")

    dfs = []
    for ym in target_months:
        local_path = D5_DIR / f'{ym}.parquet'
        downloaded_here = False
        if not local_path.exists():
            result = subprocess.run(
                ['rclone', 'copy', f'{RCLONE_REMOTE_D5}/{ym}.parquet', str(D5_DIR)],
                capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  ⚠️  {ym} rclone 다운로드 실패, 건너뜀: {result.stderr[:200]}")
                continue
            downloaded_here = True
        try:
            d = pd.read_parquet(local_path, columns=['집계구코드', '시간대구분', '총생활인구수'])
        except Exception as e:
            print(f"  ⚠️  {ym}.parquet 읽기 실패, 건너뜀: {e}")
            continue
        finally:
            if downloaded_here:
                local_path.unlink(missing_ok=True)  # 스트리밍 - 처리 즉시 삭제(디스크 절약)
        d = d[d['시간대구분'].isin(night_hours)]
        d['집계구코드'] = d['집계구코드'].astype(str)
        dfs.append(d.groupby('집계구코드')['총생활인구수'].mean().reset_index())
        print(f"  [{ym}] 처리 완료")
    if not dfs:
        raise RuntimeError("읽을 수 있는 D5 파일이 하나도 없습니다.")
    d5_night = pd.concat(dfs, ignore_index=True).groupby('집계구코드')['총생활인구수'].mean().reset_index()
    d5_night.columns = ['TOT_REG_CD', 'night_activity_pop']

    crosswalk['TOT_REG_CD'] = crosswalk['TOT_REG_CD'].astype(str)
    crosswalk['TOT_OA_CD'] = crosswalk['TOT_OA_CD'].astype(str)
    d5_night = d5_night.merge(crosswalk, on='TOT_REG_CD', how='inner')
    # 2016년 집계구 여러 개가 2025년 집계구 하나로 합쳐졌을 수 있으니 합산
    d5_night_2025 = d5_night.groupby('TOT_OA_CD')['night_activity_pop'].sum().reset_index()

    df = zone_delta_t.merge(d5_night_2025, on='TOT_OA_CD', how='inner')
    df['exposure_contribution'] = df['night_activity_pop'] * df['predicted_night_delta_t']
    citywide_weighted_mean = np.average(df['predicted_night_delta_t'], weights=df['night_activity_pop'])
    out = df.rename(columns={'night_activity_pop': 'weight'})[['TOT_OA_CD', 'exposure_contribution', 'weight']]
    return out, citywide_weighted_mean


def compute_gap_and_gate(er_df, ea_df):
    """
    Gap = E^A - E^R, 집계구별 "노출 기여도"(인구 x ΔT, person-degree 단위) 비교.
    G4: 순위상관(스피어만) > 0.98이면 "인구를 거주 기준으로 보든 활동 기준으로
    보든 어느 집계구가 노출이 큰지 순서가 거의 안 바뀐다"는 뜻이므로 회귀(재검토)
    필요. 인구분포 자체(거주 vs 활동)가 유의미하게 다른 집계구가 있다면 상관이
    낮게 나와야 정상.
    """
    merged = er_df[['TOT_OA_CD', 'exposure_contribution']].rename(
        columns={'exposure_contribution': 'E_R'}).merge(
        ea_df[['TOT_OA_CD', 'exposure_contribution']].rename(
            columns={'exposure_contribution': 'E_A'}),
        on='TOT_OA_CD', how='inner')
    merged['gap'] = merged['E_A'] - merged['E_R']

    corr, pval = spearmanr(merged['E_R'], merged['E_A'])
    print(f"\nGap(노출기여도, person-degree) 요약: mean={merged['gap'].mean():.3f}, "
          f"std={merged['gap'].std():.3f}, n={len(merged)}")
    print(f"E^R-E^A 순위상관(Spearman): {corr:.4f} (p={pval:.2e})")
    print(f"G4 게이트(순위상관>0.98이면 회귀): "
          f"{'⚠️ 회귀 필요(E^A/E^R가 사실상 같은 순서)' if corr > G4_RANK_CORR_THRESHOLD else '통과(의미있게 다름)'}")
    return merged


def main():
    test_mode = '--full' not in sys.argv
    if test_mode:
        print("🧪 [ TEST 모드 - 로직/문법 검증만, 전체 실행 아님 ]")
        print("    D5 전체 수집(23개월) 완료 확인 후 --full로 재실행하십시오.\n")
    else:
        print("🚀 [ FULL 모드 - 전체 실행 ]")
        response = input("D5 전체(2024-09~2026-07, 23개월) 수집이 정말 끝났습니까? (yes/no): ")
        if response.strip().lower() != 'yes':
            print("중단합니다.")
            sys.exit(0)

    n_test_zones = 30 if test_mode else None
    zone_delta_t = extend_delta_t_to_all_zones(test_n_zones=n_test_zones)
    print(f"\nΔT 예측된 집계구 수: {len(zone_delta_t)}")

    population = load_population_covariates()
    er_df, er_citywide = compute_residential_exposure(zone_delta_t, population)
    print(f"E^R 도시전체 인구가중평균: {er_citywide:.3f}°C (n={len(er_df)}개 집계구)")

    crosswalk = pd.read_csv(CROSSWALK_FILE, dtype=str)
    ea_df, ea_citywide = compute_activity_exposure(zone_delta_t, crosswalk, test_mode=test_mode)
    print(f"E^A 도시전체 인구가중평균: {ea_citywide:.3f}°C (n={len(ea_df)}개 집계구)")

    gap_df = compute_gap_and_gate(er_df, ea_df)
    print(f"\n도시전체 Gap(E^A-E^R): {ea_citywide - er_citywide:.3f}°C")

    if not test_mode:
        # 2026-09-14 보완: --full 결과가 콘솔 요약만 남고 집계구별 테이블은
        # 저장이 안 돼서, 이후 지도 등 후속 작업(script35)에서 D5 23개월을
        # 통째로 재다운로드해야 했음 - 로직 변경 없이 저장 누락만 보완.
        gap_df.to_parquet(GAP_OUTPUT_FILE, index=False)
        print(f"집계구별 Gap 테이블 저장: {GAP_OUTPUT_FILE}")

    if test_mode:
        print("\n🧪 [ TEST 모드 종료 ] 위 수치는 표본이 작아 최종 결과가 아닙니다 - "
              "로직/문법 검증 목적입니다.")


if __name__ == '__main__':
    main()

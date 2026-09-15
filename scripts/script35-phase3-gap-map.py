"""
script35-phase3-gap-map.py - Phase 3 집계구별 Gap(E^A-E^R) 공간분포 지도

script33-compute-exposure-accounting.py를 수정하지 않고(연구자 지시, 2026-09-14
- Phase 3 스크립트 재작성 여부 미결정) 그 안의 함수를 그대로 재사용해 집계구별
Gap 테이블을 다시 만들고, 이번에는 파일로 저장한 뒤 지도를 그린다.

--full 실행(2026-09-14) 결과는 콘솔 요약만 남고 집계구별 테이블을 저장하지
않았기 때문에, E^A 계산에 필요한 D5(생활인구) 23개월을 다시 스트리밍
다운로드해야 한다(script33과 동일한 방식 - 다운로드 후 즉시 삭제, 약 1시간
소요). 이번에는 결과 테이블을 `data/interim/phase3_gap_by_zone.parquet`에
저장해 다음에는 재사용할 수 있게 한다.

산출물: output/phase3/gap-map.png
"""
import importlib.util
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams['font.family'] = 'AppleGothic'
plt.rcParams['axes.unicode_minus'] = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ZONES_FILE = PROJECT_ROOT / 'data' / 'interim' / 'seoul_census_oa_wgs84.geojson'
GAP_CACHE = PROJECT_ROOT / 'data' / 'interim' / 'phase3_gap_by_zone.parquet'
OUTPUT_DIR = PROJECT_ROOT / 'output' / 'phase3'
OUTPUT_PNG = OUTPUT_DIR / 'gap-map.png'

spec = importlib.util.spec_from_file_location(
    's33', PROJECT_ROOT / 'scripts' / 'script33-compute-exposure-accounting.py')
s33 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s33)


def build_gap_table():
    if GAP_CACHE.exists():
        print(f"캐시 사용: {GAP_CACHE}")
        return pd.read_parquet(GAP_CACHE)

    print("🚀 [ Gap 테이블 재계산 시작 (script33 함수 재사용, 파일은 수정 안 함) ]")
    zone_delta_t = s33.extend_delta_t_to_all_zones(test_n_zones=None)
    print(f"ΔT 예측된 집계구 수: {len(zone_delta_t)}")

    population = s33.load_population_covariates()
    er_df, er_citywide = s33.compute_residential_exposure(zone_delta_t, population)
    print(f"E^R 도시전체 인구가중평균: {er_citywide:.3f}°C")

    crosswalk = pd.read_csv(s33.CROSSWALK_FILE, dtype=str)
    ea_df, ea_citywide = s33.compute_activity_exposure(zone_delta_t, crosswalk, test_mode=False)
    print(f"E^A 도시전체 인구가중평균: {ea_citywide:.3f}°C")

    gap_df = s33.compute_gap_and_gate(er_df, ea_df)
    gap_df.to_parquet(GAP_CACHE, index=False)
    print(f"저장(다음 실행 시 재사용 가능): {GAP_CACHE}")
    return gap_df


def main():
    gap_df = build_gap_table()
    gap_df['TOT_OA_CD'] = gap_df['TOT_OA_CD'].astype(str)
    print(f"\n지도 대상 집계구 수: {len(gap_df)}")
    print(f"Gap 양수(E^A>E^R) 집계구: {(gap_df['gap'] > 0).sum()}개")
    print(f"Gap 음수(E^A<E^R) 집계구: {(gap_df['gap'] < 0).sum()}개")

    zones = gpd.read_file(ZONES_FILE)
    zones['TOT_OA_CD'] = zones['TOT_OA_CD'].astype(str)
    zones_with_gap = zones.merge(gap_df[['TOT_OA_CD', 'gap']], on='TOT_OA_CD', how='inner')

    fig, ax = plt.subplots(figsize=(10, 10))
    vmax = zones_with_gap['gap'].abs().quantile(0.98)  # 극단 이상치에 컬러스케일 다 뺏기지 않게
    zones_with_gap.plot(column='gap', cmap='RdBu_r', vmin=-vmax, vmax=vmax,
                         legend=True, ax=ax,
                         legend_kwds={'label': 'Gap = E^A - E^R (person-degree)', 'shrink': 0.6})
    zones.boundary.plot(ax=ax, linewidth=0.05, color='lightgray')
    ax.set_title(f'Phase 3: 집계구별 Gap(E^A-E^R) 공간분포 (n={len(zones_with_gap):,})\n'
                 '빨강=활동기반이 거주기반보다 노출 큼, 파랑=반대')
    ax.set_axis_off()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches='tight')
    print(f"\n✅ 저장 완료: {OUTPUT_PNG}")

    # 자치구별 패턴 확인 (구 단위로 뭉쳐있는지)
    zones_with_gap['gu_code'] = zones_with_gap['ADM_CD'].astype(str).str[:5]
    gu_summary = zones_with_gap.groupby('gu_code')['gap'].mean().sort_values()
    print("\n자치구별 평균 Gap(하위 5개 / 상위 5개):")
    print(gu_summary.head(5))
    print("...")
    print(gu_summary.tail(5))


if __name__ == '__main__':
    main()

"""
script28-dedupe-identical-rows.py - 원인 A(파일 겹침으로 인한 완전 동일 중복 행) 제거

docs/data-source-notes.md에서 확인한 두 가지 중복 메커니즘 중 원인 A(순수 파일 겹침,
값 완전 동일)만 제거한다. 원인 B(measure_time 12시간 접힘 등으로 값이 서로 다른
"충돌" 그룹)는 아직 원인이 확정되지 않았으므로 이 스크립트에서 절대 건드리지 않는다
- (sensor_id, measure_time) 그룹 안의 모든 행이 전체 컬럼 기준으로 완전히 동일한
경우에만 첫 번째 행만 남기고 나머지를 제거한다. 단 1건이라도 값이 다르면 그 그룹
전체를 원본 그대로 보존한다.

판정 방식: 전체 컬럼(131개)에 대해 pandas.util.hash_pandas_object로 행 해시를
벡터화 계산 -> (sensor_id, measure_time) 그룹별로 해시 유니크값이 1개면 "완전 동일
그룹"으로 판정. 전체 폭 테이블을 정렬(sort)하지 않으므로 script23이 겪었던
sort-OOM과 무관하고, 해시 계산도 groupby.transform 기반 벡터 연산이라 가볍다.

입력: data/interim/v8/ (수정하지 않음, 그대로 보존)
출력: data/interim/v9/ (원인 A만 제거된 새 버전)
"""
import gc
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parent.parent
v8_dir = PROJECT_ROOT / 'data' / 'interim' / 'v8'
v9_dir = PROJECT_ROOT / 'data' / 'interim' / 'v9'
v9_dir.mkdir(parents=True, exist_ok=True)

print("🚀 [ 원인 A(완전 동일 중복) 제거 시작 - v8 -> v9 ]\n")

grand_total_before = 0
grand_total_after = 0

for year in range(2020, 2027):
    src = v8_dir / f'sdot_{year}_v8.parquet'
    if not src.exists():
        continue
    dst = v9_dir / f'sdot_{year}_v9.parquet'

    df = pq.ParquetFile(src).read().to_pandas()
    before = len(df)

    row_hash = pd.util.hash_pandas_object(df, index=False)
    dup_key_mask = df.duplicated(subset=['sensor_id', 'measure_time'], keep=False)

    if dup_key_mask.any():
        key_df = df.loc[dup_key_mask, ['sensor_id', 'measure_time']].copy()
        key_df['_h'] = row_hash[dup_key_mask].values
        nun = key_df.groupby(['sensor_id', 'measure_time'])['_h'].transform('nunique')
        identical_mask = nun.eq(1)  # index = key_df.index (df의 부분집합)

        identical_idx = key_df.index[identical_mask]
        drop_candidates = df.loc[identical_idx].duplicated(subset=['sensor_id', 'measure_time'], keep='first')
        drop_idx = df.loc[identical_idx].index[drop_candidates]

        n_groups_identical = key_df.loc[identical_idx].groupby(['sensor_id', 'measure_time']).ngroups
        n_groups_conflict = key_df.loc[key_df.index[~identical_mask]].groupby(['sensor_id', 'measure_time']).ngroups

        df_out = df.drop(index=drop_idx)
    else:
        drop_idx = []
        n_groups_identical = 0
        n_groups_conflict = 0
        df_out = df

    after = len(df_out)
    grand_total_before += before
    grand_total_after += after

    print(f"{year}: {before:,} -> {after:,}행 ({len(drop_idx):,}건 제거) | 완전동일그룹={n_groups_identical:,} 충돌그룹(보존)={n_groups_conflict:,}")

    table = pa.Table.from_pandas(df_out, preserve_index=False)
    pq.write_table(table, dst)

    del df, df_out, table, row_hash, dup_key_mask
    gc.collect()

print()
print(f"✅ 전체: {grand_total_before:,} -> {grand_total_after:,}행 ({grand_total_before - grand_total_after:,}건 제거)")
print(f"💾 저장 위치: {v9_dir.relative_to(PROJECT_ROOT)}")

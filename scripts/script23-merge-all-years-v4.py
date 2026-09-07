"""
script23-merge-all-years-v4.py - v8 마스터 데이터 통합 + 위치정보 매핑 (script18/21의 후속)

data/interim/v8/sdot_{year}_v8.parquet(script22 산출물 - measure_time 매핑 버그
수정, 4개 날짜포맷 정규화, 병합 불변식 검증, 연도 이상치 플래그까지 완료)을
하나의 마스터 parquet으로 통합하면서 동시에 위치정보(위경도/자치구)를 매핑한다.

메모리 전략: 연도 파일 전체를 한 번에 메모리에 올리지 않고 script21과 동일하게
100만 행 배치로 스트리밍 처리한다. 시간순 정렬은 하지 않는다 - 8GB RAM 환경에서
1000만 행급 파일을 pandas/pyarrow로 정렬하다가 OOM으로 두 번 죽은 뒤 내린 결정
(실측: 2020년 530만행 read+write는 성공, 정렬을 더하자 2021년 1000만행에서 실패).
정렬이 필요하면 사용/쿼리 시점(DuckDB 등)에 하면 되고, 컬럼 130여개짜리 테이블
전체를 미리 정렬해두는 이득보다 OOM 리스크가 더 크다.

measure_time_source / measure_time_tx_reg_mismatch / measure_time_year_outlier
플래그 컬럼은 그대로 보존 (버리지 않고 표시만 하는 프로젝트 원칙 유지 - 이상치
1건도 여기서 제외하지 않고 마스터에 포함, 표본 선정 시점에 필터링할 것).
"""
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parent.parent
interim_dir = PROJECT_ROOT / 'data' / 'interim' / 'v8'
processed_dir = PROJECT_ROOT / 'data' / 'processed'
metadata_dir = PROJECT_ROOT / 'metadata'
processed_dir.mkdir(parents=True, exist_ok=True)

meta_file = metadata_dir / '서울시 도시데이터 센서(S-DoT) 환경정보 설치 위치정보.xlsx'
output_file = processed_dir / 'sdot_master_2020_2026_v2.parquet'
interim_files = sorted(interim_dir.glob('sdot_*_v8.parquet'))

if not interim_files:
    print("❌ [오류] data/interim/v8/에 병합할 파일이 없습니다. script22를 먼저 실행하세요.")
    sys.exit(1)

print("🚀 [ v8 마스터 데이터 통합 + 위치정보 매핑 시작 ]")
print(f"📁 대상 파일: {len(interim_files)}개\n")
start_time = time.time()

# ==========================================
# [STEP 1] 위치정보 매핑 딕셔너리 구축 (script21과 동일 로직)
# ==========================================
print("[STEP 1] 위치정보 메타데이터 로드 중...")
df_meta = pd.read_excel(meta_file)
df_meta['current_id'] = df_meta['모델 시리얼(*)'].astype(str).str.strip()
df_meta['gu_name'] = df_meta['주소'].astype(str).str.extract(r'서울특별시\s+([가-힣]+구)')

active_ids = set(df_meta['current_id'].unique())
id_map = {}
old_cols = [c for c in df_meta.columns if '변경 전 시리얼' in c]
for _, row in df_meta.iterrows():
    new_id = row['current_id']
    for col in old_cols:
        old_id = str(row[col]).strip()
        if old_id and old_id.lower() not in ['nan', 'none', ''] and old_id not in active_ids:
            id_map[old_id] = new_id

df_meta_latest = df_meta.drop_duplicates(subset=['current_id'], keep='last')
lat_dict = df_meta_latest.set_index('current_id')['위도'].to_dict()
lon_dict = df_meta_latest.set_index('current_id')['경도'].to_dict()
gu_dict = df_meta_latest.set_index('current_id')['gu_name'].to_dict()
print(f"  - 과거 ID 매핑 {len(id_map)}건, 위치정보 보유 센서 {len(lat_dict)}개\n")

# ==========================================
# [STEP 2] 배치 스트리밍으로 통합 + 위치 매핑 (script21과 동일한 저메모리 패턴)
# ==========================================
print("[STEP 2] 배치 스트리밍 통합 진행 중 (배치당 100만 행)")
writer = None
total_rows = 0
missing_loc_rows = 0

try:
    for file in interim_files:
        pf = pq.ParquetFile(file)
        for batch in pf.iter_batches(batch_size=1_000_000):
            df_chunk = batch.to_pandas()

            if id_map:
                df_chunk['lookup_id'] = df_chunk['sensor_id'].replace(id_map)
            else:
                df_chunk['lookup_id'] = df_chunk['sensor_id']

            df_chunk['latitude'] = df_chunk['lookup_id'].map(lat_dict)
            df_chunk['longitude'] = df_chunk['lookup_id'].map(lon_dict)
            df_chunk['gu_name'] = df_chunk['lookup_id'].map(gu_dict)
            df_chunk = df_chunk.drop(columns=['lookup_id'])

            missing_loc_rows += df_chunk['latitude'].isna().sum()
            total_rows += len(df_chunk)

            table = pa.Table.from_pandas(df_chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(output_file, table.schema)
            writer.write_table(table)

        print(f"  - {file.name} 처리 완료 (누적 {total_rows:,}행)", flush=True)
except Exception as e:
    print(f"\n❌ [오류] 처리 중 에러 발생: {e}")
    if writer:
        writer.close()
    sys.exit(1)
finally:
    if writer:
        writer.close()

print(f"\n✅ 통합 완료. 총 {total_rows:,}행")
print(f"위치 매핑 성공: {total_rows - missing_loc_rows:,}행 / 누락(고아): {missing_loc_rows:,}행 ({missing_loc_rows/total_rows*100:.2f}%)\n")

# ==========================================
# 사후 검증
# ==========================================
print("🔍 사후 검증 중...")
pf = pq.ParquetFile(output_file)
master_rows = pf.metadata.num_rows
if master_rows != total_rows:
    print(f"❌ [FAIL] 행수 불일치! (기대: {total_rows:,} -> 실제: {master_rows:,})")
    sys.exit(1)
print(f"✅ 행수 일치 확인: {master_rows:,}행")

elapsed_minutes = (time.time() - start_time) / 60
print("-" * 50)
print(f"💾 저장 위치: {output_file.relative_to(PROJECT_ROOT)}")
print(f"⏱️ 소요 시간: 약 {elapsed_minutes:.1f}분")
print("-" * 50)

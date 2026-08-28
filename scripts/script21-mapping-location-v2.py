"""
script22-mapping-location-v2.py - S-DoT 위치정보 공간 매핑 스크립트 
- 정밀 정규표현식을 통한 자치구 추출
- 과거 기기 ID를 활용한 위치 매핑 (원본 시계열 독립성 유지 및 현역 센서 보호)
- PyArrow Batch Processing을 통한 OOM 방어
"""
import pandas as pd
import pyarrow.parquet as pq
import pyarrow as pa
from pathlib import Path
import time
import sys

# 1. 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
processed_dir = PROJECT_ROOT / 'data' / 'processed'
metadata_dir = PROJECT_ROOT / 'metadata'

master_file = processed_dir / 'sdot_master_2020_2026.parquet'
meta_file = metadata_dir / '서울시 도시데이터 센서(S-DoT) 환경정보 설치 위치정보.xlsx'
output_file = processed_dir / 'sdot_master_2020_2026_geocoded.parquet'

if not master_file.exists():
    print(f"오류: 마스터 파케이 파일이 존재하지 않습니다. 경로: {master_file}")
    sys.exit(1)

print("--- [ S-DoT 위치정보 공간 매핑 시작 ] ---\n")
start_time = time.time()

# ==========================================
# [STEP 1] 엑셀 메타데이터 로드 및 매핑 딕셔너리 생성
# ==========================================
print("[STEP 1] 메타데이터 분석 및 매핑 딕셔너리 구축 진행 중...")
try:
    df_meta = pd.read_excel(meta_file)
    
    # 1. 기준 ID 정제
    df_meta['current_id'] = df_meta['모델 시리얼(*)'].astype(str).str.strip()
    
    # 2. '주소'에서 '자치구' 추출 (정밀 정규표현식 적용)
    df_meta['gu_name'] = df_meta['주소'].astype(str).str.extract(r'서울특별시\s+([가-힣]+구)')
    
    # 3. 현재 현역으로 뛰고 있는 최신 ID 목록 확보 (안전장치용)
    active_ids = set(df_meta['current_id'].unique())
    
    # 4. 과거 ID ➔ 최신 ID 매핑 딕셔너리(id_map) 생성
    id_map = {}
    old_cols = [c for c in df_meta.columns if '변경 전 시리얼' in c]
    
    for _, row in df_meta.iterrows():
        new_id = row['current_id']
        for col in old_cols:
            old_id = str(row[col]).strip()
            
            # [핵심 안전장치] 과거 ID가 유효하고, 현재 '현역 ID'로 존재하지 않을 때만 매핑
            if old_id and old_id.lower() not in ['nan', 'none', ''] and old_id not in active_ids:
                id_map[old_id] = new_id
                
    if id_map:
        print(f"  - 통합 대기 중인 과거 센서 ID 수: {len(id_map)}개")
    
    # 5. 위치 매핑을 위해 가장 최신(마지막) 위치 정보만 남기기
    df_meta_latest = df_meta.drop_duplicates(subset=['current_id'], keep='last')
    
    lat_dict = df_meta_latest.set_index('current_id')['위도'].to_dict()
    lon_dict = df_meta_latest.set_index('current_id')['경도'].to_dict()
    gu_dict = df_meta_latest.set_index('current_id')['gu_name'].to_dict()

except Exception as e:
    print(f"오류: 엑셀 파일 처리 중 문제가 발생했습니다: {e}")
    sys.exit(1)

# ==========================================
# [STEP 2] 대용량 파케이 메모리 최적화 매핑 (Batch Processing)
# ==========================================
print("\n[STEP 2] 대용량 마스터 데이터 공간 매핑 진행 중")
try:
    parquet_file = pq.ParquetFile(master_file)
    writer = None
    
    total_rows = 0
    missing_loc_rows = 0
    batch_count = 0
    
    for batch in parquet_file.iter_batches(batch_size=1_000_000):
        batch_count += 1
        print(f"  - Batch {batch_count} 매핑 중... ", end="", flush=True)
        
        df_chunk = batch.to_pandas()
        
        # 원본 sensor_id는 시계열 분석을 위해 유지하고, 매핑용 임시 ID(lookup_id) 생성
        if id_map:
            df_chunk['lookup_id'] = df_chunk['sensor_id'].replace(id_map)
        else:
            df_chunk['lookup_id'] = df_chunk['sensor_id']
        
        # 임시 조회용 ID(최신 ID)를 기준으로 위도, 경도, 자치구 매핑
        df_chunk['latitude'] = df_chunk['lookup_id'].map(lat_dict)
        df_chunk['longitude'] = df_chunk['lookup_id'].map(lon_dict)
        df_chunk['gu_name'] = df_chunk['lookup_id'].map(gu_dict)
        
        # 조회용 임시 컬럼 삭제
        df_chunk = df_chunk.drop(columns=['lookup_id'])
        
        missing_loc_rows += df_chunk['latitude'].isna().sum()
        total_rows += len(df_chunk)
        
        table = pa.Table.from_pandas(df_chunk)
        if writer is None:
            writer = pq.ParquetWriter(output_file, table.schema)
            
        writer.write_table(table)
        print("완료")
        
except Exception as e:
    print(f"\n오류: 매핑 중 에러가 발생했습니다: {e}")
    if writer: writer.close()
    sys.exit(1)
finally:
    if writer: writer.close()

# ==========================================
# [STEP 3] 리포트
# ==========================================
end_time = time.time()
print("\n--- [ 위치정보 공간 매핑 종료 ] ---")
print(f"총 처리 데이터: {total_rows:,}행")
print(f"위치 확보(매핑 성공): {total_rows - missing_loc_rows:,}행")
print(f"위치정보 누락(고아): {missing_loc_rows:,}행 ({(missing_loc_rows/total_rows)*100:.2f}%)")
print(f"총 소요 시간: {(end_time - start_time) / 60:.1f}분")
"""
script19-mapping-location.py - S-DoT 위치정보 매핑 스크립트
(센서 Relocation 추적 + OOM 방어 Batch 매핑)
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
    print(f"❌ [오류] 마스터 파케이 파일이 없습니다.")
    sys.exit(1)

print("🚀 [ S-DoT 위치정보 매핑 및 이사 추적 시작 ]\n")
start_time = time.time()

# ==========================================
# [STEP 1] 센서 이사(Relocation) 이력 추적 및 딕셔너리 생성
# ==========================================
print("📂 [STEP 1] 위치정보 분석 및 센서 이사 현황 추적 중...")
try:
    df_meta = pd.read_excel(meta_file)
    df_meta['sensor_id_clean'] = df_meta['모델 시리얼(*)'].astype(str).str.strip()
    
    # '자치구' 컬럼 유연하게 찾기 (자치구, 자치구명, 시군구명 등)
    gu_cols = [c for c in df_meta.columns if '구' in c and ('자치' in c or '행정' in c or '시군' in c)]
    gu_col = gu_cols[0] if gu_cols else None
    
    # 중복(이사)된 센서들 찾기
    dup_mask = df_meta.duplicated(subset=['sensor_id_clean'], keep=False)
    dup_sensors = df_meta[dup_mask]
    
    total_sensors = len(df_meta['sensor_id_clean'].unique())
    
    print("-" * 50)
    if not dup_sensors.empty:
        moved_count = len(dup_sensors['sensor_id_clean'].unique())
        print(f"⚠️ [센서 이동 감지] 전체 {total_sensors:,}개 센서 중 {moved_count}개의 센서가 이사(위치 변경) 이력이 있습니다.")
        
        # 자치구를 넘나든 굵직한 이사 케이스만 상세 출력
        if gu_col:
            cross_gu_moves = []
            for sid, group in dup_sensors.groupby('sensor_id_clean'):
                gu_history = group[gu_col].dropna().astype(str).tolist()
                
                # 자치구가 아예 달라진 경우
                if len(set(gu_history)) > 1:
                    cross_gu_moves.append(f"[{sid}] {gu_history[0]} ➔ {gu_history[-1]}")
            
            if cross_gu_moves:
                print(f"🚨 이 중 {len(cross_gu_moves)}개는 아예 '자치구'를 넘나들며 이사했습니다!")
                for move in cross_gu_moves:
                    print(f"   - {move}")
            else:
                print("   - (모두 동일 자치구 내에서 위치만 살짝 이동한 케이스입니다.)")
    else:
        print(f"✅ 이동(이사)한 센서가 하나도 없습니다! (1센서 1위치 유지)")
    print("-" * 50 + "\n")

    # 매핑을 위해 가장 최신(마지막) 위치 정보만 남기기
    df_meta_latest = df_meta.drop_duplicates(subset=['sensor_id_clean'], keep='last')
    
    lat_dict = df_meta_latest.set_index('sensor_id_clean')['위도'].to_dict()
    lon_dict = df_meta_latest.set_index('sensor_id_clean')['경도'].to_dict()
    
    if gu_col:
        gu_dict = df_meta_latest.set_index('sensor_id_clean')[gu_col].to_dict()
    else:
        gu_dict = {}

except Exception as e:
    print(f"❌ [오류] 엑셀 파일 처리 중 문제 발생: {e}")
    sys.exit(1)

# ==========================================
# [STEP 2] 대용량 파케이 메모리 최적화 매핑 (Batch Processing)
# ==========================================
print("🏗️ [STEP 2] 대용량 마스터 데이터 공간 매핑 진행 중 (OOM 방지 모드)")
try:
    parquet_file = pq.ParquetFile(master_file)
    writer = None
    
    total_rows = 0
    missing_loc_rows = 0
    batch_count = 0
    
    for batch in parquet_file.iter_batches(batch_size=1_000_000):
        batch_count += 1
        print(f"   🔄 Batch {batch_count} 매핑 중... ", end="", flush=True)
        
        df_chunk = batch.to_pandas()
        
        # 위도, 경도, 자치구 매핑
        df_chunk['latitude'] = df_chunk['sensor_id'].map(lat_dict)
        df_chunk['longitude'] = df_chunk['sensor_id'].map(lon_dict)
        if gu_dict:
            df_chunk['gu_name'] = df_chunk['sensor_id'].map(gu_dict)
        
        missing_loc_rows += df_chunk['latitude'].isna().sum()
        total_rows += len(df_chunk)
        
        table = pa.Table.from_pandas(df_chunk)
        if writer is None:
            writer = pq.ParquetWriter(output_file, table.schema)
            
        writer.write_table(table)
        print("완료!")
        
except Exception as e:
    print(f"\n❌ [오류] 매핑 중 에러 발생: {e}")
    if writer: writer.close()
    sys.exit(1)
finally:
    if writer: writer.close()

# ==========================================
# [STEP 3] 리포트
# ==========================================
end_time = time.time()
print("\n" + "=" * 50)
print("🎉 [ 위치정보 완벽 매핑 종료! ]")
print(f"📊 총 처리 데이터: {total_rows:,}행")
print(f"📍 매핑 성공(위치 확보): {total_rows - missing_loc_rows:,}행")
print(f"⚠️ 위치정보 누락(고아): {missing_loc_rows:,}행 ({(missing_loc_rows/total_rows)*100:.2f}%)")
print(f"⏱️ 소요 시간: 약 {(end_time - start_time) / 60:.1f}분")
print("=" * 50)
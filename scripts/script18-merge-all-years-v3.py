"""
script18-merge-all-years-v4.py - 메모리 최적화 마스터 병합 스크립트 V4
(연도별 개별 정렬 후 Parquet 점진적 쓰기 기법 적용 -> OOM 커널 죽음 방지)
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import time
import sys
import gc  # 메모리 청소부

# 1. 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
interim_dir = PROJECT_ROOT / 'data' / 'interim'
processed_dir = PROJECT_ROOT / 'data' / 'processed'
processed_dir.mkdir(parents=True, exist_ok=True)

output_file = processed_dir / 'sdot_master_2020_2026.parquet'
interim_files = sorted(interim_dir.glob('sdot_*.parquet'))
interim_files = [f for f in interim_files if 'report' not in f.name and 'dropped' not in f.name]

if not interim_files:
    print("❌ [오류] 병합할 interim 파일이 없습니다.")
    sys.exit(1)

print("🚀 [ 메모리 최적화 마스터 데이터 병합 시작 ]")
print(f"📁 대상 파일: {len(interim_files)}개\n")

start_time = time.time()
writer = None
total_rows_expected = 0

print("🏗️ [STEP 1] 연도별 파일 로드 ➔ 정렬 ➔ Parquet 이어쓰기(Append)")

for file in interim_files:
    print(f"🔄 처리 중: {file.name} ... ", end="", flush=True)
    
    try:
        # 1. 파일 하나만 메모리에 로드
        df = pd.read_parquet(file)
        
        # 2. 해당 연도 내에서 시간순 정렬
        df['measure_time_str'] = df['measure_time'].astype(str).str.replace('_', ' ')
        df['measure_time_dt'] = pd.to_datetime(df['measure_time_str'], errors='coerce')
        df = df.sort_values(by='measure_time_dt', na_position='last')
        df = df.drop(columns=['measure_time_str', 'measure_time_dt'])
        
        # 3. PyArrow Table로 변환
        table = pa.Table.from_pandas(df)
        
        # 4. Parquet 파일에 점진적 쓰기 (최초 1회만 스키마 초기화)
        if writer is None:
            writer = pq.ParquetWriter(output_file, table.schema)
        
        writer.write_table(table)
        file_rows = len(df)
        total_rows_expected += file_rows
        print(f"완료! ({file_rows:,}행 저장)")
        
        # 5. 🚨 커널 죽음 방지: 메모리 강제 해제
        del df
        del table
        gc.collect()
        
    except Exception as e:
        print(f"\n❌ [오류] {file.name} 처리 중 에러 발생: {e}")
        if writer is not None:
            writer.close()
        sys.exit(1)

# 쓰기 완료 후 파일 닫기
if writer is not None:
    writer.close()

print(f"✅ 모든 연도 데이터 병합 및 정렬 완료. (총 {total_rows_expected:,}행 예상)\n")

# ==========================================
# [STEP 2] 사후 검증 (메타데이터만 읽어서 0.1초 만에 확인)
# ==========================================
print("🔍 [STEP 2] 사후 검증: 생성된 마스터 파케이 무결성 체크")
try:
    parquet_file = pq.ParquetFile(output_file)
    master_total_rows = parquet_file.metadata.num_rows
    
    if master_total_rows != total_rows_expected:
        print(f"❌ [FAIL] 행 수가 꼬였습니다! (예상: {total_rows_expected:,} -> 실제: {master_total_rows:,})")
        sys.exit(1)
        
    print(f"✅ 데이터 무결성 완벽! 유실된 행 0건.\n")
except Exception as e:
    print(f"❌ [오류] 사후 검증 중 문제 발생: {e}")
    sys.exit(1)

end_time = time.time()
elapsed_minutes = (end_time - start_time) / 60

print("-" * 50)
print("🎉 [최종 마스터 데이터 생성 완료 ]")
print(f"💾 저장 위치: {output_file.relative_to(PROJECT_ROOT)}")
print(f"📊 총 유효 데이터 수: {master_total_rows:,}행")
print(f"⏱️ 소요 시간: 약 {elapsed_minutes:.1f}분")
print("-" * 50)
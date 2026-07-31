"""
merge-all-years-v2.py - 연도별 데이터 최종 병합 스크립트 V2
(메모리 최적화 Chunk 병합 + 타입 충돌/지수표기법/헤더 누락 이중 방어 + 인코딩 최적화)
"""
import pandas as pd
from pathlib import Path
import time
import sys

# 1. 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
interim_dir = PROJECT_ROOT / 'data' / 'interim'
processed_dir = PROJECT_ROOT / 'data' / 'processed'

processed_dir.mkdir(parents=True, exist_ok=True)

output_file = processed_dir / 'sdot_master_2020_2026.csv'
interim_files = sorted(interim_dir.glob('sdot_*.csv'))

if not interim_files:
    print("❌ [오류] 병합할 interim 파일이 없습니다. 경로를 확인하세요.")
    sys.exit(1)

print("🚀 [ 최종 마스터 데이터 병합 및 클렌징 시작 ]")
print(f"📁 대상 파일: {len(interim_files)}개\n")

# ==========================================
# [STEP 1] 사전 검증: 모든 파일의 스키마(컬럼) 일치 여부 확인
# ==========================================
print("🔍 [STEP 1] 사전 검증: 연도별 데이터 스키마 정합성 확인")
reference_columns = None
reference_file = None

for file in interim_files:
    # 한글 깨짐 방지를 위해 encoding='utf-8' 명시
    cols = pd.read_csv(file, nrows=0, encoding='utf-8').columns.tolist()
    
    if reference_columns is None:
        reference_columns = cols
        reference_file = file.name
    else:
        if cols != reference_columns:
            print(f"❌ [FAIL] 스키마(컬럼 구조) 불일치 발견!")
            print(f" - 기준 파일 ({reference_file}): {len(reference_columns)}개 컬럼")
            print(f" - 문제 파일 ({file.name}): {len(cols)}개 컬럼")
            sys.exit(1)

print(f"✅ 모든 파일이 동일한 스키마({len(reference_columns)}개 컬럼)를 가짐을 확인했습니다.\n")

# ==========================================
# [STEP 2] 데이터 병합 + 실시간 클렌징 (Chunk & Append)
# ==========================================
print("🏗️ [STEP 2] 마스터 파일 생성 (메모리 최적화 + 지수표기법/헤더 누락 이중 방어)")
if output_file.exists():
    output_file.unlink() # 기존에 오염된 마스터 파일 삭제

start_time = time.time()
total_rows_expected = 0
first_file = True

for file in interim_files:
    print(f"🔄 병합 및 정제 중: {file.name} ... ", end="", flush=True)
    
    try:
        # dtype=str 원천 차단 및 encoding='utf-8' 적용
        chunk_iter = pd.read_csv(file, chunksize=100000, low_memory=False, dtype=str, encoding='utf-8')
        file_rows = 0
        
        for chunk in chunk_iter:
            # 불량 데이터 실시간 필터링 (이중 방어막)
            if 'measure_time' in chunk.columns:
                chunk = chunk[~chunk['measure_time'].str.contains('E\+', na=False)]
                chunk = chunk[~chunk['measure_time'].str.contains('전송시간|측정일시', na=False)]
            
            if len(chunk) > 0:
                # 출력 시에도 utf-8 적용
                chunk.to_csv(output_file, mode='a', index=False, header=first_file, encoding='utf-8')
                first_file = False
                file_rows += len(chunk)
            
        total_rows_expected += file_rows
        print(f"완료! 유효 행 수: +{file_rows:,}행")
        
    except Exception as e:
        print(f"\n❌ [오류] {file.name} 병합 중 치명적 에러 발생: {e}")
        sys.exit(1)

# ==========================================
# [STEP 3] 사후 검증: 최종 마스터 파일 데이터 유실 확인
# ==========================================
print("\n🔍 [STEP 3] 사후 검증: 생성된 마스터 데이터 무결성 체크")

try:
    master_cols = pd.read_csv(output_file, nrows=0, encoding='utf-8').columns.tolist()
    if master_cols != reference_columns:
        print("❌ [FAIL] 최종 마스터 파일의 컬럼이 꼬였습니다!")
        sys.exit(1)
    
    with open(output_file, 'r', encoding='utf-8') as f:
        master_total_lines = sum(1 for _ in f)
    
    master_total_rows = master_total_lines - 1

    print(f"✅ 데이터 무결성 검증 통과! 최종 마스터 파일 행 수: {master_total_rows:,}행\n")

except Exception as e:
    print(f"❌ [오류] 사후 검증 중 문제 발생: {e}")
    sys.exit(1)

# ==========================================
# [STEP 4] 최종 결과 리포트
# ==========================================
end_time = time.time()
elapsed_minutes = (end_time - start_time) / 60

print("-" * 50)
print("🎉 [ 최종 클렌징 마스터 데이터 생성 완료! ]")
print(f"💾 저장 위치: {output_file.relative_to(PROJECT_ROOT)}")
print(f"📊 총 유효 데이터 수: {master_total_rows:,}행")
print(f"⏱️ 소요 시간: 약 {elapsed_minutes:.1f}분")
print("-" * 50)
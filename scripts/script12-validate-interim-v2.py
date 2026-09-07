import pandas as pd
from pathlib import Path
import time
import sys

# 1. 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
interim_dir = PROJECT_ROOT / 'data' / 'interim'
interim_files = sorted(interim_dir.glob('sdot_*.csv'))

if not interim_files:
    print("❌ [오류] 검증할 interim 파일이 존재하지 않습니다.")
    sys.exit(1)

print("🔍 [ interim 데이터 무결성 최종 점검 시작 ]\n")

# ==========================================
# [STEP 1] 스키마(컬럼 구조) 일치 여부 검증
# ==========================================
print("1️⃣ 스키마(컬럼 구조) 일치 여부 검증")
reference_cols = None
reference_file = None
schema_passed = True

for file in interim_files:
    # 데이터는 읽지 않고 컬럼명만 빠르게 추출
    cols = pd.read_csv(file, nrows=0).columns.tolist()
    
    if reference_cols is None:
        reference_cols = cols
        reference_file = file.name
    elif cols != reference_cols:
        print(f"  ❌ [불일치] {file.name}의 컬럼이 {reference_file}과 다릅니다.")
        print(f"     - {reference_file}: {len(reference_cols)}개")
        print(f"     - {file.name}: {len(cols)}개")
        schema_passed = False

if schema_passed:
    print(f"  ✅ 모든 interim 파일의 컬럼(총 {len(reference_cols)}개)이 완벽히 일치합니다.\n")
else:
    print("\n🚨 컬럼 구조가 일치하지 않아 병합할 수 없습니다. 검증을 중단합니다.")
    sys.exit(1)

# ==========================================
# [STEP 2] 데이터 오염(지수표기법, 문자열 찌꺼기) 정밀 검사
# ==========================================
print("2️⃣ 데이터 오염(지수표기법, 문자열 찌꺼기) 정밀 검증")
start_time = time.time()
total_rows = 0
all_passed = True

for file in interim_files:
    print(f"  ▶️ 검사 중: {file.name} ... ", end="", flush=True)
    has_error = False
    file_rows = 0
    
    # 메모리 최적화를 위해 청크(Chunk) 단위로 스캔
    for chunk in pd.read_csv(file, chunksize=500000, low_memory=False, dtype=str):
        file_rows += len(chunk)
        
        if 'measure_time' in chunk.columns:
            # 1) 지수 표기법 검사
            if chunk['measure_time'].str.contains('E\+', na=False).any():
                has_error = True
                print("\n    ❌ [오류] 지수표기법(E+) 감지!")
                break
            
            # 2) 헤더 찌꺼기 검사 (한글이나 영문자가 포함되어 있는지)
            if chunk['measure_time'].str.contains('[가-힣a-zA-Z]', na=False, regex=True).any():
                has_error = True
                print("\n    ❌ [오류] 헤더 찌꺼기(문자열) 감지!")
                break

    total_rows += file_rows
    
    if not has_error:
        print(f"✅ 이상 없음 (총 {file_rows:,}행)")
    else:
        all_passed = False

# ==========================================
# [STEP 3] 최종 검증 결과
# ==========================================
print("-" * 50)
if all_passed:
    print(f"🎉 [ 검증 통과! ]")
    print(f"  - 총 검증된 유효 데이터: {total_rows:,}행")
    print(f"  - 소요 시간: {round(time.time() - start_time, 1)}초")
    print("✅ 모든 점검을 통과했습니다. 이제 마스터 병합 스크립트를 안심하고 실행하셔도 좋습니다!")
else:
    print("🚨 [ 검증 실패 ] 일부 파일에서 오류가 발견되었습니다. 마스터 병합을 진행하지 마세요.")
print("-" * 50)
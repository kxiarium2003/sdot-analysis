import pandas as pd
from pathlib import Path

# 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
interim_dir = PROJECT_ROOT / 'data' / 'interim'
interim_files = sorted(interim_dir.glob('sdot_*.csv'))

print("🔍 [ 중간 산출물 무결성 검증 시작 (메모리 최적화 청크 모드) ]\n")

string_cols = ['measure_time', 'sensor_id']

for file in interim_files:
    print(f"📄 검사 중: {file.name} ... ", end="", flush=True)
    
    try:
        # 1. 컬럼 무결성 검증 (맨 앞 10줄만 빠르게 읽기)
        df_sample = pd.read_csv(file, nrows=10)
        col_count = len(df_sample.columns)
        if col_count != 128:
            print(f"❌ [FAIL] 컬럼 수 불일치! (현재 {col_count}개)")
            continue
            
        # 2. 데이터 타입 & Flag 값 검증 (10만 줄씩 잘라서 검사)
        flag_cols = [c for c in df_sample.columns if c.startswith('flag_')]
        numeric_fail = False
        flag_fail = False
        
        # chunksize 적용: 한 번에 10만 행씩 메모리에 올려서 검사 후 삭제 (메모리 낭비 제로)
        for chunk in pd.read_csv(file, chunksize=100000, low_memory=True):
            
            # 숫자형 검증 (문자열이 섞여서 object 타입으로 읽힌 컬럼이 있는지 확인)
            for col in chunk.columns:
                if col not in string_cols:
                    if chunk[col].dtype == 'object':
                        numeric_fail = True
                        break
                        
            # Flag 검증 (0과 1이 아닌 값이 들어있는지 확인)
            for f_col in flag_cols:
                unique_vals = chunk[f_col].dropna().unique()
                if not set(unique_vals).issubset({0, 1, 0.0, 1.0}):
                    flag_fail = True
                    break
                    
            # 하나라도 에러가 발견되면 즉시 해당 파일 검사 중단
            if numeric_fail or flag_fail:
                break
                
        if numeric_fail:
            print("❌ [FAIL] 숫자가 아닌 데이터가 포함된 컬럼 발견")
        elif flag_fail:
            print("❌ [FAIL] 0과 1이 아닌 이상한 Flag 값 발견")
        else:
            print("✅ [ALL PASS] 완벽합니다!")
            
    except Exception as e:
        print(f"❌ [에러 발생] {e}")

print("\n🎉 모든 파일 검증 완료!")
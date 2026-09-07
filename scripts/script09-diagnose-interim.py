import pandas as pd
from pathlib import Path
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
interim_files = sorted((PROJECT_ROOT / 'data' / 'interim').glob('sdot_*.csv'))

print("🔍 [진단 시작] interim 폴더의 전체 데이터를 끝까지 정밀 스캔합니다...\n")
start_time = time.time()

for file in interim_files:
    print(f"▶️ 검사 중: {file.name} ... ", end="", flush=True)
    has_error = False
    
    # break 없이 파일 끝까지 스캔! (속도를 위해 청크 크기를 늘림)
    for chunk in pd.read_csv(file, chunksize=500000, low_memory=False, dtype=str):
        if 'measure_time' in chunk.columns:
            # 1. 지수 표기법(E+) 깨짐 확인
            if chunk['measure_time'].str.contains('E\+', na=False).any():
                has_error = True
                print("\n ❌ [오류 발견] 지수 표기법(E+)으로 깨진 데이터가 있습니다!")
                break # 이 파일이 불량인 걸 알았으니 다음 파일로 넘어감
                
            # 2. 헤더 찌꺼기 확인
            if chunk['measure_time'].str.contains('전송시간|측정일시', na=False).any():
                has_error = True
                print("\n ❌ [오류 발견] 중간에 헤더(컬럼명) 찌꺼기가 끼어 있습니다!")
                break
                
    if not has_error:
        print("✅ 이상 없음 (통과)")

print(f"\n✨ 정밀 진단 완료! (소요 시간: {round(time.time() - start_time, 1)}초)")
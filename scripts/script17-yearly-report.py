import pandas as pd
from pathlib import Path

interim_dir = Path(__file__).resolve().parent.parent / 'data' / 'interim'
parquet_files = sorted(interim_dir.glob('sdot_*.parquet'))

print("🔬 [V7 최종 Parquet 파일 정합성 검증 시작]\n")

total_rows = 0
total_eplus = 0
total_invalid = 0

for p_file in parquet_files:
    if "dropped" in p_file.name or "report" in p_file.name:
        continue  
        
    df = pd.read_parquet(p_file)
    row_count = len(df)
    total_rows += row_count
    
    print(f"--- 📁 {p_file.name} ---")
    print(f"  ▪️ 데이터 크기: {row_count:,}행")
    
    if 'measure_time' in df.columns:
        time_str = df['measure_time'].astype(str)
        
        # 1. 지수표기법(E+) 개수 확인
        e_plus_count = time_str.str.contains(r'E\+', case=False, na=False).sum()
        total_eplus += e_plus_count
        
        # 2. 가짜 시간(길이가 8 미만이고 E+도 아닌 것) 개수 확인
        invalid_mask = (time_str.str.len() < 8) & (~time_str.str.contains(r'E\+', case=False, na=False)) & (time_str != 'nan')
        invalid_count = invalid_mask.sum()
        total_invalid += invalid_count
        
        print(f"  ▪️ 복구 대기 중인 지수표기법(E+) 데이터: {e_plus_count:,}건")
        
        if invalid_count > 0:
            print(f"  🚨 치명적 오류: 가짜 시간 데이터(온도 등)가 {invalid_count:,}건 살아있습니다!")
            print(f"     예시: {time_str[invalid_mask].head(3).tolist()}")
        else:
            print("  ✅ 가짜 시간 데이터 완벽 멸종 (0건)")
            
        # 3. 시간 샘플 출력
        valid_times = time_str[(~invalid_mask) & (time_str != 'nan')]
        if not valid_times.empty:
            print(f"  ▪️ 시간 샘플(최근 3건): {valid_times.tail(3).tolist()}\n")

print("=========================================")
print(f"🎉 전 연도 통합 총 데이터 건수: {total_rows:,}행")
print(f"📌 총 복구 대기 E+ 데이터: {total_eplus:,}건")
print(f"🛡️ 총 발견된 가짜 시간 데이터: {total_invalid:,}건")
print("=========================================")
import pandas as pd
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
excel_path = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'

df_inv = pd.read_excel(excel_path, sheet_name='FileInventory')
df_mapping = pd.read_excel(excel_path, sheet_name='ColumnMapping')

# 문제가 발생했던 2020~2024년 전체 타겟팅
target_years = [2020, 2021, 2022, 2023, 2024]
total_dropped = 0
dropped_counter = Counter()

print("🔍 [ 전체 불량 데이터 정밀 전수조사 시작 (2020~2024) ]")

for year in target_years:
    year_files = df_inv[df_inv['year'] == year]
    print(f"\n▶️ {year}년 데이터 스캔 시작 (총 {len(year_files)}개 파일)...")
    
    for idx, row in year_files.iterrows():
        version = row['schema_version']
        
        # 파일 경로 찾기
        found_files = list(PROJECT_ROOT.rglob(row['file_name']))
        if not found_files:
            continue
        file_path = found_files[0]
        
        # 매핑 딕셔너리 생성
        col_map = {}
        for _, r in df_mapping.iterrows():
            raw_cols = r[version]
            if pd.notna(raw_cols):
                for raw_col in str(raw_cols).split(','):
                    col_map[raw_col.strip()] = r['master_column']
        
        # 원본 파일 읽기
        try:
            df = pd.read_csv(file_path, encoding='utf-8', low_memory=False, dtype=str, on_bad_lines='skip')
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding='cp949', low_memory=False, dtype=str, on_bad_lines='skip')
            
        df = df.rename(columns={col: col_map[col.strip()] for col in df.columns if col.strip() in col_map})
        
        if 'measure_time' in df.columns:
            # V6 필터링 조건
            cond_no_digits = ~df['measure_time'].astype(str).str.contains(r'\d', na=False)
            cond_e_plus = df['measure_time'].astype(str).str.contains(r'E\+', case=False, na=False)
            
            dropped = df[cond_no_digits | cond_e_plus]
            total_dropped += len(dropped)
            
            # 어떤 값들이 삭제되었는지 카운트 누적 (NaN은 문자로 변환하여 집계)
            dropped_values = dropped['measure_time'].fillna('NaN').astype(str)
            dropped_counter.update(dropped_values.tolist())

print("\n" + "="*50)
print(f"🚨 [ 스캔 완료 ] 총 삭제된 데이터: {total_dropped:,}행")
print("🗑️ [ 삭제된 데이터들의 measure_time 원본 값 형태 TOP 20 ]")
for val, count in dropped_counter.most_common(20):
    print(f" - {val}: {count:,}개")
print("="*50)
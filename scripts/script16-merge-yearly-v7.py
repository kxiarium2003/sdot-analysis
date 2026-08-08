"""
script16-merge-yearly-v7.py - 연도별 데이터 병합 스크립트
- 데이터 밀림(Shift) 현상 차단
- 지수표기법(E+) 손상 p데이터 복구
"""
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
excel_path = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'
interim_dir = PROJECT_ROOT / 'data' / 'interim'

interim_dir.mkdir(parents=True, exist_ok=True)

print("📂 엑셀 파일 로드 및 매핑 사전 구축 중...")
df_inv = pd.read_excel(excel_path, sheet_name='FileInventory')
df_mapping = pd.read_excel(excel_path, sheet_name='ColumnMapping')

master_columns = df_mapping['master_column'].dropna().tolist()
schema_versions = df_inv['schema_version'].dropna().unique()

rename_dicts = {}
for version in schema_versions:
    col_map = {}
    if version in df_mapping.columns:
        for _, row in df_mapping.iterrows():
            master_col = row['master_column']
            raw_cols = row[version]
            if pd.notna(raw_cols):
                for raw_col in str(raw_cols).split(','):
                    col_map[raw_col.strip()] = master_col
    rename_dicts[version] = col_map

flag_columns = [f"flag_{col}" for col in master_columns]
final_columns = master_columns + flag_columns

years = sorted(df_inv['year'].dropna().unique())

for year in years:
    year_files = df_inv[df_inv['year'] == year]
    print(f"\n🚀 [ {int(year)}년 데이터 병합 시작 ] - 대상 파일: {len(year_files)}개")
    
    df_list = []
    processed_count = 0
    
    for _, row in year_files.iterrows():
        file_name = row['file_name']
        version = row['schema_version']
        
        found_files = list(PROJECT_ROOT.rglob(file_name))
        if not found_files:
            continue
            
        file_path = found_files[0]
        
        try:
            try:
                df = pd.read_csv(file_path, encoding='utf-8', low_memory=False, index_col=False, on_bad_lines='skip', dtype=str)
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='cp949', low_memory=False, index_col=False, on_bad_lines='skip', dtype=str)
        except Exception:
            continue
            
        rename_map = rename_dicts.get(version, {})
        actual_rename = {col: rename_map[col.strip()] for col in df.columns if col.strip() in rename_map}
        df = df.rename(columns=actual_rename)
        
        if 'measure_time' in df.columns:
            corrupted_mask = df['measure_time'].astype(str).str.contains(r'E\+', case=False, na=False)
            if corrupted_mask.any():
                df.loc[corrupted_mask, 'measure_time'] = df.loc[corrupted_mask, df.columns[-1]]
                
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]
        
        cols_to_keep = [c for c in df.columns if c in master_columns]
        df = df[cols_to_keep]
        
        # 🚨 데이터가 왼쪽으로 밀린 행(측정시간에 온도가 들어간 경우) 색출 및 폐기
        if 'measure_time' in df.columns:
            measure_time_str = df['measure_time'].astype(str)
            valid_mask = (measure_time_str.str.len() >= 8) | measure_time_str.str.contains(r'E\+', case=False, na=False)
            df = df[valid_mask & (measure_time_str != 'nan')]
        
        string_cols = ['measure_time', 'sensor_id']
        for col in df.columns:
            if col not in string_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        supported_masters = set(rename_map.values())
        flag_dict = {f"flag_{m_col}": (1 if m_col in supported_masters else 0) for m_col in master_columns}
        df = df.assign(**flag_dict)
                
        df_list.append(df)
        processed_count += 1
        
        if processed_count % 10 == 0:
            print(f"  ... {processed_count}/{len(year_files)}개 파일 처리 완료")
            
    if df_list:
        print(f"  🔄 {int(year)}년 데이터 결합 중 (Concat)...")
        df_year = pd.concat(df_list, ignore_index=True)
        df_year = df_year.reindex(columns=final_columns)
        
        output_path = interim_dir / f'sdot_{int(year)}.parquet'
        print(f"  💾 저장 중... {output_path.name}")
        df_year.to_parquet(output_path, engine='pyarrow', index=False)
        print(f"  ✅ {int(year)}년 병합 완료! (총 {len(df_year):,}행)")

print(f"\n🎉 모든 데이터 무결점 병합 완료!")
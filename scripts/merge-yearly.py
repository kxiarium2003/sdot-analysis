'''
merge-yearly.py - 연도별 데이터 병합 스크립트 V4

'''
import pandas as pd
from pathlib import Path

# 1. 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
excel_path = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'
interim_dir = PROJECT_ROOT / 'data' / 'interim'

interim_dir.mkdir(parents=True, exist_ok=True)

print("📂 엑셀 파일 로드 및 매핑 사전 구축 중...")
df_inv = pd.read_excel(excel_path, sheet_name='FileInventory')
df_mapping = pd.read_excel(excel_path, sheet_name='ColumnMapping')

master_columns = df_mapping['master_column'].dropna().tolist()
schema_versions = df_inv['schema_version'].dropna().unique()

# 2. 스키마 버전별 매핑 딕셔너리 구축
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

# 3. 연도별 병합 실행 
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
                df = pd.read_csv(file_path, encoding='utf-8', low_memory=False, index_col=False, on_bad_lines='skip')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='cp949', low_memory=False, index_col=False, on_bad_lines='skip')
        except Exception as e:
            print(f"  ❌ 읽기 실패 ({file_name}): {e}")
            continue
            
        # 4. 컬럼명 변환 (Rename) 및 필터링
        rename_map = rename_dicts.get(version, {})
        actual_rename = {col: rename_map[col.strip()] for col in df.columns if col.strip() in rename_map}
        df = df.rename(columns=actual_rename)
        
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]
        
        cols_to_keep = [c for c in df.columns if c in master_columns]
        df = df[cols_to_keep]
        
        # 🚨 센서 측정값 강제 숫자 변환 (문자열 메타데이터 컬럼 제외)
        string_cols = ['measure_time', 'sensor_id']
        
        for col in df.columns:
            if col not in string_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 🚨 구조적 결측치 0/1 Flag 라벨 한 번에 생성 (Warning 방지)
        supported_masters = set(rename_map.values())
        flag_dict = {f"flag_{m_col}": (1 if m_col in supported_masters else 0) for m_col in master_columns}
        df = df.assign(**flag_dict)
                
        df_list.append(df)
        processed_count += 1
        
        if processed_count % 10 == 0:
            print(f"  ... {processed_count}/{len(year_files)}개 파일 처리 완료")
            
    print(f"  ... 최종 {processed_count}/{len(year_files)}개 파일 읽기 완료!")    
            
    # 5. 연도별 데이터 세로 병합 (Concat)
    if df_list:
        print(f"  🔄 {int(year)}년 데이터 결합 중 (Concat)...")
        df_year = pd.concat(df_list, ignore_index=True)
        
        df_year = df_year.reindex(columns=final_columns)
        
        output_path = interim_dir / f'sdot_{int(year)}.csv'
        print(f"  💾 저장 중... {output_path.name}")
        df_year.to_csv(output_path, index=False, encoding='utf-8')
        
        print(f"  ✅ {int(year)}년 병합 완료! (총 {len(df_year):,}행, {len(df_year.columns)}열)")
    else:
        print(f"  ⚠️ {int(year)}년에 병합할 수 있는 유효한 파일이 없습니다.")

print(f"\n🎉 모든 연도별({int(years[0])}~{int(years[-1])}) 데이터 병합 및 정제가 성공적으로 완료되었습니다! interim 폴더에서 결과를 확인해 보세요.")
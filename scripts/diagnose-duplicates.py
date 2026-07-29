import pandas as pd
from pathlib import Path
import collections

# 1. 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
excel_path = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'

print("🔍 전체 연도 데이터 중복 컬럼 원인 분석 시작...\n")

df_inv = pd.read_excel(excel_path, sheet_name='FileInventory')
df_mapping = pd.read_excel(excel_path, sheet_name='ColumnMapping')

# 매핑 사전 구축
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

found_issue = False
# 인벤토리에 존재하는 모든 연도를 가져옴
years = sorted(df_inv['year'].dropna().unique())

# 결과를 연도별로 예쁘게 출력하기 위한 딕셔너리
issues_by_year = collections.defaultdict(list)

for year in years:
    files_year = df_inv[df_inv['year'] == year]
    
    for _, row in files_year.iterrows():
        file_name = row['file_name']
        version = row['schema_version']
        
        found_files = list(PROJECT_ROOT.rglob(file_name))
        if not found_files:
            continue
            
        file_path = found_files[0]
        
        # 데이터 로드 (nrows=0으로 헤더만 빠르게 읽기)
        try:
            try:
                df = pd.read_csv(file_path, encoding='utf-8', nrows=0)
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='cp949', nrows=0)
        except Exception as e:
            continue
            
        rename_map = rename_dicts.get(version, {})
        raw_columns = list(df.columns)
        
        # 원본 컬럼들이 마스터 컬럼으로 어떻게 매핑되는지 확인
        mapped_columns = [rename_map.get(c.strip(), c.strip()) for c in raw_columns]
        
        # 매핑된 후의 컬럼 중 중복이 있는지 카운트
        mapped_dupes = [item for item, count in collections.Counter(mapped_columns).items() if count > 1]
        
        if mapped_dupes:
            for dup_master in mapped_dupes:
                # 어떤 원본 컬럼들이 이 중복된 마스터 컬럼을 만들었는지 역추적
                culprits = [raw for raw, mapped in zip(raw_columns, mapped_columns) if mapped == dup_master]
                
                issues_by_year[year].append({
                    'file_name': file_name,
                    'master_col': dup_master,
                    'culprits': culprits
                })

# 3. 결과 종합 리포트 출력
for year in years:
    issues = issues_by_year.get(year, [])
    if not issues:
        continue
        
    print(f"📅 [ {int(year)}년 ] 중복 컬럼 이슈 발견 ({len(issues)}건)")
    found_issue = True
    for issue in issues:
        print(f"  - 파일명: {issue['file_name']}")
        print(f"    ↳ 마스터 컬럼 '{issue['master_col']}'(으)로 겹침: {issue['culprits']}\n")

if not found_issue:
    print("✅ 모든 연도(전체 파일)에서 중복 문제를 찾지 못했습니다! 완벽합니다.")
else:
    print("💡 위 결과를 확인하여 매핑 시트를 수정하거나 원본 데이터를 전처리해야 합니다.")
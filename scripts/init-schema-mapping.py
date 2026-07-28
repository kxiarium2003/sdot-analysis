import pandas as pd

# 기존 인벤토리에서 생성된 유니크한 스키마 버전 목록 가져오기
df_inv = pd.read_excel('metadata/sdot-schema-mapping.xlsx', sheet_name='FileInventory')
schema_versions = sorted(df_inv['schema_version'].dropna().unique())

# 마스터 스키마 기본 구조 정의
master_columns = [
    'measure_time', 'sensor_id', 'temp_avg', 'temp_max', 'temp_min',
    'humi_avg', 'humi_max', 'humi_min', 'pm10', 'pm25'
]

# 빈 데이터프레임 생성
df_mapping = pd.DataFrame({'master_column': master_columns})
df_mapping['dtype'] = ['datetime64[ns]', 'str'] + ['float64'] * (len(master_columns) - 2)
df_mapping['description'] = ''

# 각 스키마 버전별 빈 열 추가
for version in schema_versions:
    df_mapping[version] = None

# 새 시트로 엑셀에 추가 저장
with pd.ExcelWriter('metadata/sdot-schema-mapping.xlsx', mode='a', engine='openpyxl') as writer:
    df_mapping.to_excel(writer, sheet_name='ColumnMapping', index=False)
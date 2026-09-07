import pandas as pd
from pathlib import Path

# 1. 절대 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
excel_path = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'

print(f"📂 엑셀 파일 로드 중... ({excel_path.name})")

# 2. 인벤토리에서 데이터 불러오기
df_inv = pd.read_excel(excel_path, sheet_name='FileInventory')
schema_versions = sorted(df_inv['schema_version'].dropna().unique())

# ==========================================
# [기능 1] 스키마 버전별 샘플 파일 컬럼명 추출
# ==========================================
sample_files = df_inv.groupby('schema_version').first().reset_index()

print("\n🔍 [스키마 버전별 원본 컬럼명 추출 결과]")
for idx, row in sample_files.iterrows():
    version = row['schema_version']
    # 엑셀에 저장된 경로가 상대경로일 수 있으므로 PROJECT_ROOT와 결합
    file_name = row['file_name']
    
    # 프로젝트 전체(PROJECT_ROOT)를 뒤져서 해당 파일 이름과 똑같은 것을 모두 찾음
    found_files = list(PROJECT_ROOT.rglob(file_name))
    
    if found_files:
        # 파일을 찾았다면 첫 번째로 발견된 경로를 사용
        file_path = found_files[0]
    else:
        # 프로젝트 내에 파일이 아예 없다면 에러 발생
        raise FileNotFoundError(f"프로젝트 폴더 내에서 {file_name} 파일을 찾을 수 없습니다! 파일이 프로젝트 폴더 안에 있는지 확인해 주세요.")
    
    try:
        # csv 원본 파일의 헤더(첫 줄)만 빠르게 읽기 (utf-8 시도 후 실패하면 cp949 시도)
        try:
            df_sample = pd.read_csv(file_path, nrows=0, encoding='utf-8')
        except UnicodeDecodeError:
            df_sample = pd.read_csv(file_path, nrows=0, encoding='cp949')
            
        columns = df_sample.columns.tolist()
        print(f"📌 {version} (샘플: {file_path.name})")
        print(f"   -> {columns}\n")
    except Exception as e:
        print(f"❌ {version} 파일 읽기 실패: {e}\n")


# ==========================================
# [기능 2] 확장판 마스터 컬럼으로 매핑 시트 생성
# ==========================================
# S-DoT 2024 스키마 구조를 모두 반영한 확장판 마스터 컬럼
master_columns = [
    'measure_time', 'sensor_id',
    
    # 기상/환경 기본 (최대/평균/최소)
    'temp_max', 'temp_avg', 'temp_min',          # 온도
    'humi_max', 'humi_avg', 'humi_min',          # 습도
    'wind_spd_max', 'wind_spd_avg', 'wind_spd_min', # 풍속
    'wind_dir_max', 'wind_dir_avg', 'wind_dir_min', # 풍향
    'illu_max', 'illu_avg', 'illu_min',          # 조도
    'uv_max', 'uv_avg', 'uv_min',                # 자외선
    'noise_max', 'noise_avg', 'noise_min',       # 소음
    
    # 진동 가속도 (g) (x/y/z 각각 최대/평균/최소) - 2020년 스키마 등
    'vibe_x_max_g', 'vibe_x_avg_g', 'vibe_x_min_g',
    'vibe_y_max_g', 'vibe_y_avg_g', 'vibe_y_min_g',
    'vibe_z_max_g', 'vibe_z_avg_g', 'vibe_z_min_g',
    
    # 진동 속도 (mm/s) (x/y/z 각각 최대/평균/최소) - 2023년 스키마 등
    'vibe_x_max_mms', 'vibe_x_avg_mms', 'vibe_x_min_mms',
    'vibe_y_max_mms', 'vibe_y_avg_mms', 'vibe_y_min_mms',
    'vibe_z_max_mms', 'vibe_z_avg_mms', 'vibe_z_min_mms',
    
    # 가스 및 기타 (최대/평균/최소)
    'wbgt_max', 'wbgt_avg', 'wbgt_min',          # 흑구온도
    'no2_max', 'no2_avg', 'no2_min',             # 이산화질소
    'co_max', 'co_avg', 'co_min',                # 일산화탄소
    'so2_max', 'so2_avg', 'so2_min',             # 이산화황
    'nh3_max', 'nh3_avg', 'nh3_min',             # 암모니아
    'h2s_max', 'h2s_avg', 'h2s_min',             # 황화수소
    'o3_max', 'o3_avg', 'o3_min',                # 오존
    
    # 미세먼지 (보통 단일 값이지만, 만약 최대/평균/최소가 있다면 추가 필요)
    'pm10', 'pm25'
]

# 빈 데이터프레임 생성
df_mapping = pd.DataFrame({'master_column': master_columns})

# 데이터 타입 리스트 동적 생성 (처음 2개는 시간/문자열, 나머지는 실수형)
dtypes = ['datetime64[ns]', 'object'] + ['float64'] * (len(master_columns) - 2)
df_mapping['dtype'] = dtypes
df_mapping['description'] = ''

# 각 스키마 버전별 빈 열 추가
for version in schema_versions:
    df_mapping[version] = None

# 새 시트로 엑셀에 추가 저장 (안전하게 덮어쓰기)
print("💾 ColumnMapping 시트 저장 중...")
with pd.ExcelWriter(excel_path, mode='a', engine='openpyxl', if_sheet_exists='replace') as writer:
    df_mapping.to_excel(writer, sheet_name='ColumnMapping', index=False)
    
print("🎉 완벽합니다! 원본 컬럼명 확인 및 ColumnMapping 시트 생성이 완료되었습니다.")
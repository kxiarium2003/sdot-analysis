'''
auto-fill-mapping.py - 자동 매핑 스크립트 V3

'''

import pandas as pd
from pathlib import Path
import numpy as np

# 1. 경로 설정 및 파일 로드
PROJECT_ROOT = Path(__file__).resolve().parent.parent
excel_path = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'

print(f"📂 엑셀 파일 로드 중... ({excel_path.name})")

df_inv = pd.read_excel(excel_path, sheet_name='FileInventory')
df_mapping = pd.read_excel(excel_path, sheet_name='ColumnMapping')

df_mapping.set_index('master_column', inplace=True)

# 💡 이전 매핑 기록 깔끔하게 초기화
schema_versions = df_inv['schema_version'].dropna().unique()
for version in schema_versions:
    if version in df_mapping.columns:
        df_mapping[version] = np.nan
        df_mapping[version] = df_mapping[version].astype('object')

# 2. 스마트 매핑 함수 (예외 처리 및 중복 방지 강화)
def find_master_column(raw_col):
    norm = raw_col.replace(" ", "").replace("_", "").lower()
    
    # 🚫 명시적으로 무시할 컬럼들 (마스터 스키마에 없음)
    ignore_keywords = ['기관', '모델', '구분', '등록', 'unnamed']
    if any(ignore_kw in norm for ignore_kw in ignore_keywords):
        return None
        
    # 시간 및 ID (등록일자는 위에서 걸러지므로 안전하게 측정/전송시간만 매핑됨)
    if '전송시간' in norm or '측정시간' in norm: return 'measure_time'
    if '시리얼' in norm: return 'sensor_id'
    # 돌풍 데이터는 '최대 풍속/풍향'으로 매핑
    if '돌풍' in norm:
        if '풍속' in norm: return 'wind_spd_max'
        if '풍향' in norm: return 'wind_dir_max'
    
    # 진동
    if '진동' in norm:
        axis = 'x' if 'x' in norm else 'y' if 'y' in norm else 'z' if 'z' in norm else None
        if not axis: return None
        
        stat = 'max' if '최대' in norm else 'min' if '최소' in norm else 'avg'
        unit = 'mms' if 'mm' in norm else 'g'
        return f"vibe_{axis}_{stat}_{unit}"
        
    # 기상, 가스 및 환경 데이터
    metrics_map = {
        '흑구': 'wbgt',
        '초미세먼지': 'pm25', '미세먼지': 'pm10',
        '기온': 'temp', '온도': 'temp', '습도': 'humi',
        '풍속': 'wind_spd', '풍향': 'wind_dir',
        '조도': 'illu', '자외선': 'uv', '소음': 'noise',
        '이산화질소': 'no2', '일산화탄소': 'co',
        '이산화황': 'so2', '암모니아': 'nh3', '황화수소': 'h2s', '오존': 'o3'
    }
    
    for kor_key, eng_key in metrics_map.items():
        if kor_key in norm:
            if eng_key in ['pm10', 'pm25']:
                return eng_key # 미세먼지는 max/avg 없이 단일 컬럼
                
            stat = 'max' if '최대' in norm else 'min' if '최소' in norm else 'avg'
            return f"{eng_key}_{stat}"
            
    return None

# 3. 매핑 실행
print("\n🤖 [자동 매핑 알고리즘 가동 - 전체 파일 스캔]")

for version in schema_versions:
    if version not in df_mapping.columns:
        continue
        
    version_files = df_inv[df_inv['schema_version'] == version]
    
    unique_columns = set()
    for col_list_str in version_files['all_columns_list'].dropna():
        cols = [c.strip() for c in str(col_list_str).split(',')]
        unique_columns.update(cols)
        
    mapped_count = 0
    ignored_cols = []
    
    for col in unique_columns:
        target_master = find_master_column(col)
        
        if target_master and target_master in df_mapping.index:
            existing_val = df_mapping.at[target_master, version]
            
            # 같은 마스터 컬럼에 이미 값이 있다면 콤마로 추가, 아니면 새로 할당
            if pd.isna(existing_val):
                df_mapping.at[target_master, version] = col
            else:
                if col not in str(existing_val).split(', '):
                    df_mapping.at[target_master, version] = f"{existing_val}, {col}"
            mapped_count += 1
        else:
            ignored_cols.append(col)
            
    print(f"✅ {version}: {len(unique_columns)}개 중 {mapped_count}개 매핑 완료")
    print(f"   ↳ 의도적 무시(또는 미매핑) 항목: {', '.join(ignored_cols[:5])} 등 {len(ignored_cols)}개\n")

# 4. 결과 저장
df_mapping.reset_index(inplace=True)

print("💾 결과를 엑셀 파일에 저장 중...")
with pd.ExcelWriter(excel_path, mode='a', engine='openpyxl', if_sheet_exists='replace') as writer:
    df_mapping.to_excel(writer, sheet_name='ColumnMapping', index=False)
    
print("🎉 완벽한 자동화 완료! 불필요한 '등록일자' 등은 제외되고, 필수 컬럼만 깨끗하게 매핑되었습니다.")
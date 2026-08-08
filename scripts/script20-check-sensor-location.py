import pandas as pd
from pathlib import Path

# 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
processed_dir = PROJECT_ROOT / 'data' / 'processed'
metadata_dir = PROJECT_ROOT / 'metadata'

master_file = processed_dir / 'sdot_master_2020_2026_geocoded.parquet'
meta_file = metadata_dir / '서울시 도시데이터 센서(S-DoT) 환경정보 설치 위치정보.xlsx'

print("--- [ 미매핑 센서 전수 검증 시작 ] ---\n")

# 1. 파케이에서 데이터 로드
df_check = pd.read_parquet(master_file, columns=['sensor_id', 'latitude'])
df_missing = df_check[df_check['latitude'].isna()]

if df_missing.empty:
    print("결과: 위치 정보가 누락된 데이터가 없습니다.")
else:
    missing_counts = df_missing['sensor_id'].value_counts()
    total_missing_sensors = len(missing_counts)
    
    print(f"미매핑된 고유 센서 ID 수: {total_missing_sensors}개\n")
    print("[ 메타데이터 교차 검증 진행 중... ]")
    
    # 2. 메타데이터 로드 및 비교용 Set 생성
    df_meta = pd.read_excel(meta_file)
    meta_sensors = set(df_meta['모델 시리얼(*)'].astype(str).tolist())
    meta_sensors_clean = set(s.strip().replace(" ", "") for s in meta_sensors)
    
    # 3. 분류용 리스트 초기화
    found_exact = []
    found_whitespace = []
    not_found = []
    
    # 4. 전체 누락 센서 검사
    for sensor in missing_counts.index:
        sensor_str = str(sensor)
        
        if sensor_str in meta_sensors:
            found_exact.append(sensor_str)
        elif sensor_str.replace(" ", "") in meta_sensors_clean:
            found_whitespace.append(sensor_str)
        else:
            not_found.append(sensor_str)
            
    # 5. 결과 출력
    print("\n[ 검증 결과 요약 ]")
    print(f"1. 메타데이터에 정확히 존재함 (로직 검토 필요): {len(found_exact)}개")
    if found_exact:
        print(f"   -> {found_exact}")
        
    print(f"\n2. 메타데이터에 존재하나 포맷 차이(공백 등)로 매핑 실패: {len(found_whitespace)}개")
    if found_whitespace:
        print(f"   -> {found_whitespace}")
        
    print(f"\n3. 메타데이터에 존재하지 않음 (원천 데이터 누락 확인): {len(not_found)}개")
    if not_found:
        print("   -> 누락 센서 목록:")
        # 5개씩 줄바꿈하여 출력
        for i in range(0, len(not_found), 5):
            print(f"      {', '.join(not_found[i:i+5])}")
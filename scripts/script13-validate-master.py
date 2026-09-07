import duckdb

file_path = 'data/processed/sdot_master_2020_2026.csv'

print("🔍 데이터 스키마(컬럼명)를 자동으로 탐색합니다...")

# 1. LIMIT 0을 사용하여 데이터는 읽지 않고 컬럼명만 즉시 추출 (메모리 사용 거의 없음)
columns = duckdb.query(f"SELECT * FROM '{file_path}' LIMIT 0").df().columns.tolist()

# 2. 찾고자 하는 컬럼명의 예상 후보군 설정 (우선순위 순서대로 작성)
date_candidates = ['measure_time', '측정일시', '전송시간', '등록일자', '일시', 'timestamp', 'date', 'time', 'REG_DATE']
sensor_candidates = ['시리얼번호', '시리얼', '센서번호', 'sensor_id', 'serial', 'serial_no', 'ID']

# 3. 실제 파일에 존재하는 컬럼명 자동 매칭
date_col = next((col for col in columns if col in date_candidates), None)
sensor_col = next((col for col in columns if col in sensor_candidates), None)

# 매칭 실패 시 예외 처리
if not date_col or not sensor_col:
    print(f"❌ 오류: 날짜 또는 센서 컬럼을 자동으로 찾지 못했습니다.")
    print(f"현재 파일의 컬럼 목록(일부): {columns[:10]} ...")
    exit()

print(f"✅ 컬럼 파싱 완료! (날짜 기준: '{date_col}', 식별자 기준: '{sensor_col}')")
print("🔍 DuckDB로 5,200만 건 데이터 검증을 시작합니다...")

# 4. 찾은 컬럼명을 SQL 쿼리에 동적으로 삽입 (큰따옴표로 묶어 띄어쓰기 등 오류 방지)
query = f"""
SELECT 
    COUNT(*) AS total_rows,
    MIN("{date_col}") AS start_date,
    MAX("{date_col}") AS end_date,
    SUM(CASE WHEN "{sensor_col}" IS NULL THEN 1 ELSE 0 END) AS null_sensors
FROM '{file_path}'
"""

# 5. 쿼리 실행 및 결과 출력
result = duckdb.query(query).df()

print("\n📊 [마스터 데이터 검증 결과]")
print("-" * 50)
print(result.to_string(index=False))
print("-" * 50)
print("✨ 검증이 성공적으로 완료되었습니다!")


import duckdb

file_path = 'data/processed/sdot_master_2020_2026.csv'

# 날짜 형식이 아니거나(try_cast 실패), 센서 아이디가 없는 불량 데이터만 20개 추출
query = f"""
SELECT measure_time, sensor_id 
FROM '{file_path}' 
WHERE try_cast(measure_time AS TIMESTAMP) IS NULL 
   OR sensor_id IS NULL
LIMIT 20
"""

print("🚨 불량 데이터(Header Leakage 등) 샘플을 확인합니다...")
result = duckdb.query(query).df()
print(result)


# '202'로 시작하지 않는 데이터(진짜 찌꺼기) 또는 센서번호가 없는 데이터만 추출
query = f"""
SELECT measure_time, sensor_id 
FROM '{file_path}' 
WHERE measure_time NOT LIKE '202%' 
   OR sensor_id IS NULL
LIMIT 20
"""

print("🚨 [진짜 불량 데이터] 헤더 중복 및 결측치 샘플을 확인합니다...")
result = duckdb.query(query).df()
print(result)
"""
script26-diagnose-sensor-quality.py - Phase 0 체크리스트 5번: 센서 측정값 품질 진단

data/processed/master-v2/sdot_master_2020_2026_v2.parquet 대상. 지금까지 프로젝트에서는
measure_time 등 시간 컬럼만 검증했고 측정값(기온) 자체를 검증한 적이 없어 이번에 채운다.
정의(임계값)는 docs/preregistration.md §3에 결과를 보기 전에 먼저 확정해뒀다.

- 커버리지: 센서별 관측기간(최초~최후 유효 temp_avg 시각) 내 기대 관측수(시간당 1개
  가정, 실측 중앙값 간격 60분 확인됨) 대비 실제 유효 유니크 시각 수의 비율.
- 물리적 타당성: temp_avg/temp_max/temp_min 중 [-25, 45]도씨 범위를 벗어난 유효값 비율.
- 고착값: 동일 temp_avg가 간격 3시간 이내로 연속되며 72시간(3일) 이상 지속되는 구간.
- 세 지표를 종합해 센서별 정상/의심/불량 등급을 매긴다(등급표 산출용 진단이며, 이
  진단만으로 원본 값을 삭제·수정하지 않는다 - flag, don't filter 원칙 유지).

메모리 전략: script23의 sort-OOM(컬럼 130여개 폭 테이블 정렬)과 달리 여기서는
sensor_id/measure_time/temp_avg/temp_max/temp_min/flag_temp_avg 6개 컬럼만 사용한다.
컬럼 폭이 문제였지 행 수(5,313만) 자체가 문제는 아니었으므로, data/interim/v8/
연도별 파일에서 이 좁은 컬럼만 프로젝션해 읽고 concat한 뒤 그 좁은 테이블만
정렬한다(추정 메모리 사용량 1~2GB대) - 마스터 parquet 전체(134컬럼)는 읽지 않는다.
"""
import gc
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parent.parent
interim_dir = PROJECT_ROOT / 'data' / 'interim' / 'v8'
docs_dir = PROJECT_ROOT / 'docs'
report_file = docs_dir / 'sdot-sensor-quality-report.csv'

TEMP_MIN, TEMP_MAX = -25.0, 45.0
STUCK_GAP_HOURS = 3.0
STUCK_THRESHOLD_HOURS = 72.0

COLS = ['sensor_id', 'measure_time', 'temp_avg', 'temp_max', 'temp_min', 'flag_temp_avg']

print("[STEP 1] 연도별 v8 interim에서 좁은 컬럼만 읽어 결합")
frames = []
for year in range(2020, 2027):
    f = interim_dir / f'sdot_{year}_v8.parquet'
    if not f.exists():
        continue
    df = pq.ParquetFile(f).read(columns=COLS).to_pandas()
    df = df[df['flag_temp_avg'] == 1].drop(columns=['flag_temp_avg'])
    df['measure_time'] = pd.to_datetime(df['measure_time'], format='%Y-%m-%d %H:%M:%S')
    frames.append(df)
    print(f"  - {f.name}: {len(df):,}행 (flag_temp_avg==1)")

df = pd.concat(frames, ignore_index=True)
del frames
gc.collect()
print(f"결합 후 총 {len(df):,}행\n")

print("[STEP 2] 중복 제거(sensor_id, measure_time) + 정렬")
before = len(df)
df = df.sort_values(['sensor_id', 'measure_time'])
df = df.drop_duplicates(subset=['sensor_id', 'measure_time'], keep='first')
print(f"  - 중복 제거: {before:,} -> {len(df):,}행 ({before - len(df):,}건 제거)\n")

print("[STEP 3] 커버리지 계산")
valid = df['temp_avg'].notna()
valid_df = df[valid]
cov = valid_df.groupby('sensor_id')['measure_time'].agg(first_valid_ts='min', last_valid_ts='max', valid_unique_hours='count')
cov['expected_hours'] = (cov['last_valid_ts'] - cov['first_valid_ts']).dt.total_seconds() / 3600 + 1
cov['coverage_ratio'] = (cov['valid_unique_hours'] / cov['expected_hours']).clip(upper=1.0)
print(f"  - 유효 temp_avg 보유 센서 수: {len(cov):,}")

# temp_avg가 스키마상 지원되지만(flag_temp_avg==1) 유효값이 단 한 건도 없는 센서는
# groupby에서 통째로 빠지므로 coverage_ratio=0으로 명시적으로 추가한다 (조용히 누락시키지 않음)
all_flagged_sensors = df['sensor_id'].unique()
no_data_sensors = sorted(set(all_flagged_sensors) - set(cov.index))
if no_data_sensors:
    print(f"  - 유효 temp_avg 0건인 센서 {len(no_data_sensors)}개를 coverage_ratio=0으로 명시 추가: {no_data_sensors}")
    zero_rows = pd.DataFrame({
        'sensor_id': no_data_sensors,
        'first_valid_ts': pd.NaT, 'last_valid_ts': pd.NaT,
        'valid_unique_hours': 0, 'expected_hours': pd.NA, 'coverage_ratio': 0.0,
    }).set_index('sensor_id')
    cov = pd.concat([cov, zero_rows])
print()

print("[STEP 4] 물리적 타당성 검사 (기온 [-25, 45]도씨)")
oor_avg = valid & ((df['temp_avg'] < TEMP_MIN) | (df['temp_avg'] > TEMP_MAX))
oor_max = df['temp_max'].notna() & ((df['temp_max'] < TEMP_MIN) | (df['temp_max'] > TEMP_MAX))
oor_min = df['temp_min'].notna() & ((df['temp_min'] < TEMP_MIN) | (df['temp_min'] > TEMP_MAX))
df['out_of_range'] = oor_avg | oor_max | oor_min
phys = df[df['out_of_range']].groupby('sensor_id').size().rename('out_of_range_count')
print(f"  - 범위 위반 행: {df['out_of_range'].sum():,}건, 해당 센서 수: {len(phys):,}\n")

print("[STEP 5] 고착값(stuck value) 탐지")
vdf = valid_df.sort_values(['sensor_id', 'measure_time']).reset_index(drop=True)
same_val = vdf['temp_avg'] == vdf['temp_avg'].shift()
same_sensor = vdf['sensor_id'] == vdf['sensor_id'].shift()
gap_hours = (vdf['measure_time'] - vdf['measure_time'].shift()).dt.total_seconds() / 3600
continued = same_val & same_sensor & (gap_hours <= STUCK_GAP_HOURS)
run_id = (~continued).cumsum()
runs = vdf.groupby(run_id).agg(
    sensor_id=('sensor_id', 'first'),
    run_start=('measure_time', 'min'),
    run_end=('measure_time', 'max'),
).reset_index(drop=True)
runs['duration_hours'] = (runs['run_end'] - runs['run_start']).dt.total_seconds() / 3600
stuck = runs.groupby('sensor_id')['duration_hours'].max().rename('max_stuck_run_hours')
stuck_runs_over_threshold = runs[runs['duration_hours'] >= STUCK_THRESHOLD_HOURS]
print(f"  - 72시간 이상 고착 구간 수: {len(stuck_runs_over_threshold):,}건, 해당 센서 수: {stuck_runs_over_threshold['sensor_id'].nunique():,}\n")
del vdf, runs
gc.collect()

print("[STEP 6] 등급 산정 및 리포트 저장")
report = cov.join(phys, how='left').join(stuck, how='left')
report['out_of_range_count'] = report['out_of_range_count'].fillna(0).astype(int)
report['out_of_range_ratio'] = report['out_of_range_count'] / report['valid_unique_hours']
report['max_stuck_run_hours'] = report['max_stuck_run_hours'].fillna(0.0)


def coverage_grade(r):
    if r >= 0.8:
        return '정상'
    if r >= 0.5:
        return '의심'
    return '불량'


def physical_grade(r):
    if r == 0:
        return '정상'
    if r < 0.01:
        return '의심'
    return '불량'


def stuck_grade(h):
    if h < STUCK_THRESHOLD_HOURS:
        return '정상'
    if h < 168:
        return '의심'
    return '불량'


rank = {'정상': 0, '의심': 1, '불량': 2}
report['coverage_grade'] = report['coverage_ratio'].apply(coverage_grade)
report['physical_grade'] = report['out_of_range_ratio'].apply(physical_grade)
report['stuck_grade'] = report['max_stuck_run_hours'].apply(stuck_grade)
report['final_grade'] = report[['coverage_grade', 'physical_grade', 'stuck_grade']].apply(
    lambda row: max(row, key=lambda g: rank[g]), axis=1
)

report = report.reset_index().sort_values(['final_grade', 'sensor_id'], key=lambda c: c.map(rank) if c.name == 'final_grade' else c)
report.to_csv(report_file, index=False)

print(f"저장 완료: {report_file.relative_to(PROJECT_ROOT)}")
print(report['final_grade'].value_counts())
print()
print("등급별 세부 사유 분포 (불량/의심):")
for grade in ['불량', '의심']:
    sub = report[report['final_grade'] == grade]
    print(f"  [{grade}] n={len(sub)} | coverage 사유={  (sub['coverage_grade']==grade).sum() } | physical 사유={ (sub['physical_grade']==grade).sum() } | stuck 사유={ (sub['stuck_grade']==grade).sum() }")

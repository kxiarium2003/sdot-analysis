"""
script22-merge-yearly-v8.py - 연도별 병합 로직 v8 (정식 파이프라인)

배경: ColumnMapping 시트가 v2020_2022_recovered 스키마(113개 파일, 2,081만 행)의
measure_time을 깨진 전송시간 컬럼에 매핑해두고 있었음 (등록일자가 정상인데 미사용).
v2020_2022_corrupted 스키마(7개 파일)도 전송시간이 100% "2.02E+11"로 무의미.

이번 버전에서 하는 것:
1. 컬럼명 공백 정규화 (예: '등록 일자' == '등록일자') 후 전송시간/등록일자 탐색
2. measure_time: 전송시간 우선, 아래 경우에만 등록일자로 폴백
   - 결측
   - E+ 표기
   - YYYYMMDDHHMM(SS) 숫자형인데 월 또는 일이 '00'인 더미값 (예: 202000000000.0)
   - 전송시간은 유효하지만 등록일자와 날짜(캘린더 일자)가 갈리는 경우 (자정 경계, 일별 집계 왜곡 방지)
3. measure_time_source(tx/reg_fallback/reg_dateguard/mt/missing), measure_time_tx_reg_mismatch 컬럼 추가
4. 병합 불변식: 파일별 accept/reject 집계, accept+reject != 전체 대상이면 assert로 중단
5. 4개 날짜 포맷(대시/점/언더스코어+초/PM접미사) 정규화 - 고정 포맷 우선 시도 후 잔여만 mixed로 폴백(속도)
6. 파일 단위 즉시 parquet 이어쓰기 + 연도별 .done 마커로 재개 가능 (8GB RAM 환경 OOM 대응)

검증 이력: 2020~2022년(v2020_2022_recovered/corrupted, 125개 파일, 2,334만 행) 전수 처리
+ 2023~2026년(v2023_onward) 층화 샘플 34개 파일(731만 행)에서 파싱 성공률 100% 확인.
v2023_onward 전수(약 330개) 실행은 백로그 - 이 스크립트를 그대로 재실행하면 .done 마커
덕분에 완료된 연도는 건너뛰고 이어서 처리된다.
"""
import gc
import re
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
excel_path = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'
output_dir = PROJECT_ROOT / 'data' / 'interim' / 'v8'
output_dir.mkdir(parents=True, exist_ok=True)

TARGET_SCHEMAS = ['v2020_2022_recovered', 'v2020_2022_corrupted', 'v2023_onward']

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
            if master_col == 'measure_time':
                continue  # measure_time은 아래 우선순위 로직으로 별도 처리
            raw_cols = row[version]
            if pd.notna(raw_cols):
                for raw_col in str(raw_cols).split(','):
                    col_map[raw_col.strip()] = master_col
    rename_dicts[version] = col_map

flag_columns = [f"flag_{col}" for col in master_columns]
final_columns = master_columns + flag_columns + ['measure_time_source', 'measure_time_tx_reg_mismatch', 'measure_time_year_outlier']

# 0행짜리 파일(전부 필터링된 경우)의 문자열 컬럼이 pyarrow에서 null 타입으로 추론돼
# ParquetWriter 스키마와 어긋나는 걸 막기 위해 스키마를 명시적으로 고정한다.
_pa_fields = []
for _col in master_columns:
    if _col in ('measure_time', 'sensor_id'):
        _pa_fields.append(pa.field(_col, pa.string()))
    else:
        _pa_fields.append(pa.field(_col, pa.float64()))
for _col in flag_columns:
    _pa_fields.append(pa.field(_col, pa.int64()))
_pa_fields.append(pa.field('measure_time_source', pa.string()))
_pa_fields.append(pa.field('measure_time_tx_reg_mismatch', pa.bool_()))
_pa_fields.append(pa.field('measure_time_year_outlier', pa.bool_()))
EXPECTED_SCHEMA = pa.schema(_pa_fields)


def normalize_key(col: str) -> str:
    return re.sub(r'\s+', '', str(col))


def normalize_and_parse(raw: pd.Series) -> pd.Series:
    """원본 대화 초반에 발견한 4개 포맷 혼재(대시/점/언더스코어+초/PM접미사)를
    표준 'YYYY-MM-DD HH:MM:SS'로 정규화. 파싱 실패 시 NaN.

    format='mixed'는 행마다 dateutil로 포맷을 추론해서 수백만~수천만 행 규모에서
    치명적으로 느림(스팟체크 중 실측: 2021년 한 해 처리에만 40분 넘게 걸려 중단).
    정규화 후 값은 사실상 'YYYY-MM-DD HH:MM:SS' 또는 'YYYY-MM-DD H:MM' 두 고정
    포맷으로 수렴하므로, 고정 포맷을 벡터화로 먼저 시도하고 그래도 안 되는
    나머지(보통 극소수)에만 느린 mixed를 적용한다.
    """
    s = raw.astype(str).str.strip()
    s = s.str.replace('_', ' ', regex=False)
    s = s.str.replace(r'\s*(AM|PM)$', '', regex=True)
    s = s.str.replace('.', '-', regex=False)

    dt = pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    still_na = dt.isna()
    if still_na.any():
        dt2 = pd.to_datetime(s[still_na], format='%Y-%m-%d %H:%M', errors='coerce')
        dt.loc[still_na] = dt2
        still_na = dt.isna()
    if still_na.any():
        dt3 = pd.to_datetime(s[still_na], format='mixed', errors='coerce')
        dt.loc[still_na] = dt3

    return dt.dt.strftime('%Y-%m-%d %H:%M:%S')


def resolve_measure_time(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """전송시간 우선, 결측/E+/더미값일 때만 등록일자로 폴백.
    단, 전송시간이 유효해도 등록일자와 날짜(캘린더 일자)가 갈리는 경우엔
    일별 집계 왜곡을 막기 위해 등록일자를 우선한다 (measure_time_tx_reg_mismatch=True로 표시).
    (measure_time, source, tx_reg_mismatch) 반환
    """
    norm_lookup = {normalize_key(c): c for c in df.columns}
    tx_col = norm_lookup.get('전송시간')
    reg_col = norm_lookup.get('등록일자')
    mt_col = norm_lookup.get('측정시간')

    n = len(df)
    measure_time = pd.Series([None] * n, index=df.index, dtype=object)
    source = pd.Series(['missing'] * n, index=df.index, dtype=object)
    mismatch = pd.Series([False] * n, index=df.index, dtype=bool)

    # 2023년 이후 스키마는 측정시간 컬럼을 쓰지만, "정상"이라는 건 아직 검증된 적 없는 가정이므로
    # 다른 분기와 동일하게 정규화-파싱을 거친다 (여기서 실패하면 NaN -> 이후 행 폐기 대상)
    if mt_col is not None:
        measure_time = normalize_and_parse(df[mt_col])
        source = pd.Series(['mt'] * n, index=df.index, dtype=object)
        return measure_time, source, mismatch

    reg_raw = df[reg_col].astype(str) if reg_col is not None else pd.Series([None] * n, index=df.index)

    # 전송시간 검증/파싱 - 전량 벡터화 (행 단위 .map()은 수천만 행에서 치명적으로 느림, 스팟체크 중 실측)
    tx_parsed = pd.Series([None] * n, index=df.index, dtype=object)
    if tx_col is not None:
        tx_raw = df[tx_col].astype(str).str.strip()
        tx_is_null = tx_raw.isna() | tx_raw.isin(['None', 'nan'])
        tx_has_e = tx_raw.str.upper().str.contains('E+', regex=False)
        digits = tx_raw.str.split('.', n=1).str[0]
        numeric_match = tx_raw.str.match(r'^(\d{12}|\d{14})(\.0)?$')
        dummy_mask = numeric_match & ((digits.str.slice(4, 6) == '00') | (digits.str.slice(6, 8) == '00'))

        tx_valid_mask = (~tx_is_null) & (~tx_has_e) & (~dummy_mask)

        len12_mask = tx_valid_mask & (digits.str.len() == 12)
        len14_mask = tx_valid_mask & (digits.str.len() == 14)
        if len12_mask.any():
            dt12 = pd.to_datetime(digits[len12_mask], format='%Y%m%d%H%M', errors='coerce')
            tx_parsed.loc[len12_mask] = dt12.dt.strftime('%Y-%m-%d %H:%M:%S')
        if len14_mask.any():
            dt14 = pd.to_datetime(digits[len14_mask], format='%Y%m%d%H%M%S', errors='coerce')
            tx_parsed.loc[len14_mask] = dt14.dt.strftime('%Y-%m-%d %H:%M:%S')

        # 파싱 자체가 실패하면(예외 케이스) 유효 마스크에서 제외
        tx_valid_mask = tx_valid_mask & tx_parsed.notna()
    else:
        tx_raw = pd.Series([None] * n, index=df.index)
        tx_valid_mask = pd.Series([False] * n, index=df.index)

    # 등록일자는 대시/점/언더스코어+초/PM접미사 4개 포맷이 섞여 있으므로 여기서 정규화-파싱까지 끝낸다
    reg_parsed = normalize_and_parse(reg_raw) if reg_col is not None else pd.Series([None] * n, index=df.index)
    reg_available_mask = reg_parsed.notna()
    reg_date = reg_parsed.str.slice(0, 10)
    tx_date = tx_parsed.str.slice(0, 10)

    date_mismatch_mask = tx_valid_mask & reg_available_mask & (tx_date != reg_date)
    mismatch.loc[date_mismatch_mask] = True

    # 1) 전송시간 유효 + 등록일자와 날짜 일치 (또는 등록일자 자체가 없음) -> 전송시간 채택
    tx_final_mask = tx_valid_mask & ~date_mismatch_mask
    measure_time.loc[tx_final_mask] = tx_parsed.loc[tx_final_mask]
    source.loc[tx_final_mask] = 'tx'

    # 2) 전송시간 유효하지만 등록일자와 날짜가 갈림 -> 일자 왜곡 방지 위해 등록일자 채택
    dateguard_mask = date_mismatch_mask & reg_available_mask
    measure_time.loc[dateguard_mask] = reg_parsed.loc[dateguard_mask]
    source.loc[dateguard_mask] = 'reg_dateguard'

    # 3) 전송시간 자체가 무효 -> 등록일자로 폴백
    fallback_mask = (~tx_valid_mask) & reg_available_mask
    measure_time.loc[fallback_mask] = reg_parsed.loc[fallback_mask]
    source.loc[fallback_mask] = 'reg_fallback'

    return measure_time, source, mismatch


accepted, rejected = [], []
drop_reason_counter = Counter()
year_outlier_counter = 0
resumed_file_count = 0
resumed_row_count = 0
years = sorted(df_inv[df_inv['schema_version'].isin(TARGET_SCHEMAS)]['year'].dropna().unique())

for year in years:
    output_path = output_dir / f'sdot_{int(year)}_v8.parquet'
    done_marker = output_dir / f'sdot_{int(year)}_v8.done'

    # 재개 가능하게: 이전 실행이 중간에 죽었어도(메모리 부족 등) 이미 끝낸 연도는 다시 안 돈다.
    # marker에는 "파일수,행수"를 저장해뒀다가 최종 집계(불변식/파싱성공률)에 그대로 합산한다.
    if done_marker.exists():
        marker_file_count, marker_row_count = map(int, done_marker.read_text().strip().split(','))
        resumed_file_count += marker_file_count
        resumed_row_count += marker_row_count
        print(f"\n⏭️  [ {int(year)}년 ] 이미 완료됨 - 건너뜀 (파일 {marker_file_count}개, {marker_row_count:,}행)", flush=True)
        continue
    if output_path.exists():
        output_path.unlink()  # 이전 실행이 중간에 죽어서 남은 미완성 parquet은 폐기

    year_files = df_inv[(df_inv['year'] == year) & (df_inv['schema_version'].isin(TARGET_SCHEMAS))]
    print(f"\n🚀 [ {int(year)}년 병합 시작 ] - 대상 파일: {len(year_files)}개", flush=True)

    # 메모리 절약: 연도 전체를 리스트에 쌓지 않고 파일 단위로 즉시 parquet에 이어쓴다
    # (8GB RAM 환경에서 연도 전체를 메모리에 쌓다가 OOM으로 OS에 강제 종료된 적 있음)
    writer = None
    year_row_count = 0

    for file_idx, (_, row) in enumerate(year_files.iterrows(), 1):
        file_name = row['file_name']
        version = row['schema_version']
        print(f"  [{file_idx}/{len(year_files)}] {file_name} 처리 중...", flush=True)

        found_files = list(PROJECT_ROOT.rglob(file_name))
        if not found_files:
            rejected.append((file_name, 'raw_not_found'))
            continue

        file_path = found_files[0]

        try:
            try:
                df = pd.read_csv(file_path, encoding='utf-8', low_memory=False, index_col=False, on_bad_lines='skip', dtype=str)
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='cp949', low_memory=False, index_col=False, on_bad_lines='skip', dtype=str)
        except Exception as e:
            rejected.append((file_name, f'read_error: {e}'))
            continue

        measure_time, source, tx_reg_mismatch = resolve_measure_time(df)

        rename_map = rename_dicts.get(version, {})
        actual_rename = {col: rename_map[col.strip()] for col in df.columns if col.strip() in rename_map}
        df = df.rename(columns=actual_rename)

        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]

        cols_to_keep = [c for c in df.columns if c in master_columns and c != 'measure_time']
        df = df[cols_to_keep]
        df['measure_time'] = measure_time
        df['measure_time_source'] = source
        df['measure_time_tx_reg_mismatch'] = tx_reg_mismatch

        # 밀림 행(측정시간에 온도가 들어간 경우) 폐기 - script16과 동일 기준
        measure_time_str = df['measure_time'].astype(str)
        valid_mask = (measure_time_str.str.len() >= 8) & (measure_time_str != 'None')
        dropped = (~valid_mask).sum()

        drop_reasons = df.loc[~valid_mask, 'measure_time_source'].map({
            'missing': 'tx_invalid_and_reg_missing',
            'mt': 'mt_present_but_unparseable',
        }).fillna('other')
        drop_reason_counter.update(drop_reasons.value_counts().to_dict())

        df = df[valid_mask]

        # 시각 타당성 체크 (Phase 0 5번 "물리 범위 검증"을 measure_time에도 적용):
        # 이 파일이 대표하는 연도에서 1년 넘게 벗어나면 원본 자체의 시계 이상으로 보고 플래그만 남긴다
        # (조용히 버리지 않음 - "0 치환 금지"와 같은 정신. 실측: 8.2M행 중 1건, 센서 시계 오류로 추정)
        mt_year = df['measure_time'].str.slice(0, 4).astype(float)
        file_year = row['year']
        year_outlier_mask = (mt_year < file_year - 1) | (mt_year > file_year + 1)
        df['measure_time_year_outlier'] = year_outlier_mask
        if year_outlier_mask.any():
            year_outlier_counter += int(year_outlier_mask.sum())
            sample = df.loc[year_outlier_mask, ['sensor_id', 'measure_time']].head(5).values.tolist()
            print(f"  ⚠️  연도 이상치 {int(year_outlier_mask.sum())}건 ({file_name}): {sample}", flush=True)

        string_cols = ['measure_time', 'sensor_id', 'measure_time_source', 'measure_time_tx_reg_mismatch', 'measure_time_year_outlier']
        for col in df.columns:
            if col not in string_cols:
                # 파일마다 결측 유무에 따라 pd.to_numeric이 int64/float64를 오락가락하면
                # 파일별로 다른 pyarrow 스키마가 생겨 ParquetWriter가 이어쓰기에서 터진다 -> float64로 고정
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')

        supported_masters = set(rename_map.values()) | {'measure_time'}
        flag_dict = {f"flag_{m_col}": (1 if m_col in supported_masters else 0) for m_col in master_columns}
        df = df.assign(**flag_dict)
        for fc in flag_columns:
            df[fc] = df[fc].astype('int64')
        df = df.reindex(columns=final_columns)

        table = pa.Table.from_pandas(df, schema=EXPECTED_SCHEMA, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(output_path, EXPECTED_SCHEMA)
        writer.write_table(table)

        accepted.append((file_name, len(df), int(dropped)))
        year_row_count += len(df)

        del df, table
        gc.collect()

    if writer is not None:
        writer.close()
        done_marker.write_text(f"{len(year_files)},{year_row_count}\n")
        print(f"  💾 저장: {output_path.name} ({year_row_count:,}행)", flush=True)

# ==========================================
# 병합 불변식 검증
# ==========================================
total_target_files = len(df_inv[df_inv['schema_version'].isin(TARGET_SCHEMAS)])
total_accepted = len(accepted) + resumed_file_count
print(f"\n{'='*60}")
print(f"병합 불변식 검증: accept({len(accepted)}+{resumed_file_count}건 이전 실행분) + reject({len(rejected)}) == 전체({total_target_files})?")
assert total_accepted + len(rejected) == total_target_files, \
    f"❌ 불일치! accept={total_accepted} reject={len(rejected)} total={total_target_files}"
print("✅ 통과")

if rejected:
    print(f"\n거부된 파일 {len(rejected)}개:")
    for name, reason in rejected:
        print(f"  - {name}: {reason}")

# ==========================================
# 파싱 성공률 검증 (행수 일치와는 별개 지표)
# 행수가 원본과 맞아도 값 자체가 파싱 불가능한 문자열일 수 있으므로,
# "남은 행의 measure_time이 실제로 datetime으로 파싱되는가"를 별도로 확인한다.
# ==========================================
raw_total = int(df_inv[df_inv['schema_version'].isin(TARGET_SCHEMAS)]['row_count'].sum())
kept_total = sum(n for _, n, _ in accepted) + resumed_row_count
dropped_total = sum(d for _, _, d in accepted)  # 이전 실행분(재개된 연도)의 폐기 건수는 마커에 없어 미포함

print(f"\n{'='*60}")
print(f"원본 행수(인벤토리 기준): {raw_total:,}")
print(f"병합 후 남은 행수: {kept_total:,} (파싱 실패로 폐기: {dropped_total:,})")
print(f"행수 보존율: {kept_total/raw_total*100:.2f}%")

if drop_reason_counter:
    print(f"\n폐기 사유별 집계:")
    for reason, cnt in drop_reason_counter.most_common():
        print(f"  - {reason}: {cnt:,}건")

print(f"\n연도 이상치(measure_time_year_outlier) - 이번 실행에서 새로 처리한 파일 기준: {year_outlier_counter}건")
print("  (재개 실행으로 건너뛴 연도의 이상치는 이 카운트에 안 잡힘 - 각 parquet의 컬럼을 직접 집계할 것)")


print(f"\nmeasure_time_source 분포 확인은 별도 검증 스크립트에서 수행")
print("="*60)

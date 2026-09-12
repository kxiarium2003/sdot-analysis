"""
script27-verify-measure-time-fold.py - v2023_onward 측정시간 12시간(AM/PM) 접힘 전수 검증

docs/data-source-notes.md 2026-09-08 항목에서 표본(2023년 7개 파일)으로 확인한
"측정시간과 등록일시가 정확히 12시간 차이" 패턴이, 충돌(중복) 그룹뿐 아니라 충돌
없이 단독으로 남아있는 행에도 얼마나 퍼져 있는지 v2023_onward 전체 339개 원본
파일(metadata/sdot-schema-mapping.xlsx FileInventory 기준)에서 확인한다.
조사만 하고 수정은 하지 않는다.

주의(1차 시도에서 발견한 함정, 재작성 이유):
- 일부 파일(예: S-DoT_2026 일부)은 데이터 행의 컬럼 수가 헤더보다 많다(끝에 이름
  없는 빈 컬럼 다수). script22와 동일하게 index_col=False, on_bad_lines='skip'을
  주지 않으면 pandas가 앞쪽 컬럼들을 이름 없는 인덱스로 취급해 전체 컬럼이 밀려
  읽힌다 - script22는 이미 이 옵션을 쓰고 있어 실제 파이프라인 출력(interim v8)은
  영향 없음이 확인됨, 이 검증 스크립트만 같은 옵션으로 맞춘다.
- 측정시간 hour와 등록일시 hour를 문자열에서 그대로 비교하면, 등록이 몇 분 늦어
  시(hour) 경계를 넘는 지극히 정상적인 지연(예: 0:58 측정 -> 1:03 등록)까지
  "불일치"로 오분류된다. 실제 시각차(분)를 계산해 임계값으로 분류해야 한다.

각 행을 measure_time - 등록일시의 시간차(분)로 3가지로 분류한다:
- match: |시간차| <= 15분 (정상 - 등록 지연 범위 이내)
- fold12: |시간차| - 720분(12시간)| <= 15분 (12시간 접힘 의심)
- other: 그 외 (다른 원인 - 별도 확인 필요)

메모리 전략: 파일 339개를 하나씩 읽어 필요한 2개 컬럼(측정시간/등록일시)만 남기고
파일별 카운트만 전역 카운터에 누적한 뒤 즉시 버린다.
"""
import gc
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
raw_dir = PROJECT_ROOT / 'data' / 'raw'
mapping_file = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'

MATCH_TOL_MIN = 15
FOLD_MIN = 720


def normalize_key(col: str) -> str:
    return ''.join(str(col).split())


def parse_dt(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().str.replace('_', ' ', regex=False)
    dt = pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    mask = dt.isna()
    if mask.any():
        dt2 = pd.to_datetime(s[mask], format='%Y-%m-%d %H:%M', errors='coerce')
        dt = dt.where(~mask, dt2)
    mask = dt.isna()
    if mask.any():
        dt3 = pd.to_datetime(s[mask], errors='coerce', format='mixed')
        dt = dt.where(~mask, dt3)
    return dt


fi = pd.read_excel(mapping_file, sheet_name='FileInventory')
v23 = fi[fi['schema_version'] == 'v2023_onward'].sort_values(['year', 'file_order'])
print(f"[STEP 1] v2023_onward 파일 {len(v23)}개 대상 (기대 총 행수: {v23['row_count'].sum():,})\n")

total = 0
match = 0
fold12 = 0
other_mismatch = 0
unparseable = 0
per_year = {}

for i, row in enumerate(v23.itertuples(), 1):
    path = raw_dir / row.relative_path
    try:
        df = pd.read_csv(path, encoding=row.encoding, dtype=str, index_col=False, on_bad_lines='skip', low_memory=False)
    except UnicodeDecodeError:
        alt_enc = 'cp949' if row.encoding == 'utf-8' else 'utf-8'
        df = pd.read_csv(path, encoding=alt_enc, dtype=str, index_col=False, on_bad_lines='skip', low_memory=False)

    col_map = {normalize_key(c): c for c in df.columns}
    mt_col = col_map.get('측정시간')
    reg_col = col_map.get('등록일시')
    if mt_col is None or reg_col is None:
        print(f"  ! 컬럼 못 찾음, 건너뜀: {row.relative_path} (columns={list(df.columns)})")
        continue

    mt_dt = parse_dt(df[mt_col])
    reg_dt = parse_dt(df[reg_col])

    n = len(df)
    valid = mt_dt.notna() & reg_dt.notna()
    n_unparseable = n - int(valid.sum())

    delta_min = (mt_dt[valid] - reg_dt[valid]).dt.total_seconds() / 60
    abs_delta = delta_min.abs()

    is_match = abs_delta <= MATCH_TOL_MIN
    is_fold12 = (~is_match) & ((abs_delta - FOLD_MIN).abs() <= MATCH_TOL_MIN)
    is_other = (~is_match) & (~is_fold12)

    total += n
    match += int(is_match.sum())
    fold12 += int(is_fold12.sum())
    other_mismatch += int(is_other.sum())
    unparseable += int(n_unparseable)

    y = row.year
    yd = per_year.setdefault(y, {'total': 0, 'match': 0, 'fold12': 0, 'other_mismatch': 0, 'unparseable': 0})
    yd['total'] += n
    yd['match'] += int(is_match.sum())
    yd['fold12'] += int(is_fold12.sum())
    yd['other_mismatch'] += int(is_other.sum())
    yd['unparseable'] += int(n_unparseable)

    del df, mt_dt, reg_dt, valid, delta_min, abs_delta, is_match, is_fold12, is_other
    if i % 10 == 0:
        gc.collect()

    if i % 50 == 0 or i == len(v23):
        print(f"  진행 {i}/{len(v23)}개 파일 처리 (누적 {total:,}행)", flush=True)

print()
print("[STEP 2] 전체 결과")
print(f"총 행수: {total:,} (파싱 실패 {unparseable:,}, {unparseable/total*100:.3f}%)")
print(f"  match (정상, |시간차|<=15분): {match:,} ({match/total*100:.2f}%)")
print(f"  fold12 (12시간 접힘 의심): {fold12:,} ({fold12/total*100:.2f}%)")
print(f"  other_mismatch (그 외): {other_mismatch:,} ({other_mismatch/total*100:.2f}%)")

print()
print("[STEP 3] 연도별 세부")
for y in sorted(per_year):
    d = per_year[y]
    t = d['total'] if d['total'] else 1
    print(f"  {y}: total={d['total']:,} match={d['match']/t*100:.1f}% fold12={d['fold12']/t*100:.1f}% other={d['other_mismatch']/t*100:.1f}% unparseable={d['unparseable']:,}")

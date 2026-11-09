"""
script43-revise-d5-dong-agg-star4.py - D5 내국인 행정동 여름 집계본 수정: 상한 기준 3→4, 2025-07-08·09 제외

입력: Drive interim/seoul_living_population/agg_dong_summer_2024_2025.parquet (script41 산출, 상한 = 별표 3)
출력: 같은 경로·같은 이름으로 덮어씀. 덮어쓰기 전에 원본을 Drive 안에서
      agg_dong_summer_2024_2025_v1_star3.parquet 로 복사해 둔다(서버 측 복사).
월별 parquet(native/YYYYMM.parquet)은 읽지 않는다.

[변경 1] 상한 {구간}_hi = {구간}_lo + 4 × {구간}_nstar
  근거(2026-10-19 확인, docs/data-source-notes.md D5 마스킹 항목):
  - 2024-07, 2025-07(07-08·09 제외) 내국인 연령 28칸 모두 별표가 아닌 값의 최솟값이 4.0이고,
    0과 (0, 4) 값이 한 건도 없다 → 별표는 "0 이상 4 미만"(0 포함)을 가린 것.
  - 별표가 없는 2025-07-08·09의 [0, 4) 값 비율이 다른 날의 별표 비율과 연령 구간별로 1%p 이내로 같다
    ([0, 3] 기준이면 4~6%p 낮음).
  script41의 상한(별표 = 3)은 {구간}_lo + 3 × {구간}_nstar 와 같음을 확인했으므로(최대 차 7e-12),
  월별 parquet을 다시 읽지 않고 이 식으로 다시 계산한다. 하한(별표 = 0)은 그대로 둔다.
[변경 2] 기준일ID 20250708, 20250709 제외
  이 이틀은 원본에 별표가 없고(작은 값까지 공개됨) 외국인 데이터도 없어서 다른 날과 처리 기준이 다르다.

사용법: python scripts/script43-revise-d5-dong-agg-star4.py [--tmp DIR]
"""
import subprocess
import sys
from pathlib import Path

import duckdb

REMOTE_DIR = 'googledrive:sdot-analysis/interim/seoul_living_population'
NAME = 'agg_dong_summer_2024_2025'
BACKUP = f'{NAME}_v1_star3.parquet'
STAR_HI = 4
DROP_DATES = ('20250708', '20250709')
TMP = Path(sys.argv[sys.argv.index('--tmp') + 1]) if '--tmp' in sys.argv else Path('/tmp')


def rclone(*args):
    r = subprocess.run(['rclone', *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"rclone {' '.join(args)} 실패: {r.stderr[-300:]}")
    return r.stdout


def remote_size(name):
    """폴더 목록에서 이름으로 찾는다(없는 파일 경로를 직접 조회하면 rclone이 오류를 낸다)."""
    for line in rclone('lsf', '--files-only', '--format', 'ps', '--separator', '\t', REMOTE_DIR).splitlines():
        n, s = line.rsplit('\t', 1)
        if n == name:
            return int(s)
    return None


src = TMP / f'{NAME}_v1.parquet'
out = TMP / f'{NAME}.parquet'
rclone('copyto', f'{REMOTE_DIR}/{NAME}.parquet', str(src))

con = duckdb.connect()
con.execute("SET threads TO 4; SET memory_limit = '3GB';")
cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{src}')").fetchall()]
labs = [c[:-3] for c in cols if c.endswith('_lo')]

# script41 상한이 lo + 3·nstar 인지 먼저 확인 (아니면 이 방식으로 다시 계산할 수 없음)
for lab in labs:
    d = con.execute(f"SELECT max(abs({lab}_hi - ({lab}_lo + 3 * {lab}_nstar))) FROM read_parquet('{src}')").fetchone()[0]
    if d > 1e-6:
        raise SystemExit(f"{lab}: 기존 상한이 lo + 3·nstar 와 다름 (최대 차 {d})")

select = ', '.join(f"({c[:-3]}_lo + {STAR_HI} * {c[:-3]}_nstar) AS {c}" if c.endswith('_hi') else c for c in cols)
drop = ', '.join(f"'{d}'" for d in DROP_DATES)
con.execute(f"""COPY (SELECT {select} FROM read_parquet('{src}') WHERE 기준일ID NOT IN ({drop})
                ORDER BY 기준일ID, 시간대구분, 행정동코드) TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")

n_src, n_out, n_drop = con.execute(f"""SELECT (SELECT count(*) FROM read_parquet('{src}')), (SELECT count(*) FROM read_parquet('{out}')),
    (SELECT count(*) FROM read_parquet('{src}') WHERE 기준일ID IN ({drop}))""").fetchone()
if n_src - n_drop != n_out:
    raise SystemExit(f"행 수 불일치: {n_src} - {n_drop} != {n_out}")
print(f"행 수 {n_src:,} → {n_out:,} (제외 {n_drop:,})")
for lab in labs:
    lo, hi, ns = con.execute(f"SELECT SUM({lab}_lo), SUM({lab}_hi), SUM({lab}_nstar) FROM read_parquet('{out}')").fetchone()
    print(f"  {lab}: 하한 {lo:,.0f} 상한 {hi:,.0f} ({(hi - lo) / lo:.2%}) 별표 {ns:,.0f}")

# 덮어쓰기 전에 원본을 Drive 안에서 보존
if remote_size(BACKUP) is None:
    rclone('copyto', f'{REMOTE_DIR}/{NAME}.parquet', f'{REMOTE_DIR}/{BACKUP}')
if remote_size(BACKUP) != src.stat().st_size:
    raise SystemExit("원본 보존 사본 크기가 다름 - 덮어쓰지 않음")
rclone('copyto', str(out), f'{REMOTE_DIR}/{NAME}.parquet')
if remote_size(f'{NAME}.parquet') != out.stat().st_size:
    raise SystemExit("업로드 크기 불일치")
print(f"업로드 완료 {out.stat().st_size:,} B, 원본 보존: {BACKUP}")
src.unlink()
out.unlink()

"""
script41-aggregate-d5-native-dong-summer.py - D5 내국인 생활인구 월별 parquet 대조 + 행정동 여름 집계본

입력(읽기만, 수정 금지): Drive sdot-analysis/interim/seoul_living_population/native/YYYYMM.parquet
  (script30 산출: 값 컬럼은 float, 원본 '*'는 NaN + {컬럼}_suppressed=True)
  Drive 파일을 로컬로 받지 않고 `rclone serve http`(읽기 전용, 127.0.0.1)로 열어 DuckDB httpfs로
  필요한 컬럼만 읽는다.

[사전등록 - 결과 보기 전에 고정] (작성 2026-10-19)
[1] 대조: 2024-01 ~ 2025-12 24개월
  - 행 수, 날짜 범위(최소·최대), 그 달 달력 대비 빠진 날짜
  - 날짜 컬럼: 이름에 '기준일'이 들어간 컬럼(예: 기준일ID, ?"기준일ID")의 이름과 DuckDB 자료형
[2] 행정동 여름 집계본: 2024·2025년 6~9월
  - 날짜: 컬럼 이름을 기준일ID로, 값은 숫자만 남긴 문자열 YYYYMMDD로 통일
  - 행정동 = 집계구코드(13자리) 앞 7자리
  - 단위: 행정동 × 기준일ID × 시간대구분
  - 값: 총생활인구수, 연령 14구간(남녀 합산, 원본 5세 구간 그대로: 0-9, 10-14, ..., 65-69, 70+)
  - 별표(`_suppressed`=True) 처리 - 칸마다 세 값:
      {구간}_lo    별표를 0으로 넣은 합 (하한)
      {구간}_hi    별표를 3으로 넣은 합 (상한, 3명 이하 마스킹 기준)
      {구간}_nstar 별표 칸 수
    별표가 아닌데 값이 비어 있는 칸(NaN, _suppressed=False)은 하한·상한 모두 0으로 넣고 {구간}_nnull 로 센다.
  - 저장: Drive interim/seoul_living_population/agg_dong_summer_2024_2025.parquet (+ 같은 이름 .md)
    로컬 임시 파일은 업로드·크기 검증 후 삭제.

실행: 먼저 `rclone serve http googledrive:sdot-analysis/interim/seoul_living_population/native
       --addr 127.0.0.1:8765 --read-only --vfs-cache-mode off` 를 띄운 뒤
      python scripts/script41-aggregate-d5-native-dong-summer.py [--part 1|2|all]
"""
import sys, json, time, calendar, subprocess, re
from pathlib import Path
import duckdb

BASE = "http://127.0.0.1:8765"
OUT_REMOTE = "googledrive:sdot-analysis/interim/seoul_living_population"
OUT_NAME = "agg_dong_summer_2024_2025"
TMP = Path(sys.argv[sys.argv.index("--tmp") + 1]) if "--tmp" in sys.argv else Path("/tmp")
PART = sys.argv[sys.argv.index("--part") + 1] if "--part" in sys.argv else "all"
MONTHS = [f"{y}{m:02d}" for y in (2024, 2025) for m in range(1, 13)]
SUMMER = [f"{y}{m:02d}" for y in (2024, 2025) for m in range(6, 10)]
BANDS = ["0세부터9세", "10세부터14세", "15세부터19세", "20세부터24세", "25세부터29세", "30세부터34세", "35세부터39세",
         "40세부터44세", "45세부터49세", "50세부터54세", "55세부터59세", "60세부터64세", "65세부터69세", "70세이상"]
LABEL = {b: (re.sub(r"(\d+)세부터(\d+)세", r"a\1_\2", b) if "부터" in b else "a70p") for b in BANDS}
STAR = 3

con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs; SET threads TO 4;")
con.execute("SET http_timeout = 600; SET http_retries = 10; SET http_retry_wait_ms = 3000;")   # Drive 응답 지연 대비
url = lambda ym: f"{BASE}/{ym}.parquet"
q = lambda s: '"' + s.replace('"', '""') + '"'
CACHE1 = TMP / "part1_cache.json"; PARTS2 = TMP / "agg_parts"; PARTS2.mkdir(parents=True, exist_ok=True)


def retry(fn, ym, tries=4):
    for k in range(1, tries + 1):
        try: return fn(ym)
        except duckdb.Error as e:
            print(f"  {ym}: 시도 {k}/{tries} 실패 - {e}", flush=True)
            if k == tries: raise
            time.sleep(30 * k)


def schema(ym):
    return con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url(ym)}')").fetchall()


def date_col(sch):
    c = [(n, t) for n, t, *_ in sch if "기준일" in n]
    return c[0] if c else (None, None)


def part1():
    cache = json.load(open(CACHE1)) if CACHE1.exists() else {}
    for ym in MONTHS:
        if ym in cache: continue
        cache[ym] = retry(one_month1, ym)
        json.dump(cache, open(CACHE1, "w"), ensure_ascii=False, indent=1)
    return [cache[ym] for ym in MONTHS]


def one_month1(ym):
        t0 = time.time(); sch = schema(ym); dc, dt = date_col(sch)
        n = con.execute(f"SELECT count(*) FROM read_parquet('{url(ym)}')").fetchone()[0]
        ds = [r[0] for r in con.execute(f"SELECT DISTINCT regexp_replace(CAST({q(dc)} AS VARCHAR), '[^0-9]', '', 'g') d FROM read_parquet('{url(ym)}') ORDER BY d").fetchall()]
        y, m = int(ym[:4]), int(ym[4:])
        cal = [f"{ym}{d:02d}" for d in range(1, calendar.monthrange(y, m)[1] + 1)]
        miss = [d for d in cal if d not in set(ds)]; extra = [d for d in ds if d not in set(cal)]
        print(f"  [1] {ym}: {n:,}행, {dc}({dt}), {len(ds)}/{len(cal)}일, 빠짐 {miss or '-'} ({time.time()-t0:.0f}s)", flush=True)
        return dict(month=ym, rows=n, date_col=dc, date_type=dt, n_cols=len(sch), d_min=min(ds) if ds else None, d_max=max(ds) if ds else None,
                    n_days=len(ds), n_cal=len(cal), missing=miss, outside_month=extra)


def month_sql(ym):
    sch = schema(ym); names = {n for n, *_ in sch}; dc, _ = date_col(sch)
    def trio(cols, lab):
        lo = " + ".join(f"coalesce({q(c)}, 0)" for c in cols)
        hi = " + ".join(f"CASE WHEN {q(c + '_suppressed')} THEN {STAR} ELSE coalesce({q(c)}, 0) END" for c in cols)
        ns = " + ".join(f"CAST({q(c + '_suppressed')} AS INTEGER)" for c in cols)
        nn = " + ".join(f"CAST(({q(c)} IS NULL AND NOT {q(c + '_suppressed')}) AS INTEGER)" for c in cols)
        return [f"SUM({lo}) AS {lab}_lo", f"SUM({hi}) AS {lab}_hi", f"SUM({ns}) AS {lab}_nstar", f"SUM({nn}) AS {lab}_nnull"]
    exprs = trio(["총생활인구수"], "total")
    for b in BANDS:
        cols = [f"남자{b}생활인구수", f"여자{b}생활인구수"]
        missing = [c for c in cols + [c + "_suppressed" for c in cols] if c not in names]
        if missing: raise SystemExit(f"{ym}: 컬럼 없음 {missing}")
        exprs += trio(cols, LABEL[b])
    return dc, (f"SELECT substr(집계구코드, 1, 7) AS 행정동코드, regexp_replace(CAST({q(dc)} AS VARCHAR), '[^0-9]', '', 'g') AS 기준일ID, "
                f"CAST(시간대구분 AS SMALLINT) AS 시간대구분, count(*) AS n_tract_rows, {', '.join(exprs)} "
                f"FROM read_parquet('{url(ym)}') GROUP BY ALL")


def one_month2(ym):
    t0 = time.time(); part = PARTS2 / f"{ym}.parquet"; tmp = PARTS2 / f"{ym}.parquet.tmp"
    dc, sql = month_sql(ym)
    con.execute(f"COPY ({sql}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)"); tmp.rename(part)   # 다 쓴 뒤에만 이름 확정
    n = con.execute(f"SELECT count(*) FROM read_parquet('{part}')").fetchone()[0]
    print(f"  [2] {ym}: {n:,}행 ({dc}, {time.time()-t0:.0f}s)", flush=True)
    return dict(date_col=dc, rows=n, seconds=round(time.time() - t0))


def part2():
    info = {}
    for ym in SUMMER:
        if (PARTS2 / f"{ym}.parquet").exists(): info[ym] = "기존 월별 파일 사용"; continue
        info[ym] = retry(one_month2, ym)
    con.execute(f"CREATE OR REPLACE TABLE agg AS SELECT * FROM read_parquet('{PARTS2}/*.parquet')")
    out = TMP / f"{OUT_NAME}.parquet"
    con.execute(f"COPY (SELECT * FROM agg ORDER BY 기준일ID, 시간대구분, 행정동코드) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    chk = con.execute("SELECT count(*), count(DISTINCT 행정동코드), count(DISTINCT 기준일ID), min(기준일ID), max(기준일ID), "
                      "count(DISTINCT 시간대구분), min(length(행정동코드)), max(length(행정동코드)) FROM agg").fetchone()
    labs = ["total"] + [LABEL[b] for b in BANDS]
    share = {l: con.execute(f"SELECT SUM({l}_lo), SUM({l}_hi), SUM({l}_nstar), SUM({l}_nnull) FROM agg").fetchone() for l in labs}
    return out, chk, share, info


if __name__ == "__main__":
    res = {}
    if PART in ("1", "all"): res["part1"] = part1()
    if PART in ("2", "all"):
        out, chk, share, info = part2()
        res["part2"] = dict(local=str(out), size=out.stat().st_size, rows=chk[0], n_dong=chk[1], n_days=chk[2], d_min=chk[3], d_max=chk[4],
                            n_hours=chk[5], code_len=[chk[6], chk[7]], share={k: list(v) for k, v in share.items()}, info=info, bands=LABEL)
    json.dump(res, open(TMP / f"{OUT_NAME}_report.json", "w"), ensure_ascii=False, indent=1, default=str)
    print("완료", TMP / f"{OUT_NAME}_report.json")

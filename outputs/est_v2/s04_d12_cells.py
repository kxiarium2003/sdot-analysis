"""s04_d12_cells.py - D12(4개월)를 동 쌍 × 요일 × 시 칸으로 집계.

나이 >= 65(65·70·75·80)를 s65로, 마스킹 행은 0으로 합한 t0, 마스킹 행 수 nm을 만든다.
출발 시각 변환: 도착시 - round(행의 평균 이동 시간/60) (3시간에서 자름).
출력(스크래치): d12cells/dep_YYYYMM.parquet, arr_YYYYMM.parquet(서울↔서울),
              d12cells/gu_YYYYMM.parquet(출발 구 × 요일 × 출발시), d12cells/travel_YYYYMM.parquet
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *

C = SCRATCH / "d12cells"; C.mkdir(exist_ok=True)
con = duck()
WD = " ".join(f"WHEN '{k}' THEN {v}" for k, v in WEEKDAY_KO.items())
for ym in MONTHS:
    src = f"read_parquet('{SCRATCH}/raw/d12/{ym}.parquet')"
    base = f"""
      SELECT CASE 요일 {WD} END wd, CAST(도착시간 AS INT) arr, "출발 행정동 코드" o, "도착 행정동 코드" d,
             CAST(나이 AS INT) age, "이동인구(합)" pop, "이동인구(합)_suppressed" sup, COALESCE("평균 이동 시간(분)",0) t,
             LEAST(CAST(round(COALESCE("평균 이동 시간(분)",0)/60.0) AS INT),3) sh
      FROM {src}"""
    agg = "SUM(CASE WHEN age>=65 THEN COALESCE(pop,0) ELSE 0 END) s65, SUM(COALESCE(pop,0)) t0, SUM(CASE WHEN sup THEN 1 ELSE 0 END) nm, SUM(COALESCE(pop,0)*t) ts"
    con.execute(f"""COPY (SELECT wd, (arr-sh+24)%24 AS hour, o, d, {agg} FROM ({base}) WHERE length(o)=7 AND length(d)=7 GROUP BY 1,2,3,4)
                    TO '{C}/dep_{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    con.execute(f"""COPY (SELECT wd, arr AS hour, o, d, {agg} FROM ({base}) WHERE length(o)=7 AND length(d)=7 GROUP BY 1,2,3,4)
                    TO '{C}/arr_{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    con.execute(f"""COPY (SELECT substr(o,1,5) gu, wd, (arr-sh+24)%24 AS hour, {agg} FROM ({base}) WHERE length(o)=7 GROUP BY 1,2,3)
                    TO '{C}/gu_{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    con.execute(f"""COPY (SELECT sh, CASE WHEN age>=65 THEN 'age65p' ELSE 'other' END g,
                           SUM(COALESCE(pop,0)) pop, SUM(COALESCE(pop,0)*t) ts, SUM(CASE WHEN t>180 THEN COALESCE(pop,0) ELSE 0 END) pop_over3h,
                           SUM(CASE WHEN length(o)=7 AND length(d)=7 AND o=d THEN COALESCE(pop,0) ELSE 0 END) pop_same_dong,
                           SUM(CASE WHEN length(o)=7 AND length(d)=7 THEN COALESCE(pop,0) ELSE 0 END) pop_ss,
                           COUNT(*) n, SUM(CASE WHEN sup THEN 1 ELSE 0 END) n_sup
                    FROM ({base}) GROUP BY 1,2) TO '{C}/travel_{ym}.parquet' (FORMAT parquet)""")
    n = con.execute(f"SELECT count(*) FROM read_parquet('{C}/dep_{ym}.parquet')").fetchone()[0]
    print(ym, "dep cells", n, flush=True)

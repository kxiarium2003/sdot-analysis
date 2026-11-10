"""s03_d12_cells.py - D12 서울 생활이동을 P1 칸으로 집계(est_v2 s04와 같은 규칙). 인자: 월 목록.

출발시 = (도착시 - round(행 평균 이동시간/60), 3시간에서 자름). s65=65세 이상, t0=마스킹 0으로 합, nm=마스킹 행 수.
출력(스크래치) d12cells/: dep_(동쌍×요일×출발시), oall_(출발 동×요일×출발시, 도착지 전체),
                         dall_(도착 동×요일×출발시, 출발지 전체), city_(요일×출발시).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *

C = SCRATCH / "d12cells"; C.mkdir(exist_ok=True)
con = duck()
WD = " ".join(f"WHEN '{k}' THEN {v}" for k, v in WEEKDAY_KO.items())
AGG = "SUM(CASE WHEN age>=65 THEN COALESCE(pop,0) ELSE 0 END) s65, SUM(COALESCE(pop,0)) t0, SUM(CASE WHEN sup THEN 1 ELSE 0 END) nm"
for ym in sys.argv[1].split(","):
    base = f"""SELECT CASE 요일 {WD} END wd, CAST(도착시간 AS INT) arr, "출발 행정동 코드" o, "도착 행정동 코드" d, CAST(나이 AS INT) age,
               "이동인구(합)" pop, "이동인구(합)_suppressed" sup, LEAST(CAST(round(COALESCE("평균 이동 시간(분)",0)/60.0) AS INT),3) sh
               FROM read_parquet('{SCRATCH}/raw/d12/{ym}.parquet')"""
    H = "(arr-sh+24)%24"
    specs = {"dep": (f"wd,{H} AS hour,o,d", "length(o)=7 AND length(d)=7", "1,2,3,4"),
             "oall": (f"wd,{H} AS hour,o", "length(o)=7", "1,2,3"),
             "dall": (f"wd,{H} AS hour,d", "length(d)=7", "1,2,3"),
             "city": (f"wd,{H} AS hour", "TRUE", "1,2")}
    for k, (sel, wh, gb) in specs.items():
        con.execute(f"COPY (SELECT {sel},{AGG} FROM ({base}) WHERE {wh} GROUP BY {gb}) TO '{C}/{k}_{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)")
    print(ym, {k: con.execute(f"SELECT count(*) FROM read_parquet('{C}/{k}_{ym}.parquet')").fetchone()[0] for k in specs}, flush=True)

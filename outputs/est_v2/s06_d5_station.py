"""s06_d5_station.py - B-2: D5 내국인 4개월 보유 확인과 역×반경 65+ 비중(날짜×시).

마스킹(NaN)은 0으로 합한 값(s65)과 3으로 합한 값(s65m3)을 모두 만든다. 마스킹 비율을 함께 보고한다.
출력(스크래치): d5st/YYYYMM.parquet / 요약: s06_d5_status.csv
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import pandas as pd

GEO = SCRATCH / "geo"; O = SCRATCH / "d5st"; O.mkdir(exist_ok=True)
con = duck()
con.register("sta", pd.read_parquet(GEO / "station_oa.parquet"))
OLD = ["남자65세부터69세생활인구수", "여자65세부터69세생활인구수", "남자70세이상생활인구수", "여자70세이상생활인구수"]
stat = []
for ym in MONTHS:
    f = f"{SCRATCH}/raw/d5/{ym}.parquet"
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{f}')").fetchall()]
    dcol = [c for c in cols if "기준일ID" in c and "suppressed" not in c][0]
    for c in OLD + ["총생활인구수", "집계구코드", "시간대구분"]:
        assert c in cols, c
    dq = '"' + dcol.replace('"', '""') + '"'
    s65 = " + ".join(f'COALESCE("{c}",0)' for c in OLD)
    s65m3 = " + ".join(f'COALESCE("{c}",3)' for c in OLD)  # 마스킹 칸을 3으로 둔 상한
    q = f"SELECT CAST({dq} AS VARCHAR) AS dt, 집계구코드 AS oa, 시간대구분 AS h, {s65} AS s65, {s65m3} AS s65m3, 총생활인구수 AS tot, " + ", ".join(f'"{c}" IS NULL m{i}' for i, c in enumerate(OLD)) + f" FROM read_parquet('{f}')"
    r = con.execute(f"""SELECT count(*) AS n, count(distinct dt) AS n_days, count(distinct oa) AS oas, count(distinct h) AS n_hours,
                   AVG(CASE WHEN tot IS NULL THEN 1.0 ELSE 0 END) AS tot_null, AVG(CASE WHEN m0 OR m1 OR m2 OR m3 THEN 1.0 ELSE 0 END) AS any65_null,
                   AVG(CASE WHEN m0 AND m1 AND m2 AND m3 THEN 1.0 ELSE 0 END) AS all65_null
                   FROM ({q})""").df().iloc[0].to_dict()
    r["ym"] = ym; stat.append(r); print(r, flush=True)
    con.execute(f"""COPY (SELECT s.bldn, s.radius, dt AS date, h AS hour, SUM(s65) AS s65, SUM(s65m3) AS s65m3, SUM(tot) AS tot, MAX(CASE WHEN s.method='intersects' THEN 1 ELSE 0 END) AS fallback
                   FROM ({q}) x JOIN sta s ON x.oa=s.oa WHERE tot IS NOT NULL GROUP BY 1,2,3,4) TO '{O}/{ym}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
pd.DataFrame(stat).to_csv(OUT / "s06_d5_status.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(stat).to_string())

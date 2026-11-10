"""s06b_checks.py - 스크래치 est 파일(있는 달 전부)로 자치구별 65+ 비율 분포와 상위 20개 정류장을 만든다.

출력: s06_check_gu.csv, s06_top20_stops.csv
"""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import pandas as pd, numpy as np

fs = sorted(glob.glob(str(SCRATCH / "est/est_*.parquet")))
print("files", [os.path.basename(f) for f in fs])
gus, tops = [], []
for y in ("2024", "2025"):
    f = [x for x in fs if os.path.basename(x)[4:8] == y]
    if not f: continue
    d = pd.concat([pd.read_parquet(x, columns=["node", "board", "board65_mid", "board65_lo", "board65_hi"]) for x in f], ignore_index=True).groupby("node", as_index=False).sum()
    s = pd.read_parquet(SCRATCH / f"geo/stops_{y}.parquet")[["node", "ars", "name", "gu5"]]
    d = d.merge(s, on="node", how="left")
    d["gu"] = d.gu5.map(GU_NAMES)
    d["r"] = d.board65_mid / d.board.where(d.board > 0)
    g = d.groupby("gu").agg(승차=("board", "sum"), 승차65=("board65_mid", "sum"), 하한=("board65_lo", "sum"), 상한=("board65_hi", "sum"), 정류장=("node", "count"))
    g["비율"] = g.승차65 / g.승차; g["연도"] = y
    q = d[d.board >= 1000].groupby("gu").r.quantile([.1, .5, .9]).unstack(); q.columns = ["p10", "p50", "p90"]
    gus.append(g.join(q).reset_index())
    t = d.sort_values("board65_mid", ascending=False).head(20).assign(연도=y)
    tops.append(t[["연도", "ars", "name", "gu", "board", "board65_mid", "board65_lo", "board65_hi", "r"]])
pd.concat(gus).to_csv(OUT / "s06_check_gu.csv", index=False, encoding="utf-8-sig"); print(pd.concat(gus).round(4).to_string())
pd.concat(tops).to_csv(OUT / "s06_top20_stops.csv", index=False, encoding="utf-8-sig"); print(pd.concat(tops).round(3).to_string())

"""s05b - v4b 대 v4 비교 (정류장 하루 전체 합 기준), 월 합계 대 월보 월평균 x 일수.

v4: Drive interim/bus65_v4/est_YYYYMM.parquet 를 스크래치로 받아 정류장별 합을 낸 뒤 지운다.
v4b: outputs/bus65_v4/s03b_stop_day_sum_YYYYMM.csv
사용: python3 -I s05b_compare_v4.py <SCRATCH>
"""
import sys, subprocess, calendar
from pathlib import Path
import duckdb, pandas as pd
from scipy.stats import spearmanr

OUT = Path(__file__).resolve().parent
SCR = Path(sys.argv[1])
MS = ["202407", "202408", "202507", "202508"]
MON = {"202407": 121416, "202408": 119899, "202507": 137116, "202508": 135335}  # 월보 버스 경로 월평균(일평균)

v4, v4b = [], []
for ym in MS:
    cache = SCR / f"v4_stop_day_sum_{ym}.csv"
    if not cache.exists():
        dl = SCR / "dl_v4"
        dl.mkdir(exist_ok=True)
        subprocess.run(["rclone", "copy", f"googledrive:sdot-analysis/interim/bus65_v4/est_{ym}.parquet", str(dl)], check=True)
        f = dl / f"est_{ym}.parquet"
        duckdb.sql(f"SELECT node, sum(board) board, sum(est65_base) est65_base, sum(est65_d24) est65_d24 FROM read_parquet('{f}') GROUP BY node").df().to_csv(cache, index=False)
        f.unlink()
    v4.append(pd.read_csv(cache, dtype={"node": str}).assign(ym=ym))
    v4b.append(pd.read_csv(OUT / f"s03b_stop_day_sum_{ym}.csv", dtype={"node": str}).assign(ym=ym))
v4, v4b = pd.concat(v4), pd.concat(v4b)

rows = []
for scope in MS + ["4개월 합"]:
    a = v4 if scope == "4개월 합" else v4[v4.ym == scope]
    b = v4b if scope == "4개월 합" else v4b[v4b.ym == scope]
    A = a.groupby("node")[["board", "est65_base", "est65_d24"]].sum()
    B = b.groupby("node")[["board", "est65_base", "est65_d24"]].sum()
    m = A.join(B, how="outer", lsuffix="_v4", rsuffix="_v4b").fillna(0)
    for v in ["est65_base", "est65_d24"]:
        x = m[(m[f"{v}_v4"] > 0) | (m[f"{v}_v4b"] > 0)]
        r = spearmanr(x[f"{v}_v4"], x[f"{v}_v4b"])
        rel = (x[f"{v}_v4b"] - x[f"{v}_v4"]) / x[f"{v}_v4"].where(x[f"{v}_v4"] > 0)
        rows.append(dict(범위=scope, 판=("기본판" if v == "est65_base" else "D24판"), 정류장수=len(x), spearman_v4_vs_v4b=r.statistic,
                         v4_합=x[f"{v}_v4"].sum(), v4b_합=x[f"{v}_v4b"].sum(),
                         정류장_변화율_중앙=rel.median(), 정류장_변화율_p10=rel.quantile(.1), 정류장_변화율_p90=rel.quantile(.9),
                         변화율_절대_10pct_초과_정류장=int((rel.abs() > .1).sum()),
                         v4_0_v4b_양수=int(((x[f"{v}_v4"] == 0) & (x[f"{v}_v4b"] > 0)).sum()),
                         v4_양수_v4b_0=int(((x[f"{v}_v4"] > 0) & (x[f"{v}_v4b"] == 0)).sum())))
    if scope == "4개월 합":
        m.reset_index().to_csv(OUT / "s05b_stop_v4_vs_v4b_4m.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(rows).to_csv(OUT / "s05b_rank_v4_vs_v4b.csv", index=False, encoding="utf-8-sig")

tot = []
for ym in MS:
    y, mo = int(ym[:4]), int(ym[4:])
    n = calendar.monthrange(y, mo)[1]
    c = pd.read_csv(OUT / f"s03b_check_{ym}.csv", index_col=0).value
    c4 = pd.read_csv(OUT / f"s03_check_{ym}.csv", index_col=0).value
    tot.append(dict(ym=ym, 일수=n, 월보_월평균=MON[ym], 월보x일수=MON[ym] * n, v4b_기본=float(c["est65_base_sum"]), v4b_D24=float(c["est65_d24_sum"]),
                    v4b_차=float(c["est65_base_sum"]) - MON[ym] * n, v4_기본=float(c4["est65_base_sum"]), v4_차=float(c4["est65_base_sum"]) - MON[ym] * n))
pd.DataFrame(tot).to_csv(OUT / "s05b_month_total_vs_report.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(rows).round(4).to_string()); print(pd.DataFrame(tot).to_string())

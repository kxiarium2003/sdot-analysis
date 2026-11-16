"""s03 - v5 세 후보 추정, 한 달.

65+(s,d,h) = R_d x B(s,d,h) x q(s,d,h) / sum_{그날 s',h'} B x q
  B: v4b 총 승차(Drive interim/bus65_v4b/est_YYYYMM.parquet 의 board, imputed 그대로)
  R_d: 월보 버스 경로 주중/주말 일평균, 8월 15일은 주중
  q_A: v3(interim/bus65_v3/est_YYYYMM.parquet) board65_mid / board. 보정 전 P1이 남아 있지 않아 v3 값을 씀(보고).
       칸이 없으면 같은 달 정류장 x 시 -> 정류장 -> 서울 날짜 x 시 순서로 대체(수준 기록).
  q_B: s02 qB.parquet (정류장 x 월 x 평일/주말 x 시간 묶음)
  q_C: 1
출력: SCRATCH/est/est_YYYYMM.parquet, OUT/s03_*_YYYYMM.csv
사용: python3 -I s03_estimate.py <SCRATCH> <YYYYMM>
"""
import sys, subprocess
from pathlib import Path
import numpy as np, pandas as pd, duckdb

OUT = Path(__file__).resolve().parent
SCR, YM = Path(sys.argv[1]), sys.argv[2]
R = {"202407": (129836, 97209), "202408": (129639, 96091), "202507": (147676, 106755), "202508": (147852, 109048)}[YM]
dl = SCR / "dl"
dl.mkdir(exist_ok=True)
for src in ["bus65_v4b", "bus65_v3"]:
    f = dl / src / f"est_{YM}.parquet"
    if not f.exists():
        subprocess.run(["rclone", "copy", f"googledrive:sdot-analysis/interim/{src}/est_{YM}.parquet", str(dl / src)], check=True)
con = duckdb.connect()
con.execute(f"SET temp_directory='{SCR}/duck_tmp'; SET memory_limit='6GB'")
b = con.execute(f"SELECT ars, node, dong8, date, CAST(hour AS INT) AS hour, board, imputed FROM read_parquet('{dl}/bus65_v4b/est_{YM}.parquet')").df()
v3 = con.execute(f"""SELECT node, substr(replace(CAST(date AS VARCHAR),'-',''),1,8) AS date, CAST(hour AS INT) AS hour, sum(board) b3, sum(board65_mid) m3
    FROM read_parquet('{dl}/bus65_v3/est_{YM}.parquet') GROUP BY ALL""").df()
chk = {"ym": YM, "rows": len(b), "board": b.board.sum(), "v3_rows": len(v3), "v3_board": v3.b3.sum()}

# ---- q_A
b = b.merge(v3, on=["node", "date", "hour"], how="left")
b["q_A"] = np.where(b.b3 > 0, b.m3 / b.b3, np.nan)
b["q_A_src"] = np.where(b.q_A.notna(), "칸", None)
sh = v3.groupby(["node", "hour"])[["b3", "m3"]].sum()
sh = (sh.m3 / sh.b3.where(sh.b3 > 0)).rename("r_sh")
sm = v3.groupby("node")[["b3", "m3"]].sum()
sm = (sm.m3 / sm.b3.where(sm.b3 > 0)).rename("r_sm")
dh = v3.groupby(["date", "hour"])[["b3", "m3"]].sum()
dh = (dh.m3 / dh.b3.where(dh.b3 > 0)).rename("r_dh")
b = b.join(sh, on=["node", "hour"]).join(sm, on="node").join(dh, on=["date", "hour"])
for col, lab in [("r_sh", "정류장x시"), ("r_sm", "정류장"), ("r_dh", "서울 날짜x시")]:
    m = b.q_A.isna() & b[col].notna()
    b.loc[m, "q_A"] = b.loc[m, col]
    b.loc[m, "q_A_src"] = lab
for lab in ["칸", "정류장x시", "정류장", "서울 날짜x시"]:
    chk[f"q_A_src_{lab}_board_pct"] = 100 * b.loc[b.q_A_src == lab, "board"].sum() / b.board.sum()
chk["q_A_missing_board"] = b.loc[b.q_A.isna(), "board"].sum()

# ---- q_B
dtp = pd.to_datetime(b.date)
b["daytype"] = np.where(dtp.dt.dayofweek >= 5, "주말", "평일")
b["bk"] = np.select([b.hour == 0, b.hour <= 5], ["post24", "pre06"], b.hour.map(lambda h: f"{h:02d}"))
qb = pd.read_parquet(SCR / "qB.parquet")
qb = qb[qb.ym == YM].drop(columns="ym")
b = b.merge(qb, on=["node", "daytype", "bk"], how="left")
chk["q_B_missing_board"] = b.loc[b.q_B.isna(), "board"].sum()
b["q_C"] = 1.0

# ---- 배분
dates = sorted(b.date.unique())
Rt = pd.Series([R[1] if pd.Timestamp(d).dayofweek >= 5 else R[0] for d in dates], index=dates)
b["R"] = b.date.map(Rt)
for v in "ABC":
    w = b.board * b[f"q_{v}"].fillna(0)
    b[f"est65_{v}"] = b.R * w / w.groupby(b.date).transform("sum")
    chk[f"est65_{v}_sum"] = b[f"est65_{v}"].sum()
    chk[f"cells_est_gt_board_{v}"] = int((b[f"est65_{v}"] > b.board).sum())
    chk[f"est65_{v}_over_board_pct"] = 100 * b[f"est65_{v}"].sum() / b.board.sum()
chk["R_sum"] = Rt.sum()
day = b.groupby("date")[["board", "est65_A", "est65_B", "est65_C"]].sum().join(Rt.rename("R"))
chk["max_abs_day_minus_R"] = float((day[["est65_A", "est65_B", "est65_C"]].sub(day.R, axis=0)).abs().max().max())
(SCR / "est").mkdir(exist_ok=True)
cols = ["ars", "node", "dong8", "date", "hour", "board", "q_A", "q_A_src", "q_B", "est65_A", "est65_B", "est65_C", "imputed"]
b[cols].sort_values(["date", "node", "hour"]).to_parquet(SCR / f"est/est_{YM}.parquet", index=False, compression="zstd")

# ---- 집계
E = ["board", "est65_A", "est65_B", "est65_C"]
b.groupby(["node", "ars", "dong8"])[E].sum().reset_index().to_csv(OUT / f"s03_stop_month_{YM}.csv", index=False, encoding="utf-8-sig")
ndays = pd.Series(["주말" if pd.Timestamp(d).dayofweek >= 5 else "평일" for d in dates]).value_counts()
hr = b.groupby(["daytype", "hour"])[E].sum().reset_index()
hr["days"] = hr.daytype.map(ndays)
hr.to_csv(OUT / f"s03_hour_{YM}.csv", index=False, encoding="utf-8-sig")
b[b.hour.isin([14, 15, 16])].groupby("node")[E].sum().assign(days=len(dates)).to_csv(OUT / f"s03_stop_1416_{YM}.csv", encoding="utf-8-sig")
b.assign(gu5=b.dong8.str[:5]).groupby(["gu5", "daytype"])[E].sum().reset_index().to_csv(OUT / f"s03_gu_{YM}.csv", index=False, encoding="utf-8-sig")
b.groupby(["date", "daytype", "hour"])[E].sum().reset_index().to_csv(OUT / f"s03_date_hour_{YM}.csv", index=False, encoding="utf-8-sig")
day.to_csv(OUT / f"s03_daily_{YM}.csv", encoding="utf-8-sig")
pd.Series(chk).to_csv(OUT / f"s03_check_{YM}.csv", header=["value"], encoding="utf-8-sig")
for src in ["bus65_v4b", "bus65_v3"]:
    (dl / src / f"est_{YM}.parquet").unlink()
print(pd.Series(chk).to_string())

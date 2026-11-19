"""s04 - v6 유형별 버스 승차 추정, 한 달.

입력: Drive interim/bus65_v5/est_YYYYMM.parquet (board, q_A, est65_A 등), s02_R.csv, s03_pi.csv
같은 (날짜 d, 시간 h) 안에서
  est_eld   = R(경로, 월, daytype) x pi(경로, 월, h) x board*q_A / sum_s board*q_A
  est_child / est_teen / est_dis = R x pi x board / sum_s board
  est_gen   = board - (eld + child + teen + dis), 음수면 0 (개수·합 기록)
  est_gen_same = R(일반) x pi(일반, h) x board / sum_s board   (비교 버전)
  sum_s board = 0 (또는 경로 분모 sum_s board*q_A = 0) 인 (d,h) 는 0.
daytype: 월~금 평일(8월 15일도 평일), 토·일 주말 - v5 와 같음. q_A 결측은 0 (v5 와 같음).
출력: SCRATCH/est/est_YYYYMM.parquet -> Drive interim/bus65_v6/ 업로드, MD5 대조 후 로컬 삭제
      OUT/s04_{check,daily,hour,stop_1416,stop_day}_YYYYMM.csv
사용: python3 -I s04_estimate.py <SCRATCH> <YYYYMM>
"""
import sys, subprocess, hashlib
from pathlib import Path
import numpy as np, pandas as pd

OUT = Path(__file__).resolve().parent
SCR, YM = Path(sys.argv[1]), sys.argv[2]
REMOTE = "googledrive:sdot-analysis/interim"
dl = SCR / "dl" / "bus65_v5"
dl.mkdir(parents=True, exist_ok=True)
src = dl / f"est_{YM}.parquet"
if not src.exists():
    subprocess.run(["rclone", "copy", f"{REMOTE}/bus65_v5/est_{YM}.parquet", str(dl)], check=True)

b = pd.read_parquet(src, columns=["ars", "node", "dong8", "date", "hour", "board", "q_A", "imputed", "est65_A"])
b["hour"] = b.hour.astype(int)
chk = {"ym": YM, "rows": len(b), "board": b.board.sum(), "q_A_missing_rows": int(b.q_A.isna().sum()),
       "q_A_missing_board": b.loc[b.q_A.isna(), "board"].sum()}
dtp = pd.to_datetime(b.date.astype(str))
b["daytype"] = np.where(dtp.dt.dayofweek >= 5, "주말", "평일")

Rt = pd.read_csv(OUT / "s02_R.csv", dtype={"ym": str})
Rt = Rt[(Rt.ym == YM) & Rt.daytype.isin(["평일", "주말"])].set_index(["daytype", "type"]).R
pi = pd.read_csv(OUT / "s03_pi.csv", dtype={"ym": str})
pi = pi[pi.ym == YM].set_index(["type", "hour"]).pi

key = b.date.astype(str) + "_" + b.hour.astype(str)
Sb = b.board.groupby(key).transform("sum")
w = b.board * b.q_A.fillna(0)
Sbq = w.groupby(key).transform("sum")
dh = pd.DataFrame({"Sb": b.board, "Sbq": w}).groupby(key).sum()
chk["dh_cells"] = len(dh)
chk["dh_Sb_zero"] = int((dh.Sb == 0).sum())
chk["dh_Sbq_zero_Sb_pos"] = int(((dh.Sbq == 0) & (dh.Sb > 0)).sum())

share_b = np.where(Sb > 0, b.board / Sb.where(Sb > 0, 1), 0.0)
share_q = np.where(Sbq > 0, w / Sbq.where(Sbq > 0, 1), 0.0)
COL = {"경로": "est_eld", "어린이": "est_child", "청소년": "est_teen", "장애인": "est_dis"}
for t, col in COL.items():
    tot = b.daytype.map({x: Rt[x, t] for x in ["평일", "주말"]}).to_numpy() * b.hour.map(pi.loc[t]).to_numpy()
    b[col] = tot * (share_q if t == "경로" else share_b)
tot_gen = b.daytype.map({x: Rt[x, "일반"] for x in ["평일", "주말"]}).to_numpy() * b.hour.map(pi.loc["일반"]).to_numpy()
b["est_gen_same"] = tot_gen * share_b
sum4 = b[list(COL.values())].sum(axis=1)
raw = b.board - sum4
neg = raw < 0
chk["gen_neg_cells"] = int(neg.sum())
chk["gen_neg_sum"] = float(-raw[neg].sum())
chk["gen_neg_board_sum"] = float(b.board[neg].sum())
chk["gen_neg_cells_board0"] = int((neg & (b.board == 0)).sum())
b["est_gen"] = raw.clip(lower=0)

# ---- 점검(칸)
tot5 = sum4 + b.est_gen
d = (tot5 - b.board).abs()
chk["cell_absdiff_max_nonneg"] = float(d[~neg].max())
chk["cell_absdiff_max_all"] = float(d.max())
pos = b.board > 0
r_same = ((sum4 + b.est_gen_same) / b.board)[pos]
for q in [0.01, 0.5, 0.99]:
    chk[f"same_cell_ratio_p{int(q * 100)}"] = float(r_same.quantile(q))
wq = r_same.sort_values()
cw = b.board[pos].reindex(wq.index).cumsum() / b.board[pos].sum()
for q in [0.01, 0.5, 0.99]:
    chk[f"same_cell_ratio_boardw_p{int(q * 100)}"] = float(wq[cw >= q].iloc[0])
chk["same_total_over_board_pct"] = 100 * float((sum4 + b.est_gen_same).sum() / b.board.sum())

# ---- 저장
E = ["board", "est_eld", "est_child", "est_teen", "est_dis", "est_gen", "est_gen_same", "est65_A"]
(SCR / "est").mkdir(exist_ok=True)
cols = ["ars", "node", "dong8", "date", "hour", "board", "q_A", "imputed", "est_eld", "est_child", "est_teen", "est_dis", "est_gen", "est_gen_same"]
fo = SCR / f"est/est_{YM}.parquet"
b[cols].to_parquet(fo, index=False, compression="zstd")

# ---- 집계
day = b.groupby(["date", "daytype"])[E].sum().reset_index()
for t in ["경로", "어린이", "청소년", "장애인", "일반"]:
    day[f"R_{t}"] = day.daytype.map({x: Rt[x, t] for x in ["평일", "주말"]})
for t, col in COL.items():
    chk[f"day_absdiff_max_{col}"] = float((day[col] - day[f"R_{t}"]).abs().max())
day.to_csv(OUT / f"s04_daily_{YM}.csv", index=False, encoding="utf-8-sig")
ndays = day.daytype.value_counts()
hr = b.groupby(["daytype", "hour"])[E].sum().reset_index()
hr["days"] = hr.daytype.map(ndays)
hr.to_csv(OUT / f"s04_hour_{YM}.csv", index=False, encoding="utf-8-sig")
b[b.hour.isin([14, 15, 16])].groupby(["node", "ars"])[E].sum().assign(days=len(day)).reset_index() \
    .to_csv(OUT / f"s04_stop_1416_{YM}.csv", index=False, encoding="utf-8-sig")
b.groupby(["node", "ars"])[E].sum().assign(days=len(day)).reset_index().to_csv(OUT / f"s04_stop_day_{YM}.csv", index=False, encoding="utf-8-sig")
for c in E:
    chk[f"sum_{c}"] = float(b[c].sum())

# ---- 업로드 + MD5 대조
subprocess.run(["rclone", "copy", str(fo), f"{REMOTE}/bus65_v6/"], check=True)
h = hashlib.md5()
with open(fo, "rb") as f:
    for blk in iter(lambda: f.read(1 << 20), b""):
        h.update(blk)
rm = subprocess.run(["rclone", "md5sum", f"{REMOTE}/bus65_v6/est_{YM}.parquet"], capture_output=True, text=True, check=True).stdout.split()
chk["md5_local"], chk["md5_drive"] = h.hexdigest(), (rm[0] if rm else "")
chk["md5_match"] = chk["md5_local"] == chk["md5_drive"]
chk["parquet_bytes"] = fo.stat().st_size
pd.Series(chk).to_csv(OUT / f"s04_check_{YM}.csv", header=["value"], encoding="utf-8-sig")
assert chk["md5_match"], "MD5 불일치 - 로컬 파일 유지"
fo.unlink()
src.unlink()
print(pd.Series(chk).to_string())

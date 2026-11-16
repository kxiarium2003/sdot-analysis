"""s03 - 65세 이상 버스 승차 추정 v4(간단판), 한 달.

0. 결측일: D16 월 승차(정류장 x 시간, 노선 합) - D25 나머지 날짜 합 = 결측 이틀 합 -> 반반. 음수는 0.
1. 서울 하루 65+ = 월보 버스 경로(주중/주말 일평균). 8월 15일은 주말.
2. 행정동 = 1 x TOPIS 동별 수단OD 서울 출발 동 버스 비율(s02).
3. 정류장 = 2 x 동 안 비율. 기본판: D25 하루 승차. D24판: 하루 승차 x 정류장 경로 비율(D24 2025-08 정류장->정류장,
   월 경로 30건 미만이면 행정동 값).
4. 시간 = 3 x 정류장 그날 시간대 승차 비율(D25).
출력: SCRATCH/est/est_YYYYMM.parquet, outputs/bus65_v4/s03_check_YYYYMM.csv 등
사용: python3 -I s03_estimate.py <SCRATCH> <YYYYMM>
"""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
AUD = ROOT / "outputs/bus65_v4_audit"
SCR, YM = Path(sys.argv[1]), sys.argv[2]
MISSING = {"202408": ["20240820", "20240821"], "202507": ["20250701", "20250702"]}.get(YM, [])
R = {"202407": (129836, 97209), "202408": (129639, 96091), "202507": (147676, 106755), "202508": (147852, 109048)}[YM]
HOLI = {"20240815", "20250815"}
H = [f"{h:02d}" for h in range(24)]
chk = {"ym": YM}

# ---- D25 (결측일 제외)
fs = sorted(glob.glob(str(SCR / f"d25/{YM}/*.parquet")))
parts = []
for f in fs:
    day = Path(f).stem
    if day in MISSING:
        chk[f"d25_dropped_{day}"] = float(pd.read_parquet(f).iloc[:, 1:].to_numpy().sum())
        continue
    p = pd.read_parquet(f)
    p.insert(0, "date", day)
    parts.append(p)
d25 = pd.concat(parts, ignore_index=True)
d25.columns = ["date", "node"] + H
chk["d25_days_used"] = d25.date.nunique()

# ---- 0. 결측일 보충 (D16)
if MISSING:
    f16 = ROOT / f"data/raw/D16_bus_hourly/{YM[:4]}년_버스노선별_정류장별_시간대별_승하차_인원_정보({YM[4:]}월).csv"
    d16 = pd.read_csv(f16, encoding="cp949", dtype=str)
    on = {c: f"{int(c.split('시')[0]):02d}" for c in d16.columns if c.endswith("승차총승객수")}
    d16 = d16[["표준버스정류장ID"] + list(on)].rename(columns=on | {"표준버스정류장ID": "node"})
    for h in H:
        d16[h] = pd.to_numeric(d16[h]).fillna(0)
    d16 = d16[d16.node.str.fullmatch(r"\d{9}")].groupby("node")[H].sum()
    rest = d25.groupby("node")[H].sum()
    m2 = d16.sub(rest, fill_value=0)
    neg = m2 < 0
    chk["impute_neg_cells"] = int(neg.to_numpy().sum())
    chk["impute_neg_sum"] = float(m2[neg].sum().sum())
    chk["impute_neg_stops"] = int(neg.any(axis=1).sum())
    chk["impute_cells_total"] = int(m2.size)
    m2 = m2.clip(lower=0)
    chk["d16_month_board"] = float(d16.to_numpy().sum())
    chk["d25_rest_board"] = float(rest.to_numpy().sum())
    chk["imputed_two_days_board"] = float(m2.to_numpy().sum())
    half = (m2 / 2).reset_index()
    d25 = pd.concat([d25.assign(imputed=False), pd.concat([half.assign(date=day, imputed=True) for day in MISSING])[["date", "node"] + H + ["imputed"]]], ignore_index=True)
else:
    d25["imputed"] = False
d25["day_board"] = d25[H].sum(axis=1)
chk["days_total"] = d25.date.nunique()

# ---- 정류장 -> 행정동 (감사 작업 연결표)
geo = pd.read_parquet(SCR / "stop_geo.parquet")[["node", "ars", "name", "dong7", "dong_nm", "gu_by_xy"]]
d25 = d25.merge(geo, on="node", how="left")
seoul_id = d25.node.str[:3].between("100", "124")
nomatch = d25[seoul_id & d25.dong7.isna()]
chk["seoulid_nodes_no_dong"] = nomatch.node.nunique()
chk["seoulid_board_no_dong"] = float(nomatch.day_board.sum())
chk["board_all9"] = float(d25.day_board.sum())
st = d25[d25.dong7.notna()].copy()
chk["board_seoul_dong"] = float(st.day_board.sum())
chk["nonseoulid_nodes_in_seoul_dong"] = st.loc[~st.node.str[:3].between("100", "124"), "node"].nunique()

# ---- D24 정류장 경로 비율
a = pd.read_csv(AUD / "table_d24_stop_share_202508.csv", dtype={"on_id": str})
dg = pd.read_csv(AUD / "d24_ss_share_by_dong_202508.csv", dtype={"dong7": str}).set_index("dong7")
r_dong = (dg.eld_ss / dg.n_ss)
stop_r = a.loc[a.eld_ss >= 30].set_index("on_id").eval("eld_ss / n_ss")
st["r_d24"] = st.node.map(stop_r)
st["r_src"] = np.where(st.r_d24.notna(), "정류장", "행정동")
st["r_d24"] = st.r_d24.fillna(st.dong7.map(r_dong))
chk["d24_r_missing_rows"] = int(st.r_d24.isna().sum())

# ---- 1·2. 서울 하루 65+ -> 행정동
ds = pd.read_parquet(SCR / "dong_share.parquet")
ds = ds[ds.date.str[:6] == YM]
dates = sorted(st.date.unique())
wk = pd.to_datetime(pd.Series(dates)).dt.dayofweek
Rt = pd.Series([R[1] if (w >= 5 or d in HOLI) else R[0] for d, w in zip(dates, wk)], index=dates)
ds["dong65"] = ds.share * ds.date.map(Rt)
chk["R_month_sum"] = float(Rt.sum())

# ---- 3. 동 안 정류장
st["w_base"] = st.day_board
st["w_d24"] = st.day_board * st.r_d24
for v in ["base", "d24"]:
    st[f"W_{v}"] = st.groupby(["date", "dong7"])[f"w_{v}"].transform("sum")
st = st.merge(ds[["date", "dong7", "dong65"]], on=["date", "dong7"], how="left")
st["dong65"] = st.dong65.fillna(0)
for v in ["base", "d24"]:
    st[f"day65_{v}"] = np.where(st[f"W_{v}"] > 0, st.dong65 * st[f"w_{v}"] / st[f"W_{v}"], 0)
# 손실: 동 65+가 있는데 그 동에 승차가 없는 경우
dongday = st.groupby(["date", "dong7"]).agg(W=("W_base", "first")).reset_index()
lost = ds.merge(dongday, on=["date", "dong7"], how="left")
lost_mask = lost.W.isna() | (lost.W <= 0)
chk["dong65_lost_no_stops"] = float(lost.loc[lost_mask, "dong65"].sum())
chk["dong_days_lost"] = int(lost_mask.sum())
zero_share = st[st.dong65 == 0].groupby("dong7").agg(board=("day_board", "sum"), nodes=("node", "nunique"), nm=("dong_nm", "first"))
zero_share.to_csv(OUT / f"s03_dong_zero_share_{YM}.csv", encoding="utf-8-sig")
chk["dongs_with_stops_zero_share"] = int(len(zero_share[zero_share.board > 0]))
chk["board_in_zero_share_dongs"] = float(zero_share.board.sum())

# ---- 4. 시간대
long = st.melt(id_vars=["date", "node", "ars", "dong7", "imputed", "day_board", "day65_base", "day65_d24"], value_vars=H, var_name="hour", value_name="board")
long = long[long.board > 0]
for v in ["base", "d24"]:
    long[f"est65_{v}"] = long[f"day65_{v}"] * long.board / long.day_board
est = long[["ars", "node", "dong7", "date", "hour", "board", "est65_base", "est65_d24", "imputed"]].copy()
est["hour"] = est.hour.astype("int8")
est = est.sort_values(["date", "node", "hour"])
(SCR / "est").mkdir(exist_ok=True)
est.to_parquet(SCR / f"est/est_{YM}.parquet", index=False, compression="zstd")

# ---- 점검
for v in ["base", "d24"]:
    chk[f"est65_{v}_sum"] = float(est[f"est65_{v}"].sum())
    chk[f"cells_est_gt_board_{v}"] = int((est[f"est65_{v}"] > est.board).sum())
    chk[f"stopdays_est_gt_board_{v}"] = int((st[f"day65_{v}"] > st.day_board).sum())
    chk[f"est65_{v}_over_board_pct"] = 100 * est[f"est65_{v}"].sum() / est.board.sum()
chk["board_est_rows_sum"] = float(est.board.sum())
chk["rows"] = len(est)
chk["stops"] = est.node.nunique()
chk["r_src_stop_pct_of_board"] = 100 * st.loc[st.r_src == "정류장", "day_board"].sum() / st.day_board.sum()
daily = est.groupby("date")[["board", "est65_base", "est65_d24"]].sum().join(Rt.rename("R_report"))
daily.to_csv(OUT / f"s03_daily_{YM}.csv", encoding="utf-8-sig")
gu = st.groupby("gu_by_xy")[["day_board", "day65_base", "day65_d24"]].sum()
gu["pct_base"] = 100 * gu.day65_base / gu.day_board
gu["pct_d24"] = 100 * gu.day65_d24 / gu.day_board
gu.to_csv(OUT / f"s03_gu_{YM}.csv", encoding="utf-8-sig")
# 14~16시(14, 15시) 정류장별 합 (s04에서 4개월 하루 평균으로 씀)
w = est[est.hour.isin([14, 15])].groupby("node")[["board", "est65_base", "est65_d24"]].sum()
w["days"] = chk["days_total"]
w.to_csv(OUT / f"s03_stop_1416_sum_{YM}.csv", encoding="utf-8-sig")
st.drop_duplicates("node")[["node", "ars", "name", "dong7", "dong_nm", "gu_by_xy", "r_d24", "r_src"]].to_csv(SCR / f"stop_attr_{YM}.csv", index=False)
pd.Series(chk).to_csv(OUT / f"s03_check_{YM}.csv", header=["value"], encoding="utf-8-sig")
print(pd.Series(chk).to_string())

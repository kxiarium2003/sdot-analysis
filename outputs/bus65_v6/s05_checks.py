"""s05 - v6 점검과 v5 비교 (네 달). s04 월별 집계만 읽는다(큰 parquet 은 다시 읽지 않음).

입력: s04_{check,daily,hour,stop_1416,stop_day}_YYYYMM.csv, s02_R.csv, s03_pi.csv, s01_report_bus_hour.csv,
      ../bus65_v5/s01_d24_hour.csv (D24 서울시 정류장별 사용자유형별 환승 데이터 경로 시간 분포)
출력: s05_check1_day_vs_R.csv, s05_check2_cell.csv, s05_check3_gen.csv, s05_check4_hour.csv, s05_check4_summary.csv,
      s05_v5v6_daily.csv, s05_v5v6_hour_share.csv, s05_v5v6_hour_corr.csv, s05_v5v6_top20_1416.csv, s05_v5v6_rank.csv,
      s05_top20_by_type_1416.csv
사용: python3 -I s05_checks.py
"""
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import spearmanr

OUT = Path(__file__).resolve().parent
V5 = OUT.parent / "bus65_v5"
MS = ["202407", "202408", "202507", "202508"]
kw = dict(index=False, encoding="utf-8-sig")
TY = {"경로": "est_eld", "어린이": "est_child", "청소년": "est_teen", "장애인": "est_dis", "일반": "est_gen"}

chk = pd.concat([pd.read_csv(OUT / f"s04_check_{m}.csv", index_col=0).value.rename(m) for m in MS], axis=1)
day = pd.concat([pd.read_csv(OUT / f"s04_daily_{m}.csv", dtype={"date": str}).assign(ym=m) for m in MS])
hr = pd.concat([pd.read_csv(OUT / f"s04_hour_{m}.csv").assign(ym=m) for m in MS])
s16 = pd.concat([pd.read_csv(OUT / f"s04_stop_1416_{m}.csv", dtype={"node": str, "ars": str}).assign(ym=m) for m in MS])
R = pd.read_csv(OUT / "s02_R.csv", dtype={"ym": str})
pi = pd.read_csv(OUT / "s03_pi.csv", dtype={"ym": str})

# ---- 점검 1: 유형별 날짜 합 = R
c1 = []
for m in MS:
    d = day[day.ym == m]
    for t in ["경로", "어린이", "청소년", "장애인"]:
        e = d[TY[t]] - d[f"R_{t}"]
        c1.append(dict(ym=m, type=t, days=len(d), max_abs_diff=e.abs().max(), max_rel_diff=(e.abs() / d[f"R_{t}"]).max()))
c1 = pd.DataFrame(c1)
c1.to_csv(OUT / "s05_check1_day_vs_R.csv", **kw)

# ---- 점검 2: 칸별 합 = board, 음수 처리
c2 = chk.loc[["rows", "board", "dh_cells", "dh_Sb_zero", "dh_Sbq_zero_Sb_pos", "cell_absdiff_max_nonneg", "cell_absdiff_max_all",
              "gen_neg_cells", "gen_neg_sum", "gen_neg_board_sum", "gen_neg_cells_board0", "q_A_missing_rows", "md5_match", "parquet_bytes"]].T
c2.index.name = "ym"
c2.reset_index().to_csv(OUT / "s05_check2_cell.csv", **kw)

# ---- 점검 3: est_gen 하루 합 / R(일반), est_gen_same 칸 비율 분포
g = day.assign(ratio=day.est_gen / day.R_일반, ratio_same=day.est_gen_same / day.R_일반, board_over_R=day.board / (day[[f"R_{t}" for t in TY]].sum(axis=1)))
c3 = g.groupby(["ym", "daytype"]).agg(days=("date", "size"), gen_over_R_mean=("ratio", "mean"), gen_over_R_min=("ratio", "min"),
                                       gen_over_R_max=("ratio", "max"), board_over_sumR_mean=("board_over_R", "mean")).reset_index()
q = chk.loc[[i for i in chk.index if i.startswith("same_")]].T
q.index.name = "ym"
c3 = c3.merge(q.reset_index(), on="ym")
c3.to_csv(OUT / "s05_check3_gen.csv", **kw)

# ---- 점검 4: 시간대별 sum_t R*pi(h) vs 서울 board 시간 합 (하루 평균)
rp = R[R.in_estimate & R.daytype.isin(["평일", "주말"])].merge(pi, on=["ym", "type"])
rp["Rpi"] = rp.R * rp.pi
rp = rp.groupby(["ym", "daytype", "hour"]).Rpi.sum().reset_index()
h4 = hr[["ym", "daytype", "hour", "board", "days"]].assign(board_day=lambda x: x.board / x.days).merge(rp, on=["ym", "daytype", "hour"])
bh = pd.read_csv(OUT / "s01_report_bus_hour.csv", dtype={"ym": str})
bh = bh[bh.daytype != "전체"].assign(daytype=lambda x: x.daytype.map({"주중": "평일", "주말": "주말"}))
h4 = h4.merge(bh[["ym", "daytype", "hour", "bus", "hour_table_ok"]].rename(columns={"bus": "report_bus", "hour_table_ok": "report_ok"}),
              on=["ym", "daytype", "hour"], how="left")
h4["Rpi_over_board"] = h4.Rpi / h4.board_day
h4["gen_cells_short"] = (h4.Rpi > h4.board_day)
for c in ["board_day", "Rpi", "report_bus"]:
    h4[f"{c}_share"] = h4[c] / h4.groupby(["ym", "daytype"])[c].transform("sum")
h4.to_csv(OUT / "s05_check4_hour.csv", **kw)
s4 = []
for (m, dt), x in h4.groupby(["ym", "daytype"]):
    s4.append(dict(ym=m, daytype=dt, sumRpi_over_board=x.Rpi.sum() / x.board_day.sum(),
                   ratio_min=x.Rpi_over_board.min(), ratio_min_hour=int(x.loc[x.Rpi_over_board.idxmin(), "hour"]),
                   ratio_max=x.Rpi_over_board.max(), ratio_max_hour=int(x.loc[x.Rpi_over_board.idxmax(), "hour"]),
                   hours_Rpi_gt_board=int(x.gen_cells_short.sum()),
                   share_corr=np.corrcoef(x.Rpi_share, x.board_day_share)[0, 1],
                   share_maxabs_pp=100 * (x.Rpi_share - x.board_day_share).abs().max(),
                   report_board_corr=(np.corrcoef(x.report_bus_share, x.board_day_share)[0, 1] if x.report_ok.all() else np.nan)))
s4 = pd.DataFrame(s4)
s4.to_csv(OUT / "s05_check4_summary.csv", **kw)

# ---- v5 비교 (a) 하루 합
v = day.groupby(["ym", "daytype"])[["est65_A", "est_eld", "board"]].mean().reset_index()
v["v6_over_v5"] = v.est_eld / v.est65_A
v.to_csv(OUT / "s05_v5v6_daily.csv", **kw)

# ---- (b) 시간 비중 (네 달 합) + D24 + 월보 경로(pi, 버스+지하철 전체 날)
d24 = pd.read_csv(V5 / "s01_d24_hour.csv", dtype={"ym": str, "hh": str})
d24["hour"] = d24.hh.astype(int)
H = hr.groupby(["daytype", "hour"])[["est65_A", "est_eld", "board"]].sum()
H = H / H.groupby(level=0).transform("sum")
H = H.join(d24.groupby(["daytype", "hour"]).n_eld.sum().pipe(lambda s: s / s.groupby(level=0).transform("sum")).rename("D24_eld"))
pe = pi[pi.type == "경로"].merge(pd.read_csv(OUT / "s01_report_type_hour.csv", dtype={"ym": str}).query("type=='경로' and hour>=0"), on=["ym", "type", "hour"])
H = H.join((pe.groupby("hour")["count_x"].sum() / pe["count_x"].sum()).rename("report_eld_pi_4m"), on="hour")
H = H.reset_index()
H.to_csv(OUT / "s05_v5v6_hour_share.csv", **kw)
hc = []
for dt, x in H.groupby("daytype"):
    for col, lab in [("est65_A", "v5 A"), ("est_eld", "v6"), ("board", "총 승차")]:
        hc.append(dict(daytype=dt, series=lab, corr_D24=np.corrcoef(x[col], x.D24_eld)[0, 1],
                       share_h8=x.loc[x.hour == 8, col].iloc[0], share_1416=x.loc[x.hour.isin([14, 15, 16]), col].sum(),
                       D24_h8=x.loc[x.hour == 8, "D24_eld"].iloc[0], D24_1416=x.loc[x.hour.isin([14, 15, 16]), "D24_eld"].sum()))
# 달별 상관도
d24m = d24.set_index(["ym", "daytype", "hour"]).n_eld
hm = hr.set_index(["ym", "daytype", "hour"])[["est65_A", "est_eld"]].join(d24m)
for (m, dt), x in hm.groupby(level=[0, 1]):
    for col, lab in [("est65_A", "v5 A"), ("est_eld", "v6")]:
        hc.append(dict(daytype=dt, series=lab, ym=m, corr_D24=np.corrcoef(x[col], x.n_eld)[0, 1]))
hc = pd.DataFrame(hc)
hc.to_csv(OUT / "s05_v5v6_hour_corr.csv", **kw)

# ---- (c) 14·15·16시 하루 평균 정류장 (네 달 날 수로 나눔, v5 와 같은 정의)
days = s16.drop_duplicates("ym").days.sum()
E = ["board", "est_eld", "est_child", "est_teen", "est_dis", "est_gen", "est_gen_same", "est65_A"]
ars = s16.drop_duplicates("node", keep="last").set_index("node").ars
A16 = (s16.groupby("node")[E].sum() / days).join(ars)
top_v5 = A16.nlargest(20, "est65_A")
top_v6 = A16.nlargest(20, "est_eld")
both = A16[(A16.est65_A > 0) | (A16.est_eld > 0)]
rk = [dict(기준="14·15·16시 하루 평균(네 달)", 비교="v5 A vs v6 경로", 정류장=len(both), spearman=spearmanr(both.est65_A, both.est_eld).statistic,
           top20_overlap=len(set(top_v5.index) & set(top_v6.index)))]
sd = pd.concat([pd.read_csv(OUT / f"s04_stop_day_{m}.csv", dtype={"node": str}) for m in MS]).groupby("node")[E].sum()
x = sd[(sd.est65_A > 0) | (sd.est_eld > 0)]
rk.append(dict(기준="하루 전체(네 달 합)", 비교="v5 A vs v6 경로", 정류장=len(x), spearman=spearmanr(x.est65_A, x.est_eld).statistic,
               top20_overlap=len(set(x.nlargest(20, "est65_A").index) & set(x.nlargest(20, "est_eld").index))))
for col in ["est_eld", "est65_A"]:
    rk.append(dict(기준="14·15·16시 하루 평균(네 달)", 비교=f"{col} vs 총 승차", 정류장=len(both), spearman=spearmanr(both[col], both.board).statistic,
                   top20_overlap=len(set(A16.nlargest(20, col).index) & set(A16.nlargest(20, "board").index))))
pd.DataFrame(rk).to_csv(OUT / "s05_v5v6_rank.csv", **kw)
t = []
for lab, tp, col in [("v5 A", top_v5, "est65_A"), ("v6 경로", top_v6, "est_eld")]:
    z = tp.reset_index()[["node", "ars", "board", "est65_A", "est_eld"]]
    z.insert(0, "rank", range(1, 21)); z.insert(0, "series", lab)
    z["in_other_top20"] = z.node.isin((top_v6 if lab == "v5 A" else top_v5).index)
    t.append(z)
pd.concat(t).to_csv(OUT / "s05_v5v6_top20_1416.csv", **kw)

# ---- 6. 유형별 상위 20 (ars 만)
t = []
for lab, col in list(TY.items()) + [("일반(비교 버전)", "est_gen_same"), ("총 승차", "board")]:
    tp = A16.nlargest(20, col)
    z = pd.DataFrame({"ars": tp.ars.values, "node": tp.index, "per_day_1416": tp[col].values, "board": tp.board.values})
    z["share_of_board_pct"] = 100 * z.per_day_1416 / z.board
    z.insert(0, "rank", range(1, 21)); z.insert(0, "type", lab)
    t.append(z)
pd.concat(t).to_csv(OUT / "s05_top20_by_type_1416.csv", **kw)

pd.set_option("display.width", 250)
for name, df in [("check1", c1), ("check2", c2), ("check3", c3), ("check4", s4), ("v5v6 daily", v), ("hour corr", hc[hc.ym.isna()] if "ym" in hc else hc),
                 ("rank", pd.DataFrame(rk))]:
    print(f"## {name}\n{df.to_string()}\n")

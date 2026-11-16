"""s04 - 시험 1(D24 정류장), 선택 규칙 적용, 시간대 표, 상위 30, 순위상관.

입력(OUT): s01_d24_stop_month.csv, s01_d24_hour.csv, s03_stop_month_*.csv, s03_hour_*.csv, s03_stop_1416_*.csv,
          s02_stop_nearest_dist.csv, s04_report_eld_hour.csv, table_test2_subway.csv
입력(SCR): stop_geo.parquet(정류장 이름), stations.parquet
사용: python3 -I s04_tests.py <SCRATCH>
"""
import sys, itertools
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import spearmanr, pearsonr

OUT = Path(__file__).resolve().parent
SCR = Path(sys.argv[1])
MS = ["202407", "202408", "202507", "202508"]
C3 = ["A", "B", "C"]
GU = dict(zip([f"11{i:02d}0" for i in range(1, 26)], "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split()))
d24 = pd.read_csv(OUT / "s01_d24_stop_month.csv", dtype={"on_id": str, "ym": str})
sm = pd.concat([pd.read_csv(OUT / f"s03_stop_month_{m}.csv", dtype={"node": str, "ars": str, "dong8": str}).assign(ym=m) for m in MS])
for v in C3:
    sm[f"r_{v}"] = sm[f"est65_{v}"] / sm.board

# ---- 시험 1 (a)(b)
rows = []
for m in MS:
    t = sm[sm.ym == m].merge(d24[(d24.ym == m) & (d24.n_eld >= 30)][["on_id", "ratio", "n_eld"]], left_on="node", right_on="on_id")
    t = t[t.board > 0]
    for v in C3:
        a = 0.0 if v == "C" else spearmanr(t[f"r_{v}"], t.ratio).statistic
        # (b) 동 안
        ws, wsum, nd = 0.0, 0.0, 0
        if v != "C":
            for dg, g in t.groupby("dong8"):
                if len(g) < 3 or g[f"r_{v}"].nunique() < 2 or g.ratio.nunique() < 2:
                    continue
                r = spearmanr(g[f"r_{v}"], g.ratio).statistic
                ws += r * g.board.sum(); wsum += g.board.sum(); nd += 1
        b = ws / wsum if wsum > 0 else 0.0
        rows.append(dict(ym=m, 후보=v, 시험정류장=len(t), a_정류장순위상관=a, b_동안순위상관_승차가중=b, b_동수=nd if v != "C" else None))
T1 = pd.DataFrame(rows)
avg = T1.groupby("후보")[["a_정류장순위상관", "b_동안순위상관_승차가중"]].mean().reset_index().assign(ym="네 달 평균")
T1 = pd.concat([T1, avg])

# ---- 시험 1 (c) 시간대
dh = pd.read_csv(OUT / "s01_d24_hour.csv", dtype={"ym": str})
dh["hour"] = dh.hh.astype(int)
hr = pd.concat([pd.read_csv(OUT / f"s03_hour_{m}.csv").assign(ym=m) for m in MS])
rep = pd.read_csv(OUT / "s04_report_eld_hour.csv", dtype={"ym": str})
prof, crow = [], []
for scope in MS + ["네 달 합"]:
    for dt in ["평일", "주말"]:
        H = hr[(hr.daytype == dt) & ((hr.ym == scope) | (scope == "네 달 합"))].groupby("hour")[["board", "est65_A", "est65_B", "est65_C"]].sum()
        D = dh[(dh.daytype == dt) & ((dh.ym == scope) | (scope == "네 달 합"))].groupby("hour")[["n", "n_eld"]].sum()
        p = pd.DataFrame({"D24_경로": D.n_eld / D.n_eld.sum()})
        for v in C3:
            p[f"후보{v}"] = H[f"est65_{v}"] / H[f"est65_{v}"].sum()
        p["총승차"] = H.board / H.board.sum()
        p = p.reindex(range(24)).fillna(0)
        pp = (100 * p).reset_index().assign(ym=scope, daytype=dt)
        prof.append(pp)
        for v in C3:
            crow.append(dict(ym=scope, daytype=dt, 후보=v, 상관_24칸=pearsonr(p[f"후보{v}"], p.D24_경로).statistic,
                             비중_14_16시_후보=100 * p.loc[[14, 15, 16], f"후보{v}"].sum(), 비중_14_16시_D24=100 * p.loc[[14, 15, 16], "D24_경로"].sum(),
                             차이_pp=100 * (p.loc[[14, 15, 16], f"후보{v}"].sum() - p.loc[[14, 15, 16], "D24_경로"].sum())))
    # 보고서 경로(버스+지하철, 전체 날)
r_ = rep if True else None
rp = rep.groupby("hour").report_eld_modetrips.sum()
P = pd.concat(prof)
P = P.merge((100 * rp / rp.sum()).rename("보고서경로_버스지하철_네달전체날").reset_index(), on="hour", how="left")
P.to_csv(OUT / "table_hourly_profile.csv", index=False, encoding="utf-8-sig")
TC = pd.DataFrame(crow)

# ---- D24 자체 안정성
stab = []
for a, b in itertools.combinations(MS, 2):
    x = d24[(d24.ym == a) & (d24.n_eld >= 30)].merge(d24[(d24.ym == b) & (d24.n_eld >= 30)], on="on_id")
    stab.append(dict(비교=f"{a} vs {b}", 정류장=len(x), spearman=spearmanr(x.ratio_x, x.ratio_y).statistic))
ST = pd.DataFrame(stab)

with open(OUT / "table_test1_d24.csv", "w", encoding="utf-8-sig") as f:
    f.write("# (a)(b) 정류장·동 안 순위상관 (D24 월 경로 30건 이상 정류장)\n"); T1.to_csv(f, index=False)
    f.write("\n# (c) 시간대 분포 대 D24 경로 (평일·주말)\n"); TC.to_csv(f, index=False)
    f.write("\n# D24 정류장 경로 비율의 달 사이 순위상관\n"); ST.to_csv(f, index=False)

# ---- 선택 규칙
m = T1[T1.ym == "네 달 평균"].set_index("후보")
t2 = pd.read_csv(OUT / "table_test2_subway.csv")
order = m.a_정류장순위상관.drop("C").sort_values(ascending=False)
best, second = order.index[0], order.index[1]
log = [f"규칙1: 네 달 평균 (a) A={m.loc['A','a_정류장순위상관']:.4f}, B={m.loc['B','a_정류장순위상관']:.4f}, C=0 (기준선)"]
if order.iloc[0] < 0.1:
    main = None; log.append("규칙3: 어느 후보도 0.1 미만 -> 주 결과 없음")
elif order.iloc[0] - order.iloc[1] > 0.03:
    main = best; log.append(f"규칙1: 차이 {order.iloc[0]-order.iloc[1]:.4f} > 0.03 -> 주 결과 {best}")
else:
    log.append(f"규칙2: 차이 {order.iloc[0]-order.iloc[1]:.4f} <= 0.03 -> (b) 비교")
    bb = m.b_동안순위상관_승차가중.drop("C")
    if abs(bb[best] - bb[second]) > 0.03:
        main = bb.idxmax(); log.append(f"규칙2(b): A={bb['A']:.4f}, B={bb['B']:.4f} -> 주 결과 {main}")
    else:
        sa = t2.loc[t2.단위.str.startswith("②") & t2.후보.str.startswith("A"), "spearman"].iloc[0]
        sb = t2.loc[t2.단위.str.startswith("②") & t2.후보.str.startswith("B"), "spearman"].iloc[0]
        main = "A" if sa >= sb else "B"; log.append(f"규칙2(시험2 ②): A={sa:.4f}, B={sb:.4f} -> 주 결과 {main}")
pooled = TC[TC.ym == "네 달 합"].groupby("후보").상관_24칸.mean()
hour_best = pooled.idxmax()
log.append(f"규칙4: 시간대(네 달 합, 평일·주말 상관 평균) A={pooled['A']:.4f}, B={pooled['B']:.4f}, C={pooled['C']:.4f} -> 가장 가까운 후보 {hour_best}"
           + ("" if hour_best == main else " (주 결과와 다름 -> 결정 필요)"))
(OUT / "s04_selection_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")

# ---- 상위 30 (14·15·16시 하루 평균), 순위상관
s16 = pd.concat([pd.read_csv(OUT / f"s03_stop_1416_{m}.csv", dtype={"node": str}).assign(ym=m) for m in MS])
days = s16.drop_duplicates("ym").days.sum()
A16 = s16.groupby("node")[["board", "est65_A", "est65_B", "est65_C"]].sum() / days
geo = pd.read_parquet(SCR / "stop_geo.parquet")[["node", "ars", "name"]].set_index("node")
dong = sm.drop_duplicates("node", keep="last").set_index("node")[["dong8"]]
A16 = A16.join(geo).join(dong)
A16["자치구"] = A16.dong8.str[:5].map(GU)
d24all = d24[d24.n_eld >= 0].groupby("on_id")[["n", "n_eld"]].sum()
A16["D24경로비율_네달"] = (d24all.n_eld / d24all.n).reindex(A16.index)
A16["D24경로건수_네달"] = d24all.n_eld.reindex(A16.index)
nd = pd.read_csv(OUT / "s02_stop_nearest_dist.csv", dtype={"node": str}).set_index("node")
A16["최근접역거리m"] = nd.d1.reindex(A16.index)
for v in C3:
    A16[f"65+비율_{v}%"] = 100 * A16[f"est65_{v}"] / A16.board
top = []
for v in C3:
    t = A16.sort_values(f"est65_{v}", ascending=False).head(30).reset_index()
    t.insert(0, "순위", range(1, 31)); t.insert(0, "후보", v)
    top.append(t)
pd.concat(top).rename(columns={"node": "정류장ID", "ars": "ARS", "name": "정류장명", "dong8": "행정동코드", "board": "총승차_14_16시_하루평균",
                              "est65_A": "65+A_하루평균", "est65_B": "65+B_하루평균", "est65_C": "65+C_하루평균"}) \
    .to_csv(OUT / "table_top30_1416.csv", index=False, encoding="utf-8-sig")
day_all = sm.groupby("node")[["board", "est65_A", "est65_B", "est65_C"]].sum()
rc = []
for lab, D in [("하루 전체(네 달 합)", day_all), ("14·15·16시(네 달 하루 평균)", A16)]:
    for a, b in [("est65_A", "est65_B"), ("est65_A", "est65_C"), ("est65_B", "est65_C"), ("est65_A", "board"), ("est65_B", "board"), ("est65_C", "board")]:
        x = D[(D[a] > 0) | (D[b] > 0)]
        rc.append(dict(기준=lab, 비교=f"{a.replace('est65_','후보')} vs {b.replace('est65_','후보').replace('board','총 승차')}", 정류장=len(x), spearman=spearmanr(x[a], x[b]).statistic))
    for v in C3:
        rc.append(dict(기준=lab, 비교=f"상위 30 겹침 후보{v} vs 총 승차 상위 30", 정류장=len(set(D.nlargest(30, f"est65_{v}").index) & set(D.nlargest(30, "board").index)), spearman=None))
pd.DataFrame(rc).to_csv(OUT / "table_rank_corr.csv", index=False, encoding="utf-8-sig")

# ---- B 거리 분포 (승차 가중)
bd = day_all.join(nd[["d1"]])
dsum = dict(정류장=int(bd.d1.notna().sum()), 거리_중앙m=bd.d1.median(), 승차가중_중앙m=bd.sort_values("d1").assign(c=lambda x: x.board.cumsum() / x.board.sum()).query("c>=0.5").d1.iloc[0],
            정류장_1km초과=int((bd.d1 > 1000).sum()), 승차비중_1km초과_pct=100 * bd.loc[bd.d1 > 1000, "board"].sum() / bd.board.sum(),
            정류장_2km초과=int((bd.d1 > 2000).sum()), 승차비중_2km초과_pct=100 * bd.loc[bd.d1 > 2000, "board"].sum() / bd.board.sum())
pd.Series(dsum).to_csv(OUT / "s04_qB_distance_weighted.csv", header=["value"], encoding="utf-8-sig")
print(T1.round(4).to_string()); print(TC[TC.ym == "네 달 합"].round(3).to_string()); print(ST.round(3).to_string()); print("\n".join(log)); print(pd.DataFrame(rc).round(4).to_string()); print(dsum)

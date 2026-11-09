"""
s07_method_ranking.py - 방법별 "정류장 간 차이(순위)를 만드는가" 평가 (추가 지시 3)

입력(읽기만): data/raw/D16_bus_hourly (2025-08), outputs/eda_bus65/ 의 d12_dep_dong_hour.csv (s02),
         q2_station_ratio_summer2025.csv (s03), q1_d20_compare.csv (s06), pilot_jongno_stops_202508.csv (s04)
평가
  1) 방법 A-구 / C: 단위 안 순위 = 승차 순위인지 확인 (자치구별 스피어만)
  2) 방법 A-동: 정류장 → 행정동 연결이 현재 데이터로 불가하므로, 종로구 동별 65+ 비율(시각별)을 정류장에 무작위로 붙이는
     몬테카를로(1,000회)로 "동 비율이 만들 수 있는 순위 변화의 크기"를 본다 [추정, 실제 배정 아님]
  3) 방법 D(이름 연결판): 정류장 이름 토큰이 D17 역 이름(+역/번출구/입구)과 정확히 같으면 그 역의 우대권 비율(2025-08)을 붙인다
  4) 방법 C: D20 경로 버스 승차/일 총량을 D12 65+ 이동량 비율로 자치구에 나누고, 구 안 정류장에 승차 비율로 배분 → A-구와 비교
출력(outputs/eda_bus65/): rank_within_gu_check.csv, rank_A_dong_montecarlo.csv, method_D_jongno_matched.csv,
      method_C_vs_A_gu.csv, rank_summary.csv, fig_rank_methods.png
실행: python outputs/eda_bus65/s07_method_ranking.py
"""
from pathlib import Path
import re
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[2]; RAW = ROOT / "data/raw"; OUT = ROOT / "outputs/eda_bus65"
plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e", "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb", "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": .6})
C1, C2 = "#2a78d6", "#eb6834"
H = list(range(10, 17)); NDAY = 31; rng = np.random.default_rng(20251102)
rho = lambda a, b: spearmanr(a, b).statistic
overlap = lambda a, b, k=20: len(set(a.nlargest(k).index) & set(b.nlargest(k).index))
summary = []

# 서울 정류장(ARS 01~25) × 시각 승차, 2025-08
b = pd.read_csv(RAW / "D16_bus_hourly/2025년_버스노선별_정류장별_시간대별_승하차_인원_정보(08월).csv", encoding="cp949", dtype=str)
bc = {int(c.split("시")[0]): c for c in b.columns if c.endswith("승차총승객수")}
b[list(bc.values())] = b[list(bc.values())].apply(pd.to_numeric)
b = b[b.버스정류장ARS번호 != "~"].copy(); b["ars"] = b.버스정류장ARS번호.str.zfill(5)
b = b[b.ars.str[:2].astype(int).between(1, 25)]
S = b.groupby("ars").agg(name=("역명", lambda s: re.sub(r"\(\d+\)$", "", s.iloc[0])), **{f"h{h}": (bc[h], "sum") for h in H})
S["board"] = S[[f"h{h}" for h in H]].sum(1); S["gu"] = "11" + S.index.str[:2] + "0"; S = S[S.board > 0]

# D12: 자치구·동 × 시각 65+ 비율(상한: 별표 = 0)
d12 = pd.read_csv(OUT / "d12_dep_dong_hour.csv", dtype={"dong7": str}); d12 = d12[d12.hour.isin(H)]
d12["gu"] = d12.dong7.str[:5]
gh = d12.pivot_table(index=["gu", "hour"], columns="ag", values="v", aggfunc="sum"); gh["s"] = gh["65p"] / (gh["65p"] + gh["u65"])
g = d12.pivot_table(index="gu", columns="ag", values="v", aggfunc="sum"); g["s"] = g["65p"] / (g["65p"] + g["u65"])

# ---------- 1) A-구: 시각별 비율 적용 ----------
S["A_gu"] = sum(S[f"h{h}"] * S.gu.map(gh.s.xs(h, level="hour")) for h in H) / NDAY
S["A_gu_const"] = S.board * S.gu.map(g.s) / NDAY
w = S.groupby("gu").apply(lambda x: pd.Series({"n": len(x), "rho_A_const_vs_board": rho(x.board, x.A_gu_const), "rho_A_hour_vs_board": rho(x.board, x.A_gu)}))
w.to_csv(OUT / "rank_within_gu_check.csv", encoding="utf-8-sig")
print("[1] 구 안 순위 상관: 상수 비율 최소 %.4f, 시각별 비율 최소 %.4f" % (w.rho_A_const_vs_board.min(), w.rho_A_hour_vs_board.min()))
summary += [dict(method="A-구(상수)", scope="구 안", rho_vs_board=w.rho_A_const_vs_board.min(), note="25개 구 중 최소값"),
            dict(method="A-구(시각별)", scope="구 안", rho_vs_board=w.rho_A_hour_vs_board.min(), note="25개 구 중 최소값")]

# ---------- 2) A-동 몬테카를로 (종로구) ----------
J = S[S.gu == "11010"].copy()
dh = d12[d12.gu == "11010"].pivot_table(index=["dong7", "hour"], columns="ag", values="v", aggfunc="sum")
dh["s"] = dh["65p"] / (dh["65p"] + dh["u65"]); SH = dh.s.unstack("hour")[H]          # 동 × 시각
dongs = SH.index.values; res = []
for i in range(1000):
    pick = rng.choice(dongs, size=len(J))
    est = pd.Series((J[[f"h{h}" for h in H]].values * SH.loc[pick].values).sum(1), index=J.index)
    res.append(dict(rho=rho(J.board, est), top20=overlap(J.board, est)))
R = pd.DataFrame(res); R.to_csv(OUT / "rank_A_dong_montecarlo.csv", index=False)
dsh = (SH.mul(J[[f"h{h}" for h in H]].sum().values, axis=1).sum(1) / J[[f"h{h}" for h in H]].sum().sum())
print("[2] 종로구 동 %d개 10~16시 65+ 비율(상한) %.3f~%.3f (최대/최소 %.2f배); 정류장 승차 최대/중앙값 %.0f배" % (
    len(dongs), dsh.min(), dsh.max(), dsh.max() / dsh.min(), J.board.max() / J.board.median()))
print("    무작위 배정 1,000회: ρ 중앙값 %.3f (5%% %.3f), 상위 20 겹침 중앙값 %d (5%% %d)" % (R.rho.median(), R.rho.quantile(.05), R.top20.median(), R.top20.quantile(.05)))
summary.append(dict(method="A-동(무작위 배정 시뮬레이션)", scope=f"종로구 {len(J)}", rho_vs_board=R.rho.median(), top20_overlap=R.top20.median(),
                    note=f"ρ 5%={R.rho.quantile(.05):.3f}, 겹침 5%={R.top20.quantile(.05):.0f}; 실제 정류장→동 연결 아님"))

# ---------- 3) D: 이름으로 역 연결 (종로구) ----------
st = pd.read_csv(OUT / "q2_station_ratio_summer2025.csv", dtype={"code": str})
st["base"] = st.역명.str.replace(r"\(.*\)$", "", regex=True)
# 같은 이름(환승역 여러 호선)은 2025-08 승차 가중 평균
st["w8"] = st.r_202508 * 1.0
sr = st.groupby("base").apply(lambda x: np.average(x.r_202508, weights=x.total))
names = sorted(sr.index, key=len, reverse=True)
def match(n):
    for t in re.split(r"[.·]", n):
        for s in names:
            if re.fullmatch(re.escape(s) + r"(역)?(\d+번출구)?(입구)?", t): return s
    return None
J["station"] = J.name.apply(match); J["st_ratio"] = J.station.map(sr)
Jm = J[J.station.notna()].copy()
Jm["D"] = Jm.board * Jm.st_ratio
Jm[["name", "station", "st_ratio", "board", "A_gu", "D"]].sort_values("D", ascending=False).to_csv(OUT / "method_D_jongno_matched.csv", encoding="utf-8-sig")
rD = rho(Jm.board, Jm.D); oD = overlap(Jm.board, Jm.D, 10)
print("[3] 이름 연결 %d/%d 정류장, 10~16시 승차의 %.1f%%; 역 우대권 비율 %.3f~%.3f; ρ(D, 승차)=%.3f, 상위 10 겹침 %d/10" % (
    len(Jm), len(J), 100 * Jm.board.sum() / J.board.sum(), Jm.st_ratio.min(), Jm.st_ratio.max(), rD, oD))
# 같은 부분집합에서 A-동 무작위 배정과 비교
idx = [J.index.get_loc(i) for i in Jm.index]; rs = []
for i in range(1000):
    pick = rng.choice(dongs, size=len(Jm))
    est = pd.Series((Jm[[f"h{h}" for h in H]].values * SH.loc[pick].values).sum(1), index=Jm.index)
    rs.append(dict(rho=rho(Jm.board, est), top10=overlap(Jm.board, est, 10)))
Rs = pd.DataFrame(rs)
summary += [dict(method="D(역 이름 연결)", scope=f"종로구 {len(Jm)}", rho_vs_board=rD, top10_overlap=oD, note="승차 상위 10 대비"),
            dict(method="A-동(무작위, 같은 부분집합)", scope=f"종로구 {len(Jm)}", rho_vs_board=Rs.rho.median(), top10_overlap=Rs.top10.median(), note="")]

# ---------- 4) C: D20 총량 배분 vs A-구 ----------
C20 = pd.read_csv(OUT / "q1_d20_compare.csv", index_col=0)["value"]
d12all = pd.read_csv(OUT / "d12_dep_dong_hour.csv", dtype={"dong7": str})
f1016 = d12all[(d12all.ag == "65p") & d12all.hour.isin(H)].v.sum() / d12all[d12all.ag == "65p"].v.sum()
T = C20["D20_서울버스구간_승차/일_경로"] * f1016                       # 서울 전체 65+ 버스 승차/일, 10~16시 [추정]
g["T_gu"] = T * g["65p"] / g["65p"].sum()
bg = S.groupby("gu").board.sum() / NDAY
S["C"] = S.board / NDAY * S.gu.map(g.T_gu / bg)
g["mult_A"] = g.s; g["mult_C"] = g.T_gu / bg
g.assign(name=None).to_csv(OUT / "method_C_vs_A_gu.csv", encoding="utf-8-sig")
print("[4] 총량: A-구 %.0f명/일 vs C %.0f명/일 (10~16시, 서울 ARS 01~25 정류장 %d개); 10~16시 비중 f=%.3f" % (S.A_gu_const.sum(), S.C.sum(), len(S), f1016))
print("    구 배수 상관 ρ(A, C)=%.3f; 서울 전체 정류장 ρ(A, C)=%.4f, ρ(A, 승차)=%.4f, ρ(C, 승차)=%.4f; 상위 100 겹침 A–C %d" % (
    rho(g.mult_A, g.mult_C), rho(S.A_gu_const, S.C), rho(S.A_gu_const, S.board), rho(S.C, S.board), overlap(S.A_gu_const, S.C, 100)))
summary += [dict(method="A-구(상수)", scope=f"서울 {len(S)}", rho_vs_board=rho(S.A_gu_const, S.board), top100_overlap_vs_board=overlap(S.A_gu_const, S.board, 100), total_per_day=S.A_gu_const.sum()),
            dict(method="C(D20 총량 → 구 → 정류장)", scope=f"서울 {len(S)}", rho_vs_board=rho(S.C, S.board), top100_overlap_vs_board=overlap(S.C, S.board, 100), total_per_day=S.C.sum(),
                 note=f"ρ(A,C)={rho(S.A_gu_const, S.C):.4f}, 상위100 겹침 A–C={overlap(S.A_gu_const, S.C, 100)}")]
pd.DataFrame(summary).to_csv(OUT / "rank_summary.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(summary).round(4).to_string())

fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
ax = axs[0]
rows = [(f"A-구 (종로 {len(J)}개)", 1.0, 1.0, 1.0, "#52514e"),
        (f"A-동 무작위 (종로 {len(J)}개)", R.rho.median(), R.rho.quantile(.05), R.rho.quantile(.95), C1),
        (f"A-동 무작위 (이름 연결 {len(Jm)}개)", Rs.rho.median(), Rs.rho.quantile(.05), Rs.rho.quantile(.95), C1),
        (f"D 역 우대권 비율 (이름 연결 {len(Jm)}개)", rD, rD, rD, C2)]
for i, (lab, m, lo, hi, col) in enumerate(rows):
    ax.plot([lo, hi], [i, i], color=col, lw=2); ax.plot(m, i, "o", color=col, ms=8, mec="#fcfcfb", mew=2)
    ax.text(m - .004, i + .22, f"{m:.3f}", fontsize=8.5, color="#0b0b0b", ha="right")
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows], fontsize=8.5); ax.set_ylim(-.6, len(rows) - .4)
ax.set_xlabel("정류장 승차 순위와의 스피어만 ρ (선 = 무작위 1,000회의 5~95%)"); ax.grid(axis="y", visible=False)
ax.set_title("종로구: 지역·역 비율이 승차 순위를 얼마나 바꾸나", fontsize=10.5, loc="left")
ax = axs[1]
ax.scatter(g.mult_A * 100, g.mult_C * 100, s=22, color=C1, edgecolor="#fcfcfb", linewidth=.5)
for k, r in g.iterrows():
    if k in ("11010", "11230", "11120", "11210"): ax.annotate({"11010": "종로", "11230": "강남", "11120": "은평", "11210": "관악"}[k], (r.mult_A * 100, r.mult_C * 100), fontsize=8, color="#52514e", xytext=(4, 2), textcoords="offset points")
ax.set_xlabel("A-구 배수: D12 65+ 비율 (%, 10~16시)"); ax.set_ylabel("C 배수: 배분된 65+ 승차 / 승차 (%)")
ax.set_title(f"자치구 배수 비교 (n=25, ρ={rho(g.mult_A, g.mult_C):.2f})", fontsize=10.5, loc="left")
fig.tight_layout(); fig.savefig(OUT / "fig_rank_methods.png", dpi=150); plt.close(fig)

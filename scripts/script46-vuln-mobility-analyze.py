"""
script46-vuln-mobility-analyze.py - 취약계층 유동성 분석 표·그림·판정 (사전등록 docs/preregistration.md §7)

입력: rq1_followup/out/step5_vuln/stage/ (script45 산출), date_types.csv (script44), 2016 행정동 경계
출력: rq1_followup/out/step5_vuln/ 아래 표(csv), 그림(png), 판정 요약(json), RESULTS_tables.md
판정 기준(사전 고정): Spearman ρ ≥ 0.8 비슷함, 0.6~0.8 부분적으로 비슷함, < 0.6 다름. 판정은 하한 기준, 상한에서 달라지면 함께 표시.
실행: PYTHONDONTWRITEBYTECODE=1 python scripts/script46-vuln-mobility-analyze.py
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
OUT = ROOT / "rq1_followup/out/step5_vuln"; ST = OUT / "stage"; FIG = OUT / "fig"; TAB = OUT / "tables"
FIG.mkdir(exist_ok=True); TAB.mkdir(exist_ok=True)
MAIN = ["0-14", "15-64", "65+"]; SUB = ["0-9", "10-14", "15-19", "20-34", "35-49", "50-64", "65-69", "70+"]; ALLG = MAIN + SUB
TYPES = {"SW": "학기 평일", "VW": "방학 평일", "SAT": "토요일", "SUN": "일요일·공휴일", "WD": "평일(학기+방학)", "VWc": "방학 평일(핵심)"}
fname = lambda g: g.replace("+", "p").replace("-", "_")
judge = lambda r: "비슷함" if r >= 0.8 else ("부분적으로 비슷함" if r >= 0.6 else "다름")
TOP, TOP10 = 20, 43


def load(kind):
    fs = [(g, b, ST / f"{kind}__{fname(g)}__{b}.parquet") for g in ALLG for b in ("lo", "hi")]
    miss = [str(f.name) for *_, f in fs if not f.exists()]
    if miss: raise SystemExit(f"stage 파일 없음 {len(miss)}개: script45를 먼저 끝낼 것 ({miss[:3]}...)")
    return pd.concat([pd.read_parquet(f).assign(g=g, b=b) for g, b, f in fs], ignore_index=True)


MB, HS, DG, WN, PS, PH = (load(k) for k in ("mbar", "hstar", "dong", "win", "persist", "persisthour"))
HS["hs"] = HS.hstar.apply(json.loads)
from rq1_modules.common import dong_names, GU
NAMES = dong_names()
nm = lambda d: NAMES.get(d, d)


def hstar(g, b, s, thr=0.8):
    r = HS[(HS.g == g) & (HS.b == b) & (HS.set == s) & (HS.thr == thr)].iloc[0]
    return r.hs, int(r.peak_hour), float(r.peak)


def dong(g, b, s, thr=0.8):
    d = DG[(DG.g == g) & (DG.b == b) & (DG.set == s) & (DG.thr == thr)].copy()
    q10 = np.percentile(d.P3_mean, 10); d["lq_excl"] = d.P3_mean < q10
    d = d.sort_values(["N_mean", "dong"], ascending=[False, True]); d["rank_N"] = range(1, len(d) + 1)
    k = d[~d.lq_excl].sort_values(["LQ_mean", "dong"], ascending=[False, True]); d["rank_LQ"] = np.nan
    d.loc[k.index, "rank_LQ"] = range(1, len(k) + 1)
    return d.set_index("dong")


def top(d, col="N_mean", n=TOP):
    x = d if col == "N_mean" else d[~d.lq_excl]
    return list(x.sort_values([col], ascending=False, kind="mergesort").index[:n]) if col != "N_mean" else list(d.sort_values("rank_N").index[:n])


def cmp(a, b, col="N_mean", n=TOP):
    idx = a.index.intersection(b.index); r = spearmanr(a.loc[idx, col], b.loc[idx, col]).statistic
    ta, tb = set(top(a, col, n)), set(top(b, col, n))
    return dict(rho=float(r), overlap=len(ta & tb), jaccard=len(ta & tb) / len(ta | tb), judge=judge(r))


R = {}
# ---------------- 질문 1 ----------------
rows = []
for g in ALLG:
    for t in ("SW", "VW", "SAT", "SUN"):
        s = f"{t}|all|all"; e = {}
        for b in ("lo", "hi"):
            h8, ph, pk = hstar(g, b, s, .8); h7, *_ = hstar(g, b, s, .7); h9, *_ = hstar(g, b, s, .9)
            e[b] = dict(peak_hour=ph, peak=pk, H80=h8, H70=h7, H90=h9)
        rows.append(dict(age=g, type=TYPES[t], peak_hour=e["lo"]["peak_hour"], peak_M=round(e["lo"]["peak"], 4),
                         H80=e["lo"]["H80"], H70=e["lo"]["H70"], H90=e["lo"]["H90"],
                         peak_hour_hi=e["hi"]["peak_hour"], peak_M_hi=round(e["hi"]["peak"], 4), H80_hi=e["hi"]["H80"],
                         H80_same_lo_hi=e["lo"]["H80"] == e["hi"]["H80"]))
Q1 = pd.DataFrame(rows); Q1.to_csv(TAB / "q1_peak_hstar.csv", index=False, encoding="utf-8-sig")
MB.to_csv(TAB / "q1_mbar_curves_all_sets.csv", index=False, encoding="utf-8-sig")
q1ja = []
for g in MAIN:
    for t in ("SW", "VW"):
        for b in ("lo", "hi"):
            a, *_ = hstar(g, b, f"{t}|all|all"); j, *_ = hstar(g, b, f"{t}|JA|all")
            q1ja.append(dict(age=g, type=TYPES[t], bound=b, H80_6to9=a, H80_7to8=j, same=a == j))
pd.DataFrame(q1ja).to_csv(TAB / "q1_sens_julaug.csv", index=False, encoding="utf-8-sig")
R["q1_lohi_diff"] = Q1[~Q1.H80_same_lo_hi][["age", "type", "H80", "H80_hi"]].to_dict("records")
R["q1_julaug"] = q1ja

# 그림: 날짜 유형별 주구간 곡선 + IQR
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
COL = {"0-14": "#e67e22", "15-64": "#7f8c8d", "65+": "#8e44ad"}
NOTE = "내국인 생활인구, 2024·2025년 6~9월(242일), 하한(별표=0). 음영 = 날짜 간 IQR. 기준 = 같은 날 03시."
for t in ("SW", "VW", "SAT", "SUN"):
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for g in MAIN:
        m = MB[(MB.g == g) & (MB.b == "lo") & (MB.set == f"{t}|all|all")].sort_values("hour")
        h8, ph, pk = hstar(g, "lo", f"{t}|all|all")
        ax.plot(m.hour, m["mean"], "-o", ms=3, color=COL[g], label=f"{g} (최대 {ph:02d}시, H* {min(h8):02d}~{max(h8):02d}시)")
        ax.fill_between(m.hour, m.p25, m.p75, color=COL[g], alpha=.18)
    ax.set_xticks(range(24)); ax.set_xlabel("시각"); ax.set_ylabel("이동 강도 M 평균(h)"); ax.grid(alpha=.3); ax.legend()
    ax.set_title(f"{TYPES[t]}: 연령별 이동 강도 (03시 대비 재배치 비율)")
    fig.text(.5, -.02, NOTE, ha="center", fontsize=8.5)
    fig.savefig(FIG / f"q1_M_curve_{t}.png", dpi=150, bbox_inches="tight"); plt.close(fig)
fig, axs = plt.subplots(2, 4, figsize=(18, 8), sharey=True)
for ax, g in zip(axs.ravel(), SUB):
    m = MB[(MB.g == g) & (MB.b == "lo") & (MB.set == "SW|all|all")].sort_values("hour"); h8, ph, pk = hstar(g, "lo", "SW|all|all")
    ax.plot(m.hour, m["mean"], "-", color="#2c6fbb"); ax.fill_between(m.hour, m.p25, m.p75, color="#2c6fbb", alpha=.2)
    ax.axvspan(min(h8) - .5, max(h8) + .5, color="#f1c40f", alpha=.15)
    ax.set_title(f"{g}{' (대체값)' if g == '0-9' else ''}: 최대 {ph:02d}시, H* {min(h8):02d}~{max(h8):02d}시", fontsize=10)
    ax.set_xticks(range(0, 24, 3)); ax.grid(alpha=.3)
fig.suptitle("학기 평일: 세분 연령 8개 이동 강도 M 평균(h) (노란 띠 = H* 80%)", fontsize=13)
fig.text(.5, .01, NOTE + " 0-9세는 10-14세 × 주민등록 비율 대체값.", ha="center", fontsize=8.5)
fig.savefig(FIG / "q1_M_curve_sub8_SW.png", dpi=150, bbox_inches="tight"); plt.close(fig)

# ---------------- 질문 2 ----------------
q2rows, q2ov, q2lh, q2ja = [], [], [], []
for g in ALLG:
    for t in ("SW", "VW", "SAT", "SUN"):
        s = f"{t}|all|all"; dl, dh = dong(g, "lo", s), dong(g, "hi", s)
        tn, tl = top(dl, "N_mean"), top(dl, "LQ_mean")
        for kind, lst in (("N", tn), ("LQ", tl)):
            for i, d in enumerate(lst, 1):
                r = dl.loc[d]
                q2rows.append(dict(age=g, type=TYPES[t], 기준=kind, 순위=i, 행정동코드=d, 동=nm(d), 자치구=GU.get(d[:5], d[:5]),
                                   N_mean=round(r.N_mean, 1), LQ_mean=round(r.LQ_mean, 3), P3_mean=round(r.P3_mean, 1),
                                   rank_N=int(r.rank_N), rank_LQ=None if pd.isna(r.rank_LQ) else int(r.rank_LQ),
                                   N_p25=round(r.N_p25, 1), N_p75=round(r.N_p75, 1)))
        both = [d for d in tn if d in set(tl)]; x = dl[~dl.lq_excl]
        q2ov.append(dict(age=g, type=TYPES[t], overlap=len(both), jaccard=round(len(both) / len(set(tn) | set(tl)), 3),
                         rho_N_LQ=round(float(spearmanr(x.N_mean, x.LQ_mean).statistic), 3), 겹치는동=", ".join(nm(d) for d in both),
                         lq_excluded=int(dl.lq_excl.sum())))
        q2lh.append(dict(age=g, type=TYPES[t], N_top20_changed=TOP - len(set(tn) & set(top(dh, "N_mean"))),
                         LQ_top20_changed=TOP - len(set(tl) & set(top(dh, "LQ_mean")))))
        if g in MAIN:
            dj = dong(g, "lo", f"{t}|JA|all"); c = cmp(dl, dj)
            q2ja.append(dict(age=g, type=TYPES[t], top20_overlap_6to9_vs_7to8=c["overlap"], rho=round(c["rho"], 3), judge=c["judge"]))
pd.DataFrame(q2rows).to_csv(TAB / "q2_top20_N_LQ.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(q2ov).to_csv(TAB / "q2_overlap_N_vs_LQ.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(q2lh).to_csv(TAB / "q2_lo_vs_hi_top20_changes.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(q2ja).to_csv(TAB / "q2_sens_julaug.csv", index=False, encoding="utf-8-sig")
R["q2_overlap"] = q2ov; R["q2_lohi"] = q2lh; R["q2_julaug"] = q2ja
# 지도
import geopandas as gpd
from rq1_modules.common import P as CP
B = gpd.read_file(CP["boundary"]).set_crs(5179, allow_override=True); B["dong"] = B.TOT_REG_CD.astype(str).str[:7]
G = B[["dong", "geometry"]].dissolve(by="dong").reset_index()
from matplotlib.colors import TwoSlopeNorm, LogNorm
mp = {g: dong(g, "lo", "SW|all|all") for g in MAIN}
nmax = max(np.percentile(np.abs(mp[g].N_mean), 98) for g in MAIN)
lqs = np.concatenate([mp[g][~mp[g].lq_excl].LQ_mean.values for g in MAIN]); lqs = lqs[lqs > 0]
l_lo, l_hi = np.percentile(lqs, 2), np.percentile(lqs, 98); L = max(1 / l_lo, l_hi)
for metric, cmap, norm, lab in (("N_mean", "RdBu_r", TwoSlopeNorm(0, -nmax, nmax), "N 평균 (명, 03시 대비 순유입)"),
                                ("LQ_mean", "RdBu_r", LogNorm(1 / L, L), "LQ 평균 (로그 눈금, 1 = 03시와 같은 비중)")):
    fig, axs = plt.subplots(1, 3, figsize=(20, 6.5))
    for ax, g in zip(axs, MAIN):
        d = mp[g].reset_index(); x = G.merge(d, on="dong", how="left")
        if metric == "LQ_mean": x.loc[x.lq_excl == True, metric] = np.nan
        x.plot(column=metric, ax=ax, cmap=cmap, norm=norm, edgecolor="#bbbbbb", linewidth=.15, missing_kwds={"color": "#e6e6e6"})
        h8, *_ = hstar(g, "lo", "SW|all|all"); ax.set_title(f"{g} (H* {min(h8):02d}~{max(h8):02d}시 평균)", fontsize=12); ax.axis("off")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm); cb = fig.colorbar(sm, ax=axs, shrink=.7, label=lab)
    if metric == "LQ_mean":
        tk = [t for t in (0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4) if 1 / L <= t <= L]; cb.set_ticks(tk); cb.set_ticklabels([f"{t:g}" for t in tk]); cb.ax.minorticks_off()
    fig.suptitle(f"학기 평일: 연령별 {'순유입 N 평균' if metric == 'N_mean' else '집중 지수 LQ 평균'} (세 연령 같은 색 범위)", fontsize=13)
    fig.text(.45, .02, NOTE.replace(" 음영 = 날짜 간 IQR.", "") + (" 회색 = 03시 인구 하위 10% 제외 동." if metric == "LQ_mean" else ""), ha="center", fontsize=8.5)
    fig.savefig(FIG / f"q2_map_{'N' if metric == 'N_mean' else 'LQ'}_SW.png", dpi=150, bbox_inches="tight"); plt.close(fig)


# ---------------- 분석 1 ----------------
def curve(g, b, s):
    return MB[(MB.g == g) & (MB.b == b) & (MB.set == s)].set_index("hour")["mean"]


def a1(g, sa, sb, b):
    ca, cb = curve(g, b, sa), curve(g, b, sb); c = cmp(dong(g, b, sa), dong(g, b, sb))
    return dict(peak_shift_h=int(cb.idxmax() - ca.idxmax()), peak_A=int(ca.idxmax()), peak_B=int(cb.idxmax()),
                peak_diff=float(cb.max() - ca.max()), max_abs_diff=float((cb - ca).abs().max()), **c)


A1 = []
pairs = [(g, "SW", "VW") for g in ("10-14", "15-19")] + [(g, x, y) for g in ("65+", "65-69", "70+") for x, y in (("WD", "SAT"), ("WD", "SUN"), ("SAT", "SUN"))]
for g, x, y in pairs:
    for b in ("lo", "hi"):
        A1.append(dict(age=g, A=TYPES[x], B=TYPES[y], bound=b, 기간="6~9월", **a1(g, f"{x}|all|all", f"{y}|all|all", b)))
for b in ("lo", "hi"):
    A1.append(dict(age="10-14", A=TYPES["SW"], B=TYPES["VWc"], bound=b, 기간="6~9월(방학 핵심)", **a1("10-14", "SW|all|all", "VWc|all|all", b)))
    for g in ("10-14", "15-19"):
        A1.append(dict(age=g, A=TYPES["SW"], B=TYPES["VW"], bound=b, 기간="7~8월", **a1(g, "SW|JA|all", "VW|JA|all", b)))
A1 = pd.DataFrame(A1); A1.to_csv(TAB / "a1_daytype_compare.csv", index=False, encoding="utf-8-sig")

# ---------------- 분석 2 ----------------
def win(g, b, w):
    d = WN[(WN.g == g) & (WN.b == b) & (WN.window == w)].set_index("dong")
    return d.sort_values(["N_mean"], ascending=False)


A2, A2new = [], []
for g in MAIN:
    for b in ("lo", "hi"):
        W = {w: win(g, b, w) for w in ("오전", "점심", "오후")}; T = {w: list(W[w].index[:TOP]) for w in W}
        for x, y in (("오전", "점심"), ("점심", "오후"), ("오전", "오후")):
            idx = W[x].index.intersection(W[y].index); r = float(spearmanr(W[x].loc[idx, "N_mean"], W[y].loc[idx, "N_mean"]).statistic)
            A2.append(dict(age=g, bound=b, A=x, B=y, overlap=len(set(T[x]) & set(T[y])), rho=r, judge=judge(r)))
        if b == "lo":
            for x, y in (("오전", "점심"), ("점심", "오후")):
                A2new.append(dict(age=g, window=y, 새로등장=", ".join(nm(d) for d in T[y] if d not in set(T[x]))))
            for w in W:
                for i, d in enumerate(T[w], 1): A2new.append(dict(age=g, window=w, 순위=i, 동=nm(d), 자치구=GU.get(d[:5]), N_mean=round(W[w].loc[d, "N_mean"], 1)))
pd.DataFrame(A2).to_csv(TAB / "a2_windows.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(A2new).to_csv(TAB / "a2_windows_top20.csv", index=False, encoding="utf-8-sig")

# ---------------- 분석 3 ----------------
A3 = []
for g in ("0-14", "65+", "10-14", "65-69", "70+"):
    for b in ("lo", "hi"):
        c = cmp(dong(g, b, "SW|all|all"), dong("15-64", b, "SW|all|all"), n=TOP10)
        a, z = win(g, b, "14시"), win("15-64", b, "14시"); idx = a.index.intersection(z.index)
        r14 = float(spearmanr(a.loc[idx, "N_mean"], z.loc[idx, "N_mean"]).statistic); o14 = len(set(a.index[:TOP10]) & set(z.index[:TOP10]))
        A3.append(dict(age=g, vs="15-64", bound=b, rho_Hstar=c["rho"], top10pct_overlap_Hstar=c["overlap"], judge_Hstar=c["judge"],
                       rho_14h=r14, top10pct_overlap_14h=o14, judge_14h=judge(r14)))
pd.DataFrame(A3).to_csv(TAB / "a3_vuln_vs_15_64.csv", index=False, encoding="utf-8-sig")

# ---------------- 분석 4 ----------------
A4 = []
for g in MAIN:
    for b in ("lo", "hi"):
        c = cmp(dong(g, b, "SW|all|2024"), dong(g, b, "SW|all|2025")); h4, *_ = hstar(g, b, "SW|all|2024"); h5, *_ = hstar(g, b, "SW|all|2025")
        A4.append(dict(age=g, bound=b, H80_2024=h4, H80_2025=h5, Hstar_same=h4 == h5, **c))
pd.DataFrame(A4).to_csv(TAB / "a4_year_compare.csv", index=False, encoding="utf-8-sig")

# ---------------- 분석 5 (탐색) ----------------
A5 = []
for g in MAIN:
    d = dong(g, "lo", "SW|all|all"); p = PS[(PS.g == g) & (PS.b == "lo")].set_index("dong")
    p = p.loc[[x for x in p.index if x in d.index and not d.loc[x, "lq_excl"]]].sort_values("hours_mean", ascending=False)
    ph = PH[(PH.g == g) & (PH.b == "lo")]
    for i, x in enumerate(p.index[:TOP], 1):
        hs = sorted(ph[(ph.dong == x) & (ph.frac >= 0.5)].hour)
        A5.append(dict(age=g, 순위=i, 동=nm(x), 자치구=GU.get(x[:5]), 평균지속시간=round(p.loc[x, "hours_mean"], 2),
                       지속시간대=f"{min(hs):02d}~{max(hs):02d}시" if hs else "-"))
pd.DataFrame(A5).to_csv(TAB / "a5_persistence_top20.csv", index=False, encoding="utf-8-sig")

# ---------------- 분석 6 (탐색) ----------------
from scipy.cluster.hierarchy import linkage, dendrogram
from scipy.spatial.distance import squareform
CM = pd.DataFrame({g: curve(g, "lo", "SW|all|all") for g in SUB}).corr()
NN = pd.DataFrame({g: dong(g, "lo", "SW|all|all").N_mean for g in SUB}).corr(method="spearman")
CM.to_csv(TAB / "a6_corr_Mcurve_pearson.csv", encoding="utf-8-sig"); NN.to_csv(TAB / "a6_corr_N_spearman.csv", encoding="utf-8-sig")
fig, axs = plt.subplots(1, 2, figsize=(14, 5))
for ax, (M, t) in zip(axs, ((CM, "M 평균(h) 곡선 피어슨 상관"), (NN, "N 평균 동별 순위 상관"))):
    Z = linkage(squareform(np.clip(1 - M.values, 0, None), checks=False), "average")
    dendrogram(Z, labels=list(M.index), ax=ax); ax.set_title(f"{t} (거리 = 1 - r, 평균 연결)"); ax.set_ylabel("1 - r")
fig.text(.5, -.03, "학기 평일, 하한. 0-9세는 10-14세 대체값이라 10-14와 상관이 1에 가까운 것이 정상.", ha="center", fontsize=9)
fig.savefig(FIG / "a6_dendrograms.png", dpi=150, bbox_inches="tight"); plt.close(fig)
R["a6_6569"] = {"M_corr_with_50_64": float(CM.loc["65-69", "50-64"]), "M_corr_with_70p": float(CM.loc["65-69", "70+"]),
                "N_rho_with_50_64": float(NN.loc["65-69", "50-64"]), "N_rho_with_70p": float(NN.loc["65-69", "70+"]),
                "corr_0_9_vs_10_14_M": float(CM.loc["0-9", "10-14"]), "rho_0_9_vs_10_14_N": float(NN.loc["0-9", "10-14"])}

# ---------------- 견고성: 0.7/0.9 ----------------
RB = []
for g in MAIN:
    for t in ("SW", "VW", "SAT", "SUN"):
        d8 = dong(g, "lo", f"{t}|all|all", .8)
        for th in (.7, .9):
            c = cmp(d8, dong(g, "lo", f"{t}|all|all", th)); RB.append(dict(age=g, type=TYPES[t], thr=th, top20_overlap_vs_0p8=c["overlap"], rho=c["rho"]))
pd.DataFrame(RB).to_csv(TAB / "robust_thr_top20.csv", index=False, encoding="utf-8-sig")
json.dump(R, open(OUT / "summary.json", "w"), ensure_ascii=False, indent=1, default=str)
print("완료: 표", len(list(TAB.glob("*.csv"))), "개, 그림", len(list(FIG.glob("*.png"))), "개")

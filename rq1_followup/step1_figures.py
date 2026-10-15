"""1단계(절대 기온) 시각 자료. 새 분석·재계산 없이 rq1_followup/out/step1 의 기존 결과만 그린다.

입력 (모두 기존 파일)
  out/step1/gu25_rank_abs_vs_dT.csv   자치구 25개 낮·밤 ΔT 순위, 절대 기온 순위
  out/step1/step1_dong.csv            행정동 '2024+2025' 행의 dT_day_mean, abs_day_mean, name
  out/step1/_ked_cache.pkl (rec108)   종로 108 집계구 대표점의 매시각 배경 기온·절대 기온 추정치 (step1 실행 때 저장된 값)
  merged_data/D3_asos108/asos108_2024_2025.parquet   ASOS 108 실측 (step1 홀드아웃과 같은 입력)
  merged_data/D9_boundary/bnd_oa_11_2016_4Q          지도 경계(2016 집계구 → 앞 7자리로 행정동 424개)
출력: out/step1_fig/fig1_gu_slope.png, fig2_dong_dT_vs_abs_day.png, fig3_holdout108_hourly.png, captions.md
실행: PYTHONDONTWRITEBYTECODE=1 python3 rq1_followup/step1_figures.py
"""
import pickle, json
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
S1 = ROOT / "rq1_followup/out/step1"; OUT = ROOT / "rq1_followup/out/step1_fig"; OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
CAVEAT = "단서: 절대 기온은 그 센서가 잰 기온이며 설치 환경 차이(1.2–2.0°C) 포함. 동 단위 값은 하한, 집계구는 상한."
SHIFT = 8
check = {}


def fig1():
    g = pd.read_csv(S1 / "gu25_rank_abs_vs_dT.csv")
    fig, axs = plt.subplots(1, 2, figsize=(12, 9))
    moved = {}
    for ax, p, ttl in zip(axs, ("day", "night"), ("낮(07–20시)", "밤(21–06시)")):
        L, R = g[f"rank_dT_{p}"], g[f"rank_abs_{p}"]
        big = (L - R).abs() >= SHIFT; moved[p] = sorted(g.name[big].tolist())
        for (_, r), b in zip(g.iterrows(), big):
            a, z = r[f"rank_dT_{p}"], r[f"rank_abs_{p}"]
            if b:
                col = "#c0392b" if z < a else "#2c6fbb"
                ax.plot([0, 1], [a, z], color=col, lw=2.6, zorder=3)
                ax.text(-0.03, a, f"{r['name']} {a}", ha="right", va="center", fontsize=9, color=col, fontweight="bold")
                ax.text(1.03, z, f"{z} {r['name']}", ha="left", va="center", fontsize=9, color=col, fontweight="bold")
            else:
                ax.plot([0, 1], [a, z], color="#c8c8c8", lw=1.1, zorder=1)
        ax.set_ylim(25.8, 0.2); ax.set_xlim(-0.45, 1.45); ax.set_xticks([0, 1]); ax.set_xticklabels(["ΔT 순위", "절대 기온 순위"], fontsize=11)
        ax.set_yticks([1, 5, 10, 15, 20, 25]); ax.set_title(f"{ttl}: 순위 {SHIFT}단계 이상 바뀐 구 {int(big.sum())}곳", fontsize=12)
        for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.suptitle("자치구 25개: ΔT 순위 → 절대 기온 순위 (1 = 가장 더움, 2024·2025 여름 평균)", fontsize=13)
    fig.text(.5, .02, "빨강 = 절대 기온으로 더 더운 쪽으로 이동, 파랑 = 덜 더운 쪽으로 이동, 회색 = 변화 8단계 미만. " + CAVEAT, ha="center", fontsize=8.5, wrap=True)
    fig.savefig(OUT / "fig1_gu_slope.png", dpi=150, bbox_inches="tight"); plt.close(fig)
    check["fig1"] = dict(moved=moved, rows=len(g))
    return moved


def fig2():
    import geopandas as gpd
    d = pd.read_csv(S1 / "step1_dong.csv", dtype={"dong7": str, "year": str}); d = d[d.year == "2024+2025"]
    B = gpd.read_file(ROOT / "merged_data/D9_boundary/bnd_oa_11_2016_4Q/bnd_oa_11_2016_4Q.shp").set_crs(5179, allow_override=True)
    B["dong7"] = B.TOT_REG_CD.astype(str).str[:7]; G = B[["dong7", "geometry"]].dissolve(by="dong7").reset_index().merge(d, on="dong7", how="left")
    fig, axs = plt.subplots(1, 2, figsize=(17, 7.5)); info = {}
    for ax, col, ttl, cm in zip(axs, ("dT_day_mean", "abs_day_mean"), ("ΔT 예측값 (°C)", "절대 기온 = 배경 기온 + ΔT 예측값 (°C)"), ("PuOr_r", "YlOrRd")):
        lo, hi = np.nanpercentile(G[col], 5), np.nanpercentile(G[col], 95)
        G.plot(column=col, ax=ax, cmap=cm, vmin=lo, vmax=hi, edgecolor="white", linewidth=0.2)
        sm = plt.cm.ScalarMappable(cmap=cm, norm=plt.Normalize(lo, hi))
        cb = fig.colorbar(sm, ax=ax, shrink=.7, extend="both"); tk = np.linspace(lo, hi, 5); cb.set_ticks(tk); cb.set_ticklabels([f"{t:.2f}" for t in tk])
        top = G.nlargest(5, col); lines = []
        for i, (_, r) in enumerate(top.iterrows(), 1):
            p = r.geometry.representative_point()
            ax.text(p.x, p.y, str(i), ha="center", va="center", fontsize=8, fontweight="bold", color="black",
                    bbox=dict(boxstyle="circle,pad=.15", fc="white", ec="black", lw=.6))
            lines.append(f"{i}. {r['name']} {r[col]:.2f}")
        ax.text(0.0, 0.02, "가장 높은 5개 동\n" + "\n".join(lines), transform=ax.transAxes, fontsize=9, va="bottom", ha="left",
                bbox=dict(boxstyle="round,pad=.4", fc="white", ec="#999999", alpha=.95))
        ax.set_title(f"낮(07–20시) 평균 {ttl}\n색 범위 5–95백분위 {lo:.2f}–{hi:.2f}", fontsize=11); ax.axis("off")
        info[col] = dict(p5=float(lo), p95=float(hi), top5=[(r["name"], round(float(r[col]), 2)) for _, r in top.iterrows()])
    fig.suptitle("행정동 424개, 2024·2025 여름 낮 평균: ΔT 예측값 vs 절대 기온", fontsize=13)
    fig.text(.5, .03, "상위 5개 동은 각 지도에서 값이 가장 높은 동. " + CAVEAT, ha="center", fontsize=8.5)
    fig.savefig(OUT / "fig2_dong_dT_vs_abs_day.png", dpi=150, bbox_inches="tight"); plt.close(fig)
    check["fig2"] = info
    return info


def fig3():
    K = pickle.load(open(S1 / "_ked_cache.pkl", "rb")); R = K["rec108"]
    a = pd.read_parquet(ROOT / "merged_data/D3_asos108/asos108_2024_2025.parquet", columns=["measure_time", "TA"])
    a = a[a.TA > -50].assign(ts=a.measure_time.dt.floor("h")).groupby("ts").TA.mean()
    R = R.assign(obs=R.ts.map(a)).dropna()                                      # step1.holdout108 과 같은 결합
    H = R.groupby(R.ts.dt.hour)[["obs", "bg_est", "abs_est"]].mean()
    bias = dict(n=len(R), bg_bias=float((R.bg_est - R.obs).mean()), abs_bias=float((R.abs_est - R.obs).mean()))
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(H.index, H.obs, "-o", color="black", lw=2.2, ms=4, label="ASOS 108 실측")
    ax.plot(H.index, H.bg_est, "-s", color="#2c6fbb", lw=1.8, ms=3.5, label=f"배경 기온(KED) 추정, 편향 {bias['bg_bias']:+.2f}°C")
    ax.plot(H.index, H.abs_est, "-^", color="#c0392b", lw=1.8, ms=3.5, label=f"절대 기온 추정, 편향 {bias['abs_bias']:+.2f}°C")
    ax.set_xticks(range(24)); ax.set_xticklabels([f"{h:02d}" for h in range(24)]); ax.set_xlabel("시각"); ax.set_ylabel("여름(6–9월) 시각별 평균 기온 (°C)")
    ax.grid(alpha=.3); ax.legend(loc="upper left", fontsize=10)
    ax.set_title(f"종로 ASOS 108 홀드아웃: 2024·2025 여름 시각별 평균 (n = {bias['n']:,}시간)", fontsize=12)
    fig.text(.5, -.02, CAVEAT, ha="center", fontsize=8.5)
    fig.savefig(OUT / "fig3_holdout108_hourly.png", dpi=150, bbox_inches="tight"); plt.close(fig)
    H.round(3).to_csv(OUT / "fig3_holdout108_hourly_means.csv", encoding="utf-8-sig")
    check["fig3"] = dict(**bias, hourly_gap_abs=[float(H.abs_est.sub(H.obs).min()), float(H.abs_est.sub(H.obs).max())],
                         hourly_gap_bg=[float(H.bg_est.sub(H.obs).min()), float(H.bg_est.sub(H.obs).max())])
    return bias


if __name__ == "__main__":
    m = fig1(); i = fig2(); b = fig3()
    hold = json.load(open(S1 / "step1_summary.json"))["holdout108"]["all"]
    cap = ["# 1단계 절대 기온 그림 캡션\n",
           "\n그림: out/step1_fig/fig1_gu_slope.png\n",
           f"\n**읽는 법:** 선이 기울수록 ΔT만 볼 때와 절대 기온으로 볼 때 순위가 다르다. 굵은 선 = {SHIFT}단계 이상 바뀐 구"
           f"(낮: {', '.join(m['day'])} / 밤: {', '.join(m['night']) or '없음'}).\n",
           f"\n{CAVEAT}\n",
           "\n그림: out/step1_fig/fig2_dong_dT_vs_abs_day.png\n",
           f"\n**읽는 법:** 두 지도에서 가장 높은 5개 동이 하나도 겹치지 않는다. "
           f"ΔT 예측값 상위 5: {', '.join(n for n, _ in i['dT_day_mean']['top5'])} / 절대 기온 상위 5: {', '.join(n for n, _ in i['abs_day_mean']['top5'])}. "
           "색 범위는 각 지도의 5–95백분위.\n",
           f"\n{CAVEAT}\n",
           "\n그림: out/step1_fig/fig3_holdout108_hourly.png\n",
           f"\n**읽는 법:** 절대 기온(빨강)이 하루 종일 실측(검정)보다 위에 있다(편향 +{hold['abs_bias']:.2f}°C, 배경 기온만 {hold['bg_bias']:.2f}°C). "
           "그래서 절대 기온은 순위 비교용이다.\n",
           f"\n{CAVEAT}\n"]
    open(OUT / "captions.md", "w").write("".join(cap))
    json.dump(check, open(OUT / "_check.json", "w"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(check, ensure_ascii=False, indent=1, default=str))

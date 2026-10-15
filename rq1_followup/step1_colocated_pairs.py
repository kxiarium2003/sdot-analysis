"""[②] 기상청 관측소 근처 S-DoT 센서 쌍: 여름 시각별 raw 기온 차(센서 − 관측소). 조회·계산만.

[사전등록] 탐색용 분석이며 판정 임계값은 두지 않는다. (작성 2026-10-13, 결과 보기 전)
  센서      merged_data/D1_sdot/sensor_samples.csv 의 in_main == True (1,085대). 좌표는 sensor_summary.csv 의 lat/lon.
  관측소    merged_data/D2_aws/stations_kma.csv 중 in_seoul == True (29곳). 좌표는 lon/lat(기상청 공식 좌표로 보임).
  거리      두 좌표를 EPSG:5179 로 바꾼 직선거리. 반경 300 m. 쌍이 5개 미만이면 500 m 도 따로 보고(반경별 구분).
  기온      S-DoT: sdot_hourly_2024_2025.parquet 의 temperature(시각 = timestamp).
            관측소: merged_data/D2_aws/awsh_2024_2025.parquet 의 ta(measure_time 을 시 단위로 내림), ta_zero_sentinel 행 제외.
            같은 시각끼리 짝지어 차 = 센서 − 관측소. 기간 2024·2025 년 6–9 월. 보정·이상치 제거 없음(raw).
  산출      쌍별 전체 평균·표준편차·n, 쌍 × 시각(0–23) 평균·표준편차·n, 반경별 쌍 평균의 평균·표준편차.
실행: PYTHONDONTWRITEBYTECODE=1 python3 rq1_followup/step1_colocated_pairs.py
출력: rq1_followup/out/step1_fig/colocated_pairs*.csv, colocated_pairs_summary.json, colocated_pairs_hourly.png
"""
import json
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "rq1_followup/out/step1_fig"; OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams["font.family"] = "AppleGothic"; plt.rcParams["axes.unicode_minus"] = False
R1, R2, MIN_PAIRS = 300, 500, 5

smp = pd.read_csv(ROOT / "merged_data/D1_sdot/sensor_samples.csv"); summ = pd.read_csv(ROOT / "merged_data/D1_sdot/sensor_summary.csv")
sen = smp.loc[smp.in_main, ["sensor_id"]].merge(summ[["sensor_id", "lat", "lon"]], on="sensor_id", how="left")
st = pd.read_csv(ROOT / "merged_data/D2_aws/stations_kma.csv", dtype={"stn_id": str}); st = st[st.in_seoul]
gs = gpd.GeoDataFrame(sen, geometry=gpd.points_from_xy(sen.lon, sen.lat), crs=4326).to_crs(5179)
gt = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st.lon, st.lat), crs=4326).to_crs(5179)
D = np.sqrt((gs.geometry.x.values[:, None] - gt.geometry.x.values[None, :]) ** 2 + (gs.geometry.y.values[:, None] - gt.geometry.y.values[None, :]) ** 2)
i, j = np.where(D <= R2)
P = pd.DataFrame({"sensor_id": gs.sensor_id.values[i], "stn_id": gt.stn_id.values[j], "addr": gt.addr.values[j], "dist_m": D[i, j].round(1),
                  "stn_geocode_err_m": gt.geocode_err_m.values[j]}).sort_values("dist_m")
P["radius"] = np.where(P.dist_m <= R1, f"≤{R1}m", f"{R1}–{R2}m")
n300 = int((P.dist_m <= R1).sum()); radii = [R1] if n300 >= MIN_PAIRS else [R1, R2]
P = P[P.dist_m <= max(radii)]
print(f"반경 {R1}m 쌍 {n300}개 | 반경 {R2}m 쌍 {int((P.dist_m <= R2).sum()) if R2 in radii else '보고 안 함'}"); print(P.to_string(index=False))

summary = dict(n_in_main=int(len(sen)), n_stations_seoul=int(len(st)), n_pairs_300=n300, radii_reported=radii,
               nearest_any_m=float(D.min()), pairs=P.to_dict("records"))
if len(P):
    h = pd.read_parquet(ROOT / "merged_data/D1_sdot/sdot_hourly_2024_2025.parquet", columns=["sensor_id", "timestamp", "temperature"])
    h = h[h.sensor_id.isin(P.sensor_id) & h.timestamp.dt.month.between(6, 9) & h.temperature.notna()]
    a = pd.read_parquet(ROOT / "merged_data/D2_aws/awsh_2024_2025.parquet", columns=["stn_id", "measure_time", "ta", "ta_zero_sentinel"])
    a = a[a.stn_id.isin(P.stn_id) & ~a.ta_zero_sentinel.fillna(False) & a.ta.notna()]
    a = a.assign(ts=a.measure_time.dt.floor("h")).groupby(["stn_id", "ts"]).ta.mean().reset_index()
    X = P[["sensor_id", "stn_id", "dist_m", "radius"]].merge(h, on="sensor_id").merge(a, left_on=["stn_id", "timestamp"], right_on=["stn_id", "ts"])
    X = X[X.timestamp.dt.month.between(6, 9)]; X["diff"] = X.temperature - X.ta; X["hour"] = X.timestamp.dt.hour
    per = X.groupby(["sensor_id", "stn_id", "dist_m", "radius"])["diff"].agg(mean="mean", sd="std", n="size").reset_index().sort_values("dist_m")
    hr = X.groupby(["sensor_id", "stn_id", "radius", "hour"])["diff"].agg(mean="mean", sd="std", n="size").reset_index()
    hr_all = X.groupby(["radius", "hour"])["diff"].agg(mean="mean", sd="std", n="size").reset_index()
    per.round(3).to_csv(OUT / "colocated_pairs.csv", index=False, encoding="utf-8-sig")
    hr.round(3).to_csv(OUT / "colocated_pairs_hourly_by_pair.csv", index=False, encoding="utf-8-sig")
    hr_all.round(3).to_csv(OUT / "colocated_pairs_hourly_pooled.csv", index=False, encoding="utf-8-sig")
    summary["by_radius"] = {r: dict(n_pairs=int(len(g)), mean_of_pair_means=float(g["mean"].mean()), sd_of_pair_means=float(g["mean"].std()) if len(g) > 1 else None,
                                    pooled_mean=float(X[X.radius == r]["diff"].mean()), pooled_sd=float(X[X.radius == r]["diff"].std()), n_hours=int((X.radius == r).sum()))
                            for r, g in per.groupby("radius")}
    summary["per_pair"] = per.to_dict("records")
    print(per.round(3).to_string(index=False)); print(json.dumps(summary["by_radius"], ensure_ascii=False, indent=1))
    fig, ax = plt.subplots(figsize=(10, 5.5)); ax.set_prop_cycle(color=plt.cm.tab20(np.linspace(0, 1, 20))[:len(per)])
    for (sid, stn, r), g in hr.groupby(["sensor_id", "stn_id", "radius"]):
        ax.plot(g.hour, g["mean"], "-o", ms=3, lw=1.6 if r.startswith("≤") else 1.0, ls="-" if r.startswith("≤") else "--",
                label=f"{sid} - 관측소 {stn} ({P.set_index(['sensor_id', 'stn_id']).loc[(sid, stn), 'dist_m']:.0f} m)")
    ax.axhline(0, color="black", lw=.8); ax.set_xticks(range(24)); ax.set_xlabel("시각"); ax.set_ylabel("센서 - 관측소 (°C), 여름 시각별 평균")
    ax.set_title(f"관측소 반경 {max(radii)} m 이내 S-DoT 센서 {len(per)}쌍: 여름(6–9월) 시각별 raw 기온 차 (센서 - 관측소)"); ax.grid(alpha=.3); ax.legend(fontsize=8, ncol=2)
    fig.text(.5, -.02, "탐색용(임계값 없음). raw 값, 보정 없음. 관측소 좌표는 기상청 공식 좌표로 보임(stations_kma.csv lon/lat).", ha="center", fontsize=8.5)
    fig.savefig(OUT / "colocated_pairs_hourly.png", dpi=150, bbox_inches="tight"); plt.close(fig)
json.dump(summary, open(OUT / "colocated_pairs_summary.json", "w"), ensure_ascii=False, indent=1, default=str)

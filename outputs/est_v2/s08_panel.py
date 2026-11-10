"""s08_panel.py - C-1: 역 ID 대응, 실제 비율, 예측(P0·P1·P2) 패널.

단위: 역 × 날짜 × 시(06~23시 칸, 06시 이전·24시 이후 제외).
실제: D26 노인 승차 / D18 전체 승차.
P0: 자치구 D12 65+ 출발 이동 비율(요일×출발시) [마스킹 0/3].
P1: D25 역→역 OD × D12 동 쌍 65+ 비율(요일×시, 출발시 변환) → 역별 승차 가중 평균 [마스킹 0/3], 변환 없는 버전 ns.
P2: 역 반경 300·500m 집계구의 D5 65+ 비중(날짜×시).
출력(스크래치): eval/panel.parquet / 요약: s08_*.csv
"""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd

E = SCRATCH / "eval"; E.mkdir(exist_ok=True)
GEO = SCRATCH / "geo"; CD = SCRATCH / "d12cells"; D5 = SCRATCH / "d5st"
con = duck()
st = pd.read_parquet(GEO / "stations.parquet")


def load_d26():
    out = []
    for p in sorted(glob.glob(str(SCRATCH / "raw/d26/*.csv"))):
        d = pd.read_csv(p, encoding="cp949", dtype=str, keep_default_na=False)
        h = list(d.columns[5:])
        assert len(h) == 20, h
        d = d[d["승하차구분"] == "승차"]
        d = d[pd.to_datetime(d["수송일자"]).dt.strftime("%Y%m").isin(MONTHS)]
        arr = d[h].apply(lambda c: pd.to_numeric(c.str.replace(",", ""), errors="coerce")).fillna(0).to_numpy()
        t = pd.DataFrame(arr[:, 1:19], columns=range(6, 24)); t["id"] = d["역번호"].astype(int).to_numpy(); t["date"] = d["수송일자"].str.replace("-", "").to_numpy()
        out.append(t)
    return pd.concat(out, ignore_index=True).melt(id_vars=["id", "date"], var_name="hour", value_name="n65")


def load_d18():
    out = []
    for p in sorted(glob.glob(str(RAW_LOCAL / "D18_subway_hourly/서울교통공사_역별*.csv"))):
        d = pd.read_csv(p, encoding="cp949", dtype=str, keep_default_na=False)
        dc = "날짜" if "날짜" in d.columns else "수송일자"; kc = "구분" if "구분" in d.columns else "승하차구분"
        d = d[d[dc].str.match(r"\d{4}-\d{2}-\d{2}")]
        h = list(d.columns[6:])
        assert len(h) == 20, h
        d = d[d[kc] == "승차"]
        d = d[pd.to_datetime(d[dc]).dt.strftime("%Y%m").isin(MONTHS)]
        arr = d[h].apply(lambda c: pd.to_numeric(c.str.replace(",", ""), errors="coerce")).fillna(0).to_numpy()
        t = pd.DataFrame(arr[:, 1:19], columns=range(6, 24)); t["id"] = d["역번호"].astype(int).to_numpy(); t["date"] = d[dc].str.replace("-", "").to_numpy()
        out.append(t)
    return pd.concat(out, ignore_index=True).melt(id_vars=["id", "date"], var_name="hour", value_name="n_tot")


def load_d27_totals():
    out = []
    for p in sorted(glob.glob(str(SCRATCH / "raw/d27/*.csv"))):
        d = pd.read_csv(p, encoding="cp949", dtype=str, keep_default_na=False)
        h = list(d.columns[7:])
        assert len(h) == 20
        d = d[(d["승하차구분"] == "승차") & pd.to_datetime(d["수송일자"]).dt.strftime("%Y%m").isin(MONTHS)]
        arr = d[h].apply(lambda c: pd.to_numeric(c.str.replace(",", ""), errors="coerce")).fillna(0).to_numpy()
        t = pd.DataFrame(arr[:, 1:19], columns=range(6, 24)); t["id"] = d["역번호"].astype(int).to_numpy(); t["date"] = d["수송일자"].str.replace("-", "").to_numpy()
        out.append(t.groupby(["id", "date"], as_index=False).sum())
    return pd.concat(out, ignore_index=True).melt(id_vars=["id", "date"], var_name="hour", value_name="n27")


d26, d18, d27 = load_d26(), load_d18(), load_d27_totals()
print("rows", len(d26), len(d18), len(d27))
S26, S18, S27 = set(d26.id), set(d18.id), set(d27.id)
d22ids = {int(b): b for b in st.bldn}
sets = {"D26": S26, "D27": S27, "D18": S18}
pairs = []
for a in sets:
    pairs.append(dict(기준=a, 고유역=len(sets[a]), D22일치=sum(i in d22ids for i in sets[a]), D22불일치목록=",".join(map(str, sorted(i for i in sets[a] if i not in d22ids)))))
    for b in sets:
        if a != b:
            pairs.append(dict(기준=a, 대상=b, 고유역=len(sets[a]), 일치=len(sets[a] & sets[b]), 일치율=len(sets[a] & sets[b]) / len(sets[a]), 불일치목록=",".join(map(str, sorted(sets[a] - sets[b])))))
d25b = set(r[0] for r in con.execute(f"SELECT DISTINCT board_id FROM read_parquet('{SCRATCH}/d25long/*.parquet') WHERE length(board_id)=4").fetchall())
b26 = {f"{i:04d}" for i in S26}
pairs.append(dict(기준="D26", 대상="D25 4자리 승차ID", 고유역=len(b26), 일치=len(b26 & d25b), 일치율=len(b26 & d25b) / len(b26), 불일치목록=",".join(sorted(b26 - d25b))))
pd.DataFrame(pairs).to_csv(OUT / "s08_station_id_match.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(pairs).to_string())
# D27 합 vs D18
m = d18.merge(d27, on=["id", "date", "hour"], how="inner")
print("D27합/D18 (전체)", m.n27.sum() / m.n_tot.sum(), "역×날짜×시 일치(절대차<=1)", (abs(m.n27 - m.n_tot) <= 1).mean())

sc = st[st.seoul_d9 & st.bldn.isin(b26)].copy()
sc = sc[sc.bldn.map(lambda b: int(b) in S18)]
print("평가 대상 역", len(sc))
t = d26.merge(d18, on=["id", "date", "hour"], how="inner")
t["bldn"] = t.id.map(lambda x: f"{x:04d}")
t = t[t.bldn.isin(sc.bldn)].copy()
t["hour"] = t.hour.astype(int)
t["n65"] = np.minimum(t.n65, t.n_tot)
dt = pd.to_datetime(t.date); t["wd"] = (dt.dt.dayofweek).astype(int); t["ym"] = t.date.str[:6]
# 역 정보
info = sc[["bldn", "name", "route", "dong7", "gu_final"]]
t = t.merge(info, on="bldn", how="left")
print("실제 패널", len(t), t.bldn.nunique(), t.date.nunique())
# P0
gu = []
for ym in MONTHS:
    g = pd.read_parquet(CD / f"gu_{ym}.parquet"); g["ym"] = ym; gu.append(g)
gu = pd.concat(gu).rename(columns={"gu": "gu_final"})
gu["P0_m0"] = gu.s65 / gu.t0; gu["P0_m3"] = gu.s65 / (gu.t0 + 3 * gu.nm)
t = t.merge(gu[["gu_final", "wd", "hour", "ym", "P0_m0", "P0_m3"]], on=["gu_final", "wd", "hour", "ym"], how="left")
# P1
con.register("sta", st[st.dong7.notna()][["bldn", "dong7"]])
con.register("scope", sc[["bldn", "dong7"]])
res = []
for ym in MONTHS:
    for shift, cf, tag in (("dep", "dep", "P1"), ("arr", "arr", "P1ns")):
        r = con.execute(f"""
          WITH f AS (SELECT l.date, l.hour, l.board_id bldn, s.dong7 o, a.dong7 d, l.pax,
                            isodow(strptime(l.date,'%Y%m%d'))-1 wd
                     FROM read_parquet('{SCRATCH}/d25long/{ym}*.parquet') l JOIN scope s ON l.board_id=s.bldn LEFT JOIN sta a ON l.alight_id=a.bldn
                     WHERE length(l.board_id)=4 AND l.hour BETWEEN 6 AND 23)
          SELECT f.date, f.hour, f.bldn, SUM(f.pax) pax_all,
                 SUM(CASE WHEN c.t0>0 THEN f.pax ELSE 0 END) pax_match,
                 SUM(CASE WHEN c.t0>0 THEN f.pax*c.s65/c.t0 ELSE 0 END) sum_m0,
                 SUM(CASE WHEN c.t0>0 THEN f.pax*c.s65/(c.t0+3*c.nm) ELSE 0 END) sum_m3,
                 SUM(CASE WHEN f.d IS NOT NULL THEN f.pax ELSE 0 END) pax_seoul_dest
          FROM f LEFT JOIN read_parquet('{CD}/{cf}_{ym}.parquet') c ON f.wd=c.wd AND f.hour=c.hour AND f.o=c.o AND f.d=c.d
          GROUP BY 1,2,3""").df()
        r = r.rename(columns=lambda c: c if c in ("date", "hour", "bldn") else f"{tag}_{c}")
        res.append((tag, r))
        print(ym, shift, len(r), flush=True)
for tag in ("P1", "P1ns"):
    x = pd.concat([r for k, r in res if k == tag], ignore_index=True)
    t = t.merge(x, on=["date", "hour", "bldn"], how="left")
    t[f"{tag}_m0"] = t[f"{tag}_sum_m0"] / t[f"{tag}_pax_match"].replace(0, np.nan)
    t[f"{tag}_m3"] = t[f"{tag}_sum_m3"] / t[f"{tag}_pax_match"].replace(0, np.nan)
# P2
p2 = pd.concat([pd.read_parquet(D5 / f"{ym}.parquet") for ym in MONTHS], ignore_index=True)
p2["r"] = p2.s65 / p2.tot.replace(0, np.nan)
p2["rm3"] = (p2.s65m3 / p2.tot.replace(0, np.nan)).clip(upper=1)
for rad in (300, 500):
    x = p2[p2.radius == rad][["bldn", "date", "hour", "r", "rm3", "fallback"]].rename(columns={"r": f"P2_{rad}", "rm3": f"P2_{rad}_m3", "fallback": f"P2_{rad}_fb"})
    t = t.merge(x, on=["bldn", "date", "hour"], how="left")
t.to_parquet(E / "panel.parquet", index=False)
cov = t[["P1_pax_all", "P1_pax_match", "P1_pax_seoul_dest", "n_tot", "n65"]].sum()
print("P1 coverage: match/all", cov.P1_pax_match / cov.P1_pax_all, "seoul_dest/all", cov.P1_pax_seoul_dest / cov.P1_pax_all)
print(t[["P0_m0", "P0_m3", "P1_m0", "P1_m3", "P1ns_m0", "P2_300", "P2_500", "P2_300_m3", "P2_500_m3"]].describe().round(3).T.to_string())
print("P2_300 fallback 역", t[t.P2_300_fb == 1].bldn.nunique(), "P2_500 fallback 역", t[t.P2_500_fb == 1].bldn.nunique())
print("예측 결측 비율", t[["P0_m0", "P1_m0", "P2_300", "P2_500"]].isna().mean().round(4).to_dict(), "결측일", sorted(t[t.P1_m0.isna()].date.value_counts().head(5).index.tolist()))

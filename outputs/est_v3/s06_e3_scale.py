"""s06_e3_scale.py - E2 보정 적용과 E3 서울 전체 규모 맞추기, 최종 정류장×날짜×시 산출, 점검. 인자: 월 목록.

중간 = m3, 하한·상한 = m0·m3 결과의 칸별 최소·최대. 시나리오별·월별 k. 하차에도 같은 k.
지하철 65+ 합계 = D26 승차 합계(모든 시간대) × (D28 전 노선 무임 승차 ÷ D28 1~8호선 무임 승차).
목표 = 지하철 65+ × (버스 23.4 ÷ 지하철 24.2) [2024 서울시 노인실태조사 p.39]
출력(스크래치): est/est_YYYYMM.parquet / 요약: s06_e3_k.csv, s06_check_daily.csv, s06_check_gu.csv, s06_top20_stops.csv, s06_ratio_over1.csv
"""
import sys, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd

ES = SCRATCH / "est"; ES.mkdir(exist_ok=True)
months = sys.argv[1].split(",")
par = pd.read_csv(OUT / "s05_e2_params.csv").set_index("모형")


def apply(p, m):
    a, b = par.loc[f"P1_{m}", "a"], par.loc[f"P1_{m}", "b"]
    q = np.clip(p, 1e-3, 1 - 1e-3)
    return 1 / (1 + np.exp(-(a + b * np.log(q / (1 - q)))))


# 지하철 합계
d26 = []
for p in sorted(glob.glob(str(SCRATCH / "raw/d26/*.csv"))):
    d = pd.read_csv(p, encoding="cp949", dtype=str, keep_default_na=False)
    h = list(d.columns[5:]); assert len(h) == 20, h
    d = d[d["승하차구분"] == "승차"].copy(); d["ym"] = pd.to_datetime(d["수송일자"]).dt.strftime("%Y%m")
    d["n"] = d[h].apply(lambda c: pd.to_numeric(c.str.replace(",", ""), errors="coerce")).fillna(0).sum(axis=1)
    d26.append(d.groupby("ym").n.sum())
d26 = pd.concat(d26)
rows = []
for ym in months:
    j = json.load(open(SCRATCH / f"raw/d28/CardSubwayPayFree_{ym}.json", encoding="utf-8"))
    t = pd.DataFrame(j["row"])
    t["f"] = pd.to_numeric(t.FREECHRG_GTON_NOPE); t = t[t.USE_MM.astype(str) == ym]
    lines18 = {f"{i}호선" for i in range(1, 9)}
    all_f, k18 = t.f.sum(), t[t.SBWY_ROUT_LN_NM.isin(lines18)].f.sum()
    rows.append(dict(ym=ym, D26_승차합=float(d26[ym]), D28_전노선_무임승차=float(all_f), D28_1_8호선_무임승차=float(k18), 비율=all_f / k18, D28행=len(t), 호선수=t.SBWY_ROUT_LN_NM.nunique()))
sub = pd.DataFrame(rows); sub["지하철65합"] = sub.D26_승차합 * sub.비율; sub["목표버스65승차"] = sub.지하철65합 * SURVEY["bus"] / SURVEY["subway"]

over, kr, day_chk, gu_chk, frames = [], [], [], [], []
for ym in months:
    d = pd.read_parquet(SCRATCH / f"e1/e1_{ym}.parquet")
    for m, c in (("m0", "0"), ("m3", "3")):
        d[f"pb_{m}"] = apply(d[f"rb{c}"].to_numpy(), m); d[f"pa_{m}"] = apply(d[f"ra{c}"].to_numpy(), m)
        d[f"b_{m}"] = (d[f"pb_{m}"] * d.board).fillna(0); d[f"a_{m}"] = (d[f"pa_{m}"] * d.alight_h1).fillna(0)
    tg = sub.set_index("ym").loc[ym, "목표버스65승차"]
    rec = dict(ym=ym, 목표=tg, 분모승차합=d.board.sum())
    for m, c in (("m0", "0"), ("m3", "3")):
        p1 = (d[f"rb{c}"].fillna(0) * d.board).sum()
        e2 = d[f"b_{m}"].sum(); k = tg / e2
        rec.update({f"E1합_{m}": p1, f"E2합_{m}": e2, f"k_{m}": k, f"E2비율_{m}": e2 / d.board.sum(), f"최종비율_{m}": e2 * k / d.board.sum()})
        d[f"fb_{m}"] = d[f"b_{m}"] * k; d[f"fa_{m}"] = d[f"a_{m}"] * k
    kr.append(rec)
    res = pd.DataFrame({"date": d.date, "hour": d.hour, "node": d.node, "ars": d.ars, "board": d.board, "alight": d.alight_h1,
                        "board65_mid": d.fb_m3, "board65_lo": d[["fb_m0", "fb_m3"]].min(axis=1), "board65_hi": d[["fb_m0", "fb_m3"]].max(axis=1),
                        "alight65_mid": d.fa_m3, "alight65_lo": d[["fa_m0", "fa_m3"]].min(axis=1), "alight65_hi": d[["fa_m0", "fa_m3"]].max(axis=1),
                        "imputed": d.imputed, "is_holiday": d.is_holiday, "weekday": d.weekday, "ym": d.ym})
    with np.errstate(invalid="ignore", divide="ignore"):
        res["ratio_board65"] = res.board65_mid / res.board.where(res.board > 0); res["ratio_alight65"] = res.alight65_mid / res.alight.where(res.alight > 0)
    res.to_parquet(ES / f"est_{ym}.parquet", index=False, compression="zstd")
    for side in ("board", "alight"):
        bad = res[f"{side}65_mid"] > res[side]
        over.append(dict(ym=ym, side=side, cells=int(bad.sum()), cell_share=float(bad.mean()), excess_pax=float((res[f"{side}65_mid"] - res[side]).clip(lower=0).sum()), hi_cells=int((res[f"{side}65_hi"] > res[side]).sum())))
    x = res.groupby("date").agg(b=("board65_mid", "sum"), a=("alight65_mid", "sum"), B=("board", "sum"), A=("alight", "sum"), imp=("imputed", "max"), hol=("is_holiday", "max")).reset_index()
    x["diff65_pct"] = (x.a / x.b - 1) * 100; x["diff_total_pct"] = (x.A / x.B - 1) * 100; x["ym"] = ym; day_chk.append(x)
    frames.append(res[["node", "board", "board65_mid", "board65_lo", "board65_hi", "alight65_mid", "alight", "ym"]])
    print(ym, res[["board", "board65_mid", "board65_lo", "board65_hi", "alight65_mid"]].sum().round(0).to_dict(), flush=True)

RN = {"D26_승차합": "D26 서울교통공사 역별 노인 승하차 승차합", "D28_전노선_무임승차": "D28 서울시 지하철 호선별 역별 유/무임 승하차 전 노선 무임승차", "D28_1_8호선_무임승차": "D28 서울시 지하철 호선별 역별 유/무임 승하차 1~8호선 무임승차", "D28행": "D28 서울시 지하철 호선별 역별 유/무임 승하차 행 수"}
INV = {v: k for k, v in RN.items()}
merge_p = lambda n, f: pd.concat([pd.read_csv(n, dtype={"ym": str}).rename(columns=INV)[lambda t: ~t.ym.isin(months)], f]) if os.path.exists(n) else f
kk = merge_p(OUT / "s06_e3_k.csv", pd.DataFrame(kr).merge(sub, on="ym")).sort_values("ym"); kk.rename(columns=RN).to_csv(OUT / "s06_e3_k.csv", index=False, encoding="utf-8-sig"); print(kk.round(4).T.to_string())
oo = merge_p(OUT / "s06_ratio_over1.csv", pd.DataFrame(over)).sort_values(["ym", "side"]); oo.to_csv(OUT / "s06_ratio_over1.csv", index=False, encoding="utf-8-sig"); print(oo.to_string())
dc = merge_p(OUT / "s06_check_daily.csv", pd.concat(day_chk)).sort_values("date"); dc.to_csv(OUT / "s06_check_daily.csv", index=False, encoding="utf-8-sig")
print("날짜별 65+ 승하차 차이% (전 월):", dc.diff65_pct.describe().round(3).to_dict())
# 자치구·상위 정류장은 s06_check_gu.py가 전체 est로 다시 만든다(모든 월 합산)

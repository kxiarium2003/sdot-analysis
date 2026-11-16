"""s05 - 생활이동 대비 비교 (서울·시간대·자치구, 평일/주말, 월별 하루 평균).

생활이동: D12 서울 생활이동(Drive interim/seoul_living_migration/seoul_living_migration_admdong/YYYYMM.parquet).
  서울 출발(출발 행정동 코드 7자리)만. 하루 값 = (월 x 요일 합) / 그 달 그 요일 날 수. 평일 = 월~금, 주말 = 토·일.
  마스킹(이동인구 NaN, suppressed)은 하한 0, 상한 3. 65+ = 나이 65, 70, 75, 80. 시간 = 도착 시간. 자치구 = 출발 코드 앞 4자리.
버스: v5 추정(s03) 총 승차, 65+ = 월보 버스 경로(R_d). 자치구·시간대 65+는 주 결과 후보(s04 선택) 값.
지하철: D18 서울교통공사 승차(전체), D26 노인 승차(1~8호선), 서울 안 역만(s02_subway_daily.csv).
사용: python3 -I s05_living.py <SCRATCH>
"""
import sys, subprocess, calendar, re
from pathlib import Path
import numpy as np, pandas as pd, duckdb

OUT = Path(__file__).resolve().parent
SCR = Path(sys.argv[1])
MS = ["202407", "202408", "202507", "202508"]
GU = dict(zip([f"11{i:02d}0" for i in range(1, 26)], "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split()))
WD = ["월", "화", "수", "목", "금", "토", "일"]
sel = (OUT / "s04_selection_log.txt").read_text(encoding="utf-8")
mm = re.search(r"주 결과 ([ABC])", sel)
MAIN = mm.group(1) if mm else "C"

# ---- D12
lm = []
for ym in MS:
    cache = SCR / f"d12agg_{ym}.parquet"
    if not cache.exists():
        dl = SCR / "dl_d12"; dl.mkdir(exist_ok=True)
        subprocess.run(["rclone", "copy", f"googledrive:sdot-analysis/interim/seoul_living_migration/seoul_living_migration_admdong/{ym}.parquet", str(dl)], check=True)
        f = dl / f"{ym}.parquet"
        q = f"""SELECT "요일" AS wd, CAST("도착시간" AS INT) AS hour, '11' || substr("출발 행정동 코드",3,2) || '0' AS gu5,
                 ("나이" IN ('65','70','75','80')) AS e65,
                 sum(coalesce("이동인구(합)", 0)) AS lo, sum(CASE WHEN "이동인구(합)_suppressed" THEN 3 ELSE coalesce("이동인구(합)", 0) END) AS hi,
                 sum(CASE WHEN "이동인구(합)_suppressed" THEN 1 ELSE 0 END) AS n_star, count(*) AS n_rows
               FROM read_parquet('{f}') WHERE length("출발 행정동 코드") = 7 GROUP BY ALL"""
        duckdb.sql(q).df().to_parquet(cache, index=False)
        f.unlink()
    d = pd.read_parquet(cache)
    y, mo = int(ym[:4]), int(ym[4:])
    cnt = pd.Series([WD[calendar.weekday(y, mo, k)] for k in range(1, calendar.monthrange(y, mo)[1] + 1)]).value_counts()
    d["daytype"] = np.where(d.wd.isin(["토", "일"]), "주말", "평일")
    d["ym"] = ym
    d["ndays_dt"] = d.daytype.map({"평일": cnt[WD[:5]].sum(), "주말": cnt[WD[5:]].sum()})
    lm.append(d)
lm = pd.concat(lm)
lm["star_share"] = lm.n_star / lm.n_rows


def life(keys):
    g = lm.groupby(["ym", "daytype", "e65"] + keys).agg(lo=("lo", "sum"), hi=("hi", "sum"), nd=("ndays_dt", "first")).reset_index()
    g["lo"] /= g.nd; g["hi"] /= g.nd
    a = g.pivot_table(index=["ym", "daytype"] + keys, columns="e65", values=["lo", "hi"], aggfunc="sum")
    a.columns = [f"{v}_{'65' if e else 'u65'}" for v, e in a.columns]
    a = a.fillna(0)
    r = pd.DataFrame(index=a.index)
    r["생활이동_전체_하한"] = a.lo_65 + a.lo_u65
    r["생활이동_전체_상한"] = a.hi_65 + a.hi_u65
    r["생활이동_65+_하한"] = a.lo_65
    r["생활이동_65+_상한"] = a.hi_65
    r["생활이동_65+비율_하한%"] = 100 * a.lo_65 / (a.lo_65 + a.hi_u65)
    r["생활이동_65+비율_상한%"] = 100 * a.hi_65 / (a.hi_65 + a.lo_u65)
    return r


# ---- 버스
hr = pd.concat([pd.read_csv(OUT / f"s03_date_hour_{m}.csv", dtype={"date": str}).assign(ym=m) for m in MS])
gu = pd.concat([pd.read_csv(OUT / f"s03_gu_{m}.csv", dtype={"gu5": str}).assign(ym=m) for m in MS])
nd = hr.groupby(["ym", "daytype"]).date.nunique().rename("nd")


def bus(keys, src):
    g = src.groupby(["ym", "daytype"] + keys)[["board", f"est65_{MAIN}"]].sum().join(nd, on=["ym", "daytype"])
    return pd.DataFrame({"버스승차": g.board / g.nd, "버스65+": g[f"est65_{MAIN}"] / g.nd})


# ---- 지하철
sw = pd.read_csv(OUT / "s02_subway_daily.csv", dtype={"date": str, "ym": str})
sw = sw[sw.gu.notna()]
sw["hour"] = sw.bk.map(lambda b: 0 if b == "post24" else 5 if b == "pre06" else int(b))
sw["gu5"] = sw.gu.map({v: k for k, v in GU.items()})
snd = sw.groupby(["ym", "daytype"]).date.nunique().rename("nd")


def sub(keys):
    g = sw.groupby(["ym", "daytype"] + keys)[["T", "E"]].sum().join(snd, on=["ym", "daytype"])
    return pd.DataFrame({"지하철승차": g["T"] / g.nd, "지하철65+": g.E / g.nd})


out = []
for scope, keys in [("서울", []), ("시간대", ["hour"]), ("자치구", ["gu5"])]:
    L = life(keys)
    B = bus(keys, hr if scope != "자치구" else gu)
    S = sub(keys)
    t = L.join(B, how="outer").join(S, how="outer").reset_index()
    t.insert(0, "범위", scope)
    out.append(t)
T = pd.concat(out, ignore_index=True)
T["자치구"] = T.get("gu5").map(GU) if "gu5" in T else None
T["버스65+비율%"] = 100 * T["버스65+"] / T["버스승차"]
T["지하철65+비율%"] = 100 * T["지하철65+"] / T["지하철승차"]
for a, b, lab in [("버스승차", "생활이동_전체", "버스승차÷생활이동전체"), ("지하철승차", "생활이동_전체", "지하철승차÷생활이동전체"),
                  ("버스65+", "생활이동_65+", "버스65+÷생활이동65+"), ("지하철65+", "생활이동_65+", "지하철65+÷생활이동65+")]:
    T[f"{lab}_하한쪽"] = T[a] / T[f"{b}_상한"]
    T[f"{lab}_상한쪽"] = T[a] / T[f"{b}_하한"]
T["비고"] = (f"버스65+ = 월보 버스 경로(교통카드 경로 권종, 목적통행). 자치구·시간대 분배는 후보 {MAIN}. "
            "지하철 = 서울교통공사(1~8호선 등) 서울 안 역만, 65+ = D26 노인 승차. 버스·지하철 65+는 모두 하한. "
            "지하철 시간 0시 = '24시 이후', 5시 = '06시 이전'(00~05시 묶음), 1~4시 비어 있음. 생활이동 시간 = 도착 시각, 버스 = 승차 시각.")
T.to_csv(OUT / "table_living_migration_compare.csv", index=False, encoding="utf-8-sig")
lm.groupby(["ym", "e65"]).agg(n_star=("n_star", "sum"), n_rows=("n_rows", "sum")).assign(star_pct=lambda x: 100 * x.n_star / x.n_rows).to_csv(OUT / "s05_d12_masking.csv", encoding="utf-8-sig")
pd.set_option("display.width", 250)
print("MAIN", MAIN); print(T[T.범위 == "서울"].round(3).T.to_string())

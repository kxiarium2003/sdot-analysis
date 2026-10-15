"""RQ1 모듈 공통: 경로, 상수, 자료 불러오기, 단위(집계구·행정동·자치구) 집계, 지표 함수.

용어
  year      연도 (원자료 열 이름은 summer 이지만 연도를 뜻한다)
  season    winter(12·1·2월, 같은 해 안에서 묶음) / spring / summer(6–9월) / autumn
  period    day(07–20시) / night(21–06시)
  PA_*      활동 기준 인시 = 생활인구(연령 보정 후)를 그 계절 모든 날에 대해 더한 값
  PR_*      거주 기준 인시 = 인구총조사 인구 × 그 계절 일수
  단위 ΔT   행정동·자치구의 ΔT 는 안에 있는 집계구 ΔT 의 거주 인구 가중 평균(주민 0 이면 단순 평균)
"""
from pathlib import Path
import glob
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
P = dict(
    field=ROOT / "phase2/anomaly_by_zone_2y_merged.parquet",              # 집계구 × 연도 × 계절 × 시각 ΔT (Phase 2)
    livingpop=ROOT / "merged_data/D5_livingpop/livingpop_agg_2024_2025_native.parquet",
    foreigner=ROOT / "merged_data/D5_livingpop/foreigner_agg_2024_2025.parquet",
    census=ROOT / "merged_data/D6_census/census2024_age3_tract16.parquet",
    ses=ROOT / "merged_data/covariates/zone_ses.parquet",
    abs_temp=ROOT / "phase3/absolute_temp_tract.parquet",               # phase3_absolute_temp.py 산출
    boundary=ROOT / "merged_data/D9_boundary/bnd_oa_11_2016_4Q/bnd_oa_11_2016_4Q.shp",
    dong_names=ROOT / "data2/D9_zone_boundary/sgis_api_2025/2016",       # SGIS 2016 행정동 경계(이름)
    out=ROOT / "rq1_modules/out",
)
AGES = ["a0_14", "a15_64", "a65p"]; GROUPS = AGES + ["all"]
AGE_KO = {"a0_14": "0–14세", "a15_64": "15–64세", "a65p": "65세 이상", "all": "전 연령"}
NIGHT = {21, 22, 23, 0, 1, 2, 3, 4, 5, 6}; DAY = set(range(24)) - NIGHT
ANCHORS = {"24h": set(range(24)), "night": NIGHT, "day": DAY}
GU = {"11010": "종로구", "11020": "중구", "11030": "용산구", "11040": "성동구", "11050": "광진구", "11060": "동대문구",
      "11070": "중랑구", "11080": "성북구", "11090": "강북구", "11100": "도봉구", "11110": "노원구", "11120": "은평구",
      "11130": "서대문구", "11140": "마포구", "11150": "양천구", "11160": "강서구", "11170": "구로구", "11180": "금천구",
      "11190": "영등포구", "11200": "동작구", "11210": "관악구", "11220": "서초구", "11230": "강남구", "11240": "송파구",
      "11250": "강동구"}
SCALES = ("tract", "dong", "gu")
SCALE_KO = {"tract": "집계구", "dong": "행정동", "gu": "자치구"}
TOPK = {"tract": .10, "dong": .10, "gu": .20}          # 자치구는 25개라 상위 10% 대신 상위 5곳(20%)


def unit_of(tract16, scale):
    """집계구 코드(13자리, 2016 경계) → 단위 코드. 행정동 = 앞 7자리(2016 행정동 424개), 자치구 = 앞 5자리."""
    s = pd.Series(tract16) if not isinstance(tract16, pd.Series) else tract16
    return {"tract": s, "dong": s.str[:7], "gu": s.str[:5]}[scale]


def parse_scales(argv):
    """--scale=tract|dong|gu|all (기본 all)."""
    v = next((a.split("=", 1)[1] for a in argv if a.startswith("--scale=")), "all")
    return SCALES if v == "all" else tuple(v.split(","))


# ---------------------------------------------------------------- 자료 불러오기
def load_census():
    """인구총조사 2024 (2016 집계구로 변환), 연령 3구간 + all. 서울 합계 933.5만(외국인 포함)."""
    r = pd.read_parquet(P["census"]).set_index("tract16")[AGES]
    r["all"] = r.sum(1)
    return r


def load_field(path=None):
    z = pd.read_parquet(path or P["field"], columns=["tract16", "summer", "season", "hour", "dT_hat"])
    return z.rename(columns={"summer": "year"})


def load_livingpop(anchor="24h", raw=False):
    """내국인 생활인구 (집계구 × 연도 × 계절 × 시각, 계절 일수의 합). n_days = 그 계절 일수.
    연령 보정: 연도·연령마다 '기준 시간대(anchor) 평균 재실 인구'를 인구총조사 합계에 맞추는 단일 배율.
    배율은 모든 집계구(19,153개)의 생활인구로 구한다(본문과 같음). raw=True 면 보정하지 않는다."""
    lp = pd.read_parquet(P["livingpop"]).rename(columns={"tract": "tract16", "summer": "year"})
    if raw: return lp
    tot = load_census().sum(); hs = ANCHORS[anchor]
    days = lp.groupby(["year", "season"]).n_days.max().groupby("year").sum()
    for a in AGES:
        for y in (2024, 2025):
            m = lp.year == y; mh = m & lp.hour.isin(hs)
            lp.loc[m, a] = lp.loc[m, a] * (tot[a] / (lp.loc[mh, a].sum() / (len(hs) * days[y])))
    lp["all"] = lp[AGES].sum(1)
    return lp


def build_panel(field=None, anchor="24h", census_only=True):
    """분석 패널: 집계구 × 연도 × 계절 × 시각. 열: dT, 연령별 생활인구(PA, 인시), 인구총조사(res_*), PR_*(거주 인시), period.
    census_only=True 면 인구총조사에 있는 집계구(19,023개)만 쓴다(본문 H1–H5 와 같음)."""
    Z = load_field(field); lp = load_livingpop(anchor); res = load_census()
    M = Z.merge(lp[["tract16", "year", "season", "hour", "n_days"] + GROUPS], on=["tract16", "year", "season", "hour"])
    M = M.merge(res.add_prefix("res_"), left_on="tract16", right_index=True, how="inner" if census_only else "left").fillna({f"res_{g}": 0 for g in GROUPS})
    nd = M.groupby(["year", "season"]).n_days.transform("max")
    for g in GROUPS:
        M[f"PA_{g}"] = M[g]; M[f"PR_{g}"] = M[f"res_{g}"] * nd
    M["period"] = np.where(M.hour.isin(NIGHT), "night", "day")
    return M.rename(columns={"dT_hat": "dT"})


def to_units(M, scale, cols, key=("year", "season", "hour")):
    """패널을 단위로 집계. cols 는 합하고, dT 는 거주 인구 가중 평균으로 바꾼다."""
    if scale == "tract":
        return M.rename(columns={"tract16": "u"})[["u", *key, "dT", "res_all", *cols]].copy()
    m = M.assign(u=unit_of(M.tract16, scale), dw=M.dT * M.res_all)
    U = m.groupby(["u", *key]).agg(**{c: (c, "sum") for c in cols}, dw=("dw", "sum"), res_all=("res_all", "sum"), dm=("dT", "mean")).reset_index()
    U["dT"] = np.where(U.res_all > 0, U.dw / U.res_all.where(U.res_all > 0, 1), U.dm)
    return U.drop(columns=["dw", "dm"])


def unit_exposure(M, scale, groups=("all",), key=("year", "season", "period")):
    """장소의 노출 총량 = 단위 안 집계구 노출(집계구 ΔT × 인구)의 합. 순위·일치 지표용."""
    m = M.assign(u=unit_of(M.tract16, scale))
    for g in groups:
        m[f"EA_{g}"] = m.dT * m[f"PA_{g}"]; m[f"ER_{g}"] = m.dT * m[f"PR_{g}"]
    return m.groupby(["u", *key])[[f"{x}_{g}" for g in groups for x in ("EA", "ER")]].sum().reset_index()


# ---------------------------------------------------------------- 지표
def top_overlap(a, b, k):
    """상위 k 비율(또는 개수)의 일치율(%). 무작위면 k×100%."""
    n = k if isinstance(k, int) else max(int(round(len(a) * k)), 1)
    return 100 * len(set(a.nlargest(n).index) & set(b.nlargest(n).index)) / n


def dissimilarity(a, b):
    """비유사도(%): ½ Σ |a 비중 − b 비중|. 한 배치를 다른 배치로 바꾸려면 최소 몇 %가 옮겨야 하나."""
    a, b = a.align(b, fill_value=0)
    return 50 * (a / a.sum() - b / b.sum()).abs().sum()


def rho(a, b):
    a, b = a.align(b, fill_value=0)
    return float(spearmanr(a, b)[0])


def dong_names():
    """행정동 코드(7자리, 2016) → 'OO구 OO동'. SGIS 2016 행정동 경계를 공간 결합해 붙인다(없으면 빈 dict)."""
    import geopandas as gpd
    fs = sorted(glob.glob(str(P["dong_names"] / "emd_*.geojson")))
    if not fs: return {}
    nm = pd.concat([gpd.read_file(f) for f in fs]).set_crs(5179, allow_override=True)
    B = gpd.read_file(P["boundary"]).set_crs(5179, allow_override=True)
    B["dong"] = B.TOT_REG_CD.astype(str).str[:7]
    pt = gpd.GeoDataFrame(geometry=B.dissolve("dong").geometry.representative_point(), crs=5179)
    j = gpd.sjoin(pt, nm[["adm_nm", "geometry"]], how="left", predicate="within").groupby(level=0).adm_nm.first()
    return {k: " ".join(v.split()[1:]) for k, v in j.dropna().items()}


def unit_label(code, scale, names=None):
    if scale == "gu": return GU.get(code[:5], code)
    if scale == "dong": return (names or {}).get(code, code)
    return code


def save(obj, name):
    import json
    P["out"].mkdir(parents=True, exist_ok=True)
    json.dump(obj, open(P["out"] / f"{name}.json", "w"), ensure_ascii=False, indent=1, default=float)


def fmt(x, nd=3):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else (f"{x:+.{nd}f}" if isinstance(x, float) else str(x))

"""
s01_inventory_local.py - 로컬 원본(D14~D19, metadata 정류장 표본) 인벤토리 (1단계)

원본은 읽기만 한다. 결과는 outputs/eda_bus65/ 의 작은 CSV만 쓴다.
  inventory_files.csv   파일별 인코딩, 행 수, 컬럼 수, 기간, 이상값
  inventory_columns.csv 파일 묶음별 컬럼 목록
  d16_monthly_totals.csv  D16 월별 승차 합(시간대 합) vs D15 같은 달 일별 승차 합
실행: python outputs/eda_bus65/s01_inventory_local.py   (저장소 최상위에서, 약 3~5분)
"""
from pathlib import Path
import pandas as pd
import pyarrow.csv as pv

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw"; OUT = ROOT / "outputs/eda_bus65"


def read(f, cols=None):
    """utf-8 → cp949 순서로 시도. 모든 컬럼 문자열."""
    for enc in ("utf-8", "cp949"):
        try:
            ro = pv.ReadOptions(encoding=enc, block_size=1 << 26)
            co = pv.ConvertOptions(column_types=None, include_columns=cols, strings_can_be_null=False)
            t = pv.read_csv(f, read_options=ro, convert_options=co,
                            parse_options=pv.ParseOptions(newlines_in_values=False))
            df = t.to_pandas()
            return df.astype(str), enc
        except (UnicodeDecodeError, Exception) as e:  # pyarrow는 디코딩 오류를 ArrowInvalid로 낸다
            if enc == "cp949": raise
            last = e
    raise last


def num(s):
    return pd.to_numeric(s.str.replace(",", ""), errors="coerce")


rows, colrows = [], []

# D15 버스 일별 (24개월)
d15_month = {}
for f in sorted((RAW / "D15_bus_daily").glob("*.csv")):
    d, enc = read(f)
    b, a = num(d["승차총승객수"]), num(d["하차총승객수"])
    key = ["사용일자", "노선번호", "표준버스정류장ID"]
    ars = d["버스정류장ARS번호"]
    rows.append(dict(ds="D15", file=f.name, enc=enc, n_rows=len(d), n_cols=d.shape[1], period_min=d["사용일자"].min(), period_max=d["사용일자"].max(),
                     n_days=d["사용일자"].nunique(), n_stop_std=d["표준버스정류장ID"].nunique(), n_ars=ars.nunique(), n_route=d["노선번호"].nunique(),
                     ars_bad=int((~ars.str.fullmatch(r"\d{5}")).sum()), ars_bad_examples="|".join(ars[~ars.str.fullmatch(r"\d{5}")].unique()[:5]),
                     neg=int((b < 0).sum() + (a < 0).sum()), nonnum=int(b.isna().sum() + a.isna().sum()), zero_board_share=round(float((b == 0).mean()), 4),
                     dup_full=int(d.duplicated().sum()), dup_key=int(d.duplicated(key).sum()), board_sum=float(b.sum())))
    d15_month[f.stem[-6:]] = float(b.sum())
    if not colrows or colrows[-1]["ds"] != "D15": colrows.append(dict(ds="D15", cols="|".join(d.columns)))
    print(f.name, len(d), flush=True)

# D16 버스 시간대별 (월 합계)
d16_month = {}
for f in sorted((RAW / "D16_bus_hourly").glob("*.csv")):
    d, enc = read(f)
    bc = [c for c in d.columns if c.endswith("승차총승객수")]; ac = [c for c in d.columns if c.endswith("하차총승객수")]
    B = d[bc].apply(num); A = d[ac].apply(num)
    key = ["사용년월", "노선번호", "표준버스정류장ID"]
    ars = d["버스정류장ARS번호"]
    rows.append(dict(ds="D16", file=f.name, enc=enc, n_rows=len(d), n_cols=d.shape[1], period_min=d["사용년월"].min(), period_max=d["사용년월"].max(),
                     n_days=None, n_stop_std=d["표준버스정류장ID"].nunique(), n_ars=ars.nunique(), n_route=d["노선번호"].nunique(),
                     ars_bad=int((~ars.str.fullmatch(r"\d{5}")).sum()), ars_bad_examples="|".join(ars[~ars.str.fullmatch(r"\d{5}")].unique()[:5]),
                     neg=int((B < 0).sum().sum() + (A < 0).sum().sum()), nonnum=int(B.isna().sum().sum() + A.isna().sum().sum()),
                     zero_board_share=round(float((B.sum(1) == 0).mean()), 4), dup_full=int(d.duplicated().sum()), dup_key=int(d.duplicated(key).sum()),
                     board_sum=float(B.sum().sum()), mode_types="|".join(f"{k}:{v}" for k, v in d["교통수단타입명"].value_counts().items())))
    d16_month[d["사용년월"].iloc[0]] = float(B.sum().sum())
    if colrows[-1]["ds"] != "D16": colrows.append(dict(ds="D16", cols="|".join(d.columns)))
    print(f.name, len(d), flush=True)
pd.DataFrame([dict(ym=k, d16_board=d16_month.get(k), d15_board=v, ratio_d16_d15=(d16_month.get(k) or float("nan")) / v) for k, v in sorted(d15_month.items())]
             ).to_csv(OUT / "d16_vs_d15_monthly_totals.csv", index=False, encoding="utf-8-sig")

# D17 권종별 승차
for f in sorted((RAW / "D17_subway_ticket_type").glob("*.csv")):
    d, enc = read(f)
    v = num(d["승차인원수"])
    cnt = d.groupby("권종").size()
    rows.append(dict(ds="D17", file=f.name, enc=enc, n_rows=len(d), n_cols=d.shape[1], period_min=d["수송연월"].min(), period_max=d["수송연월"].max(),
                     n_days=d["수송연월"].nunique(), n_stop_std=d["고유역번호(외부역코드)"].nunique(), neg=int((v < 0).sum()), nonnum=int(v.isna().sum()),
                     zero_board_share=round(float((v == 0).mean()), 4), dup_full=int(d.duplicated(subset=list(d.columns[1:])).sum()),
                     dup_key=int(d.duplicated(["고유역번호(외부역코드)", "수송연월", "권종"]).sum()), board_sum=float(v.sum()),
                     mode_types="|".join(f"{k}:{n}" for k, n in cnt.items())))
    colrows.append(dict(ds="D17 " + f.name[-12:-4], cols="|".join(d.columns)))

# D18 서울교통공사 역별 일별 시간대별 + 서울철도 표본
for f in sorted((RAW / "D18_subway_hourly").glob("*.csv")):
    d, enc = read(f)
    if "운행일자" in d.columns:  # 서울철도 표본
        v = num(d["승차총승객수"]); dc = "운행일자"; key = ["운행일자", "역ID", "승차시간구분", "30분시간구간ID"]
    else:
        dc = "수송일자" if "수송일자" in d.columns else "날짜"; hc = [c for c in d.columns[6:]]
        v = d[hc].apply(num).stack(); key = [dc, "역번호", d.columns[5]]
    rows.append(dict(ds="D18", file=f.name, enc=enc, n_rows=len(d), n_cols=d.shape[1], period_min=d[dc].min(), period_max=d[dc].max(),
                     n_days=d[dc].nunique(), n_stop_std=d[[c for c in d.columns if c in ("역번호", "역ID")][0]].nunique(),
                     neg=int((v < 0).sum()), nonnum=int(v.isna().sum()), zero_board_share=round(float((v == 0).mean()), 4),
                     dup_full=int(d.duplicated(subset=[c for c in d.columns if c != "연번"]).sum()), dup_key=int(d.duplicated(key).sum())))
    colrows.append(dict(ds="D18 " + f.name[:20], cols="|".join(d.columns)))

# D19 지하철 30분 OD 표본, D14 폭염저감시설, metadata 노선·정류장 표본
f = RAW / "D19_subway_od_30min_2021/서울시 지하철 30분단위 출발-도착 데이터.csv"; d, enc = read(f)
ym = d.iloc[:, 0] + "-" + d.iloc[:, 1]
rows.append(dict(ds="D19", file=f.name, enc=enc, n_rows=len(d), n_cols=d.shape[1], period_min=ym.min(), period_max=ym.max(), n_days=ym.nunique(),
                 dup_full=int(d.duplicated().sum()), mode_types="|".join(f"{k}:{n}" for k, n in d.iloc[:, 5].value_counts().items())))
colrows.append(dict(ds="D19", cols="|".join(d.columns)))
f = ROOT / "metadata/노선 및 정류장현황.csv"; d, enc = read(f)
rows.append(dict(ds="meta_stops", file=f.name, enc=enc, n_rows=len(d), n_cols=d.shape[1], n_stop_std=d["정류장ID"].nunique(), n_route=d["노선번호"].nunique(),
                 dup_full=int(d.duplicated().sum()), mode_types="|".join(f"{k}:{n}" for k, n in d["조합구분"].value_counts().items())))
colrows.append(dict(ds="meta_stops", cols="|".join(d.columns)))
for f in sorted((RAW / "D14_heat_mitigation_facility").glob("*.xlsx")):
    x = pd.read_excel(f, dtype=str)
    rows.append(dict(ds="D14", file=f.name, enc="xlsx", n_rows=len(x), n_cols=x.shape[1]))
    colrows.append(dict(ds="D14 " + f.name, cols="|".join(map(str, x.columns))))

pd.DataFrame(rows).to_csv(OUT / "inventory_files.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(colrows).to_csv(OUT / "inventory_columns.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(rows).drop(columns=["file"]).to_string())

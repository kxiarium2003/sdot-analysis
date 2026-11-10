"""s07_shelters.py - O 공통: 스마트쉼터 ARS 연결, 무더위쉼터 좌표 정리.

스마트쉼터: D14 `스마트쉼터 현황.xlsx`. 설치장소(없으면 상세주소)에서 5자리 또는 NN-NNN 형태 ARS 추출 → D21 판본 ARS와 일치, 주소 자치구 일치 확인.
좌표가 없어 "30m 안 가장 가까운 정류장" 연결은 할 수 없다. ID 없는 행은 미연결로 남긴다.
무더위쉼터: D7 목록 2개, 경도·위도 열 사용(지오코딩 안 함). 서울 경계(행정구역 D9) 안 좌표만.
출력(스크래치): shelters/smart_links_{연도}.parquet, cooling_{연도}.parquet
요약: s07_smart_link.csv(행별), s07_smart_unlinked.csv, s07_smart_summary.csv, s07_cooling_summary.csv, s07_cooling_type.csv
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd, geopandas as gpd

S = SCRATCH / "shelters"; S.mkdir(exist_ok=True)
sm = pd.read_excel(RAW_LOCAL / "D14_heat_mitigation_facility/스마트쉼터 현황.xlsx", header=3, dtype=str)
sm.columns = [c.strip() for c in sm.columns]
sm["시도"] = sm["시도"].str.strip()
sm["설치장소"] = sm["설치장소"].str.replace(r"\s+", " ", regex=True); sm["상세주소"] = sm["상세주소"].fillna("").str.replace(r"\s+", " ", regex=True)
PAT = re.compile(r"(?<![\d-])(\d{2})-?(\d{3})(?![\d-])")


def find(text):
    return ["".join(m) for m in PAT.findall(text or "") if "01" <= m[0] <= "25"]


def addr_gu(row):
    if row["시군구"] and row["시군구"] != "-":
        return row["시군구"]
    m = re.search(r"([가-힣]+구)", row["상세주소"])
    return m.group(1) if m else None


sumrows = []
for y in ("2024", "2025"):
    st = pd.read_parquet(SCRATCH / f"geo/stops_{y}.parquet")
    st["gu"] = st.gu5.map(GU_NAMES)
    ars2 = st.set_index("ars")
    rows = []
    for i, r in sm.iterrows():
        g = addr_gu(r)
        c1, c2 = find(r["설치장소"]), find(r["상세주소"])
        src = "설치장소" if c1 else "상세주소" if c2 else None
        cand = c1 or c2
        ok = [a for a in cand if a in ars2.index]
        ars = ok[0] if ok else (cand[0] if cand else None)
        rows.append(dict(row=i, 시군구=g, 시설명=r["시설명"], 설치장소=r["설치장소"], 상세주소=r["상세주소"], 설치년도=r["설치년도"], 공사중="공사중" in r["시설명"], ars후보=",".join(cand), 추출위치=src, ars=ars,
                         ars_in_d21=bool(ok), node=ars2.node.get(ars) if ok else None, d21_name=ars2.name.get(ars) if ok else None, d21_gu=ars2.gu.get(ars) if ok else None))
    L = pd.DataFrame(rows)
    L["gu일치"] = L.apply(lambda r: (r.d21_gu == r.시군구) if (r.ars_in_d21 and r.시군구) else None, axis=1)
    L_csv = L.rename(columns={"ars_in_d21": "D21 서울시 버스정류소 위치정보 ARS 일치", "d21_name": "D21 서울시 버스정류소 위치정보 정류소명", "d21_gu": "D21 서울시 버스정류소 위치정보 자치구"})
    L_csv.to_csv(OUT / f"s07_smart_link_{y}.csv", index=False, encoding="utf-8-sig")
    use = L[L.ars_in_d21 & ~L.공사중 & (L.설치년도.astype(int) <= int(y))]
    use_unique = use.drop_duplicates("node")
    use_unique[["node", "ars", "설치년도"]].to_parquet(S / f"smart_links_{y}.parquet", index=False)
    sumrows.append(dict(판본=y, 행수=len(L), 공사중행=int(L.공사중.sum()), ID후보_있음=int(L.ars후보.ne("").sum()), D21_LINK_ROWS=int(L.ars_in_d21.sum()), 연결률=L.ars_in_d21.mean(),
                        주소구일치=int((L.gu일치 == True).sum()), 주소구불일치=int((L.gu일치 == False).sum()), 사용_행=len(use), 사용_정류장=use_unique.node.nunique(),
                        좌표로_30m연결_가능행=0))
    if y == "2025":
        L_csv[~L.ars_in_d21].to_csv(OUT / "s07_smart_unlinked.csv", index=False, encoding="utf-8-sig")
        print(L[L.ars_in_d21].sample(25, random_state=2)[["설치장소", "상세주소", "ars", "d21_name", "시군구", "d21_gu", "추출위치"]].to_string())
        print(L[(L.gu일치 == False)][["설치장소", "상세주소", "ars", "d21_name", "시군구", "d21_gu"]].to_string())
        print(L[~L.ars_in_d21][["시군구", "시설명", "설치장소", "상세주소", "ars후보"]].to_string())
pd.DataFrame(sumrows).rename(columns={"D21_LINK_ROWS": "D21 서울시 버스정류소 위치정보 연결 행", "판본": "D21 서울시 버스정류소 위치정보 판본"}).to_csv(OUT / "s07_smart_summary.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(sumrows).T.to_string())

dong = gpd.read_file(DONG_SHP).set_crs("EPSG:5179", allow_override=True)
seoul = dong.union_all()
cool, types = [], []
for y, f in (("2024", "01. 무더위쉼터 목록(20240717 기준).xlsx"), ("2025", "02. 무더위쉼터 목록(20250916 기준).xlsx")):
    d = pd.read_excel(RAW_LOCAL / "D7_cooling_shelter" / f, header=None, dtype=str)
    h4 = d.iloc[4].tolist(); lonc, latc = h4.index("경도"), h4.index("위도")
    t = d.iloc[5:].copy(); nm = t[1]; ty = t[4]
    q = pd.DataFrame({"name": nm, "road": t[2], "type": ty, "lon": pd.to_numeric(t[lonc], errors="coerce"), "lat": pd.to_numeric(t[latc], errors="coerce")})
    q = q[q.name.notna()]
    n0 = len(q); miss = int(q.lon.isna().sum() | q.lat.isna().sum())
    ok = q.dropna(subset=["lon", "lat"])
    g = gpd.GeoDataFrame(ok, geometry=gpd.points_from_xy(ok.lon, ok.lat), crs=4326).to_crs("EPSG:5179")
    inside = g.within(seoul)
    gi = g[inside].copy(); gi["x"] = gi.geometry.x; gi["y"] = gi.geometry.y
    pd.DataFrame(gi.drop(columns="geometry")).to_parquet(S / f"cooling_{y}.parquet", index=False)
    cool.append(dict(연도=y, 파일=f, 행=n0, 좌표결측=miss, 서울경계밖=int((~inside).sum()), 사용=len(gi), 좌표중복=int(gi.duplicated(["x", "y"]).sum())))
    tv = gi["type"].fillna("(결측)").value_counts().rename("n").reset_index(); tv.insert(0, "연도", y); types.append(tv)
    print(g[~inside][["name", "lon", "lat"]].head(10).to_string())
pd.DataFrame(cool).to_csv(OUT / "s07_cooling_summary.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(cool).T.to_string())
pd.concat(types).to_csv(OUT / "s07_cooling_type.csv", index=False, encoding="utf-8-sig"); print(pd.concat(types).to_string())

"""s07_limit_stations.py - C-0: D22 서울 401행 중 D26에 없는 역 목록.

출력: limit_stations_without_d26.csv, s07_limit_by_route.csv, s07_limit_summary.csv
"""
import sys, os, re, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import pandas as pd

st = pd.read_parquet(SCRATCH / "geo/stations.parquet")
s = st[st.seoul_d9].copy()
print("서울 행", len(s))
ids = set()
for p in glob.glob(str(SCRATCH / "raw/d26/*.csv")):
    d = pd.read_csv(p, encoding="cp949", dtype=str, keep_default_na=False)
    m = pd.to_datetime(d["수송일자"]).dt.strftime("%Y%m")
    ids |= set(d.loc[m.isin(MONTHS), "역번호"].astype(int).map(lambda x: f"{x:04d}"))
con = duck()
d25 = set(r[0] for r in con.execute(f"SELECT DISTINCT board_id FROM read_parquet('{SCRATCH}/d25long/*.parquet') WHERE length(board_id)=4").fetchall())
d28 = pd.read_csv(ROOT / "outputs/prep_v2/D28_station_id_match.csv", dtype=str, encoding="utf-8-sig")
d28set = set(d28.BLDN_ID.str.zfill(4))
d29set = {f"{i}" for i in range(4126, 4139)}
gun = GU_NAMES


def norm(n):
    n = re.sub(r"\(.*?\)", "", str(n)).replace(" ", "").strip()
    return re.sub(r"역$", "", n) if len(n) > 2 else n


s["nm"] = s.name.map(norm)
s["in_d26"] = s.bldn.isin(ids)
g = s.groupby("nm").agg(routes=("route", list), bld=("bldn", list), hasd26=("in_d26", list))


def operator(r):
    if re.fullmatch(r"[1-8]호선", r): return "서울교통공사(1~8호선 표기) [확인됨: D26·D27 페이지 관할 설명]"
    if r == "9호선(연장)": return "서울교통공사 [확인됨: OA-22440]"
    if r == "9호선": return "서울시메트로9호선 [추정: 지시서 구분]"
    if r in ("경부선", "경인선", "경원선", "중앙선", "분당선", "서해선", "경강선"): return "한국철도공사 [확인됨: 포털 15100373 설명 열거]"
    if r in ("경의중앙선", "경춘선"): return "한국철도공사 [추정: 노선명]"
    if r == "공항철도1호선": return "공항철도 [추정: 노선명]"
    if r in ("우이신설선", "신림선"): return f"{r} 운영사 [추정: 노선명]"
    return "[미확인]"


rows = []
for _, r in s[~s.in_d26].iterrows():
    gr = g.loc[r.nm]
    others = [x for x in gr.routes if x != r.route]
    other_d26 = [x for x, a in zip(gr.routes, gr.hasd26) if a and x != r.route]
    rows.append({"호선": r.route, "역명": r["name"], "BLDN_ID": r.bldn, "운영기관": operator(r.route), "자치구": gun.get(r.gu_final, "[미확인]"),
                 "환승역": len(gr.routes) >= 2, "함께_지나는_노선": ",".join(others), "다른노선_D26실측있음": ",".join(other_d26), "D26있는_다른노선_유무": bool(other_d26),
                 "D25승차있음": r.bldn in d25, "D28무임자료있음": r.bldn in d28set, "D29자료있음": r.bldn in d29set,
                 "어느자료에도없음": (r.bldn not in d28set) and (r.bldn not in d29set)})
o = pd.DataFrame(rows).sort_values(["호선", "역명"]); o.to_csv(OUT / "limit_stations_without_d26.csv", index=False, encoding="utf-8-sig")
print(len(o), "(표 대상)")
sm = o.groupby("호선").agg(역수=("BLDN_ID", "count"), 환승역=("환승역", "sum"), D26있는노선과환승=("D26있는_다른노선_유무", "sum"), D25승차있음=("D25승차있음", "sum"), D28있음=("D28무임자료있음", "sum"), D29있음=("D29자료있음", "sum"), 어느자료에도없음=("어느자료에도없음", "sum")).sort_values("역수", ascending=False)
sm.to_csv(OUT / "s07_limit_by_route.csv", encoding="utf-8-sig"); print(sm.to_string()); print(sm.sum().to_dict())
print(o[o["어느자료에도없음"]][["호선", "역명", "BLDN_ID", "운영기관", "자치구", "D25승차있음"]].to_string(index=False))
print(o[o["호선"].str.fullmatch(r"[1-8]호선")][["호선", "역명", "BLDN_ID", "D28무임자료있음", "자치구"]].to_string(index=False))
print("환승역 합", int(o["환승역"].sum()), "D26있는노선과환승", int(o["D26있는_다른노선_유무"].sum()))

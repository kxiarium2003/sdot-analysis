"""s08_o_analysis.py - O0 정류장 변화, O1 커버리지, O2 스마트쉼터 추가, O3 무더위쉼터 MCLP(그리디), O4 비교.

수요(연도별, 있는 달 평균): w65 = 11~17시(시 라벨 11,12,…,17) 65+ 승차(중간값) 하루 평균 [주 가중치].
민감도: w65_lo, w65_hi, wtot(총 승차), w65_all(0~23시). 거리 EPSG:5179 직선. 반경 300m(민감도 150, 500m).
O1: (a) 스마트쉼터 정류장 (b) 무더위쉼터 r m 안 (c) a∪b (d) 커버 없음.
O2: 후보 = a·b 모두 아님. w 순 상위 p. 정류장 자체만 커버.
O3: 후보지 = 그 연도 전체 정류장 위치, 수요 = (d) 정류장. 반경 r m 커버, 그리디 p개.
정수계획 검증: pulp·ortools 미설치로 하지 않음.
출력: o0_stop_change.csv, o1_coverage_city.csv, o1_coverage_gu.csv, o2_selected_*.csv, o3_selected_*.csv, o2_o3_summary.csv, o4_overlap.csv
"""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s00_common import *
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix

fs = sorted(glob.glob(str(SCRATCH / "est/est_*.parquet")))
YEARS = sorted({os.path.basename(f)[4:8] for f in fs})
PS2, PS3 = [50, 100, 200], [10, 30, 50]
print("years", YEARS, [os.path.basename(f) for f in fs])


def demand(y):
    f = [x for x in fs if os.path.basename(x)[4:8] == y]
    c = duck(); s = "[" + ",".join(f"'{x}'" for x in f) + "]"
    nd = c.execute(f"SELECT count(DISTINCT date) FROM read_parquet({s})").fetchone()[0]
    d = c.execute(f"""SELECT node, SUM(CASE WHEN hour BETWEEN 11 AND 17 THEN board65_mid ELSE 0 END)/{nd} w65,
                 SUM(CASE WHEN hour BETWEEN 11 AND 17 THEN board65_lo ELSE 0 END)/{nd} w65_lo,
                 SUM(CASE WHEN hour BETWEEN 11 AND 17 THEN board65_hi ELSE 0 END)/{nd} w65_hi,
                 SUM(CASE WHEN hour BETWEEN 11 AND 17 THEN board ELSE 0 END)/{nd} wtot,
                 SUM(board65_mid)/{nd} w65_all, SUM(board)/{nd} wtot_all FROM read_parquet({s}) GROUP BY 1""").df()
    st = pd.read_parquet(SCRATCH / f"geo/stops_{y}.parquet")[["node", "ars", "name", "gu5", "x", "y", "lon", "lat"]]
    st["gu"] = st.gu5.map(GU_NAMES)
    return st.merge(d, on="node", how="left").fillna({k: 0 for k in d.columns if k != "node"}), nd, len(f)


D = {}; ND = {}
for y in YEARS:
    D[y], ND[y], m = demand(y); print(y, "stops", len(D[y]), "days", ND[y], "months", m, "w65 sum", round(D[y].w65.sum()))


def cover(y, r):
    st = D[y]
    sm = set(pd.read_parquet(SCRATCH / f"shelters/smart_links_{y}.parquet").node)
    c = pd.read_parquet(SCRATCH / f"shelters/cooling_{y}.parquet")
    tree = cKDTree(c[["x", "y"]].to_numpy())
    near = tree.query_ball_point(st[["x", "y"]].to_numpy(), r=r)
    return st.node.isin(sm).to_numpy(), np.array([len(n) > 0 for n in near])


# O0
if len(YEARS) == 2:
    a, b = D["2024"], D["2025"]
    A, B = set(a.node), set(b.node)
    groups = {"2024에만": A - B, "2025에만": B - A, "둘 다": A & B}
    rows = []
    for g, s in groups.items():
        row = dict(그룹=g, 정류장수=len(s))
        for y, t in (("2024", a), ("2025", b)):
            m = t.node.isin(s)
            row[f"정류장수_{y}"] = int(m.sum()); row[f"w65비중_{y}"] = t[m].w65.sum() / t.w65.sum(); row[f"하루65승차비중_{y}"] = t[m].w65_all.sum() / t.w65_all.sum(); row[f"하루65승차_{y}"] = t[m].w65_all.sum()
        rows.append(row)
    pd.DataFrame(rows).to_csv(OUT / "o0_stop_change.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(rows).round(4).to_string())
# O1
city, gu_rows = [], []
for y in YEARS:
    for r in (300, 150, 500):
        sa, sb = cover(y, r)
        st = D[y]
        c = sa | sb; none = ~c
        for name, col in (("w65(11~17시 65+)", "w65"), ("wtot(11~17시 총승차)", "wtot"), ("w65_all(0~23시 65+)", "w65_all")):
            t = st[col].to_numpy(); city.append(dict(연도=y, 반경=r, 기준=name, 총량_하루=t.sum(), a스마트=t[sa].sum() / t.sum(), b무더위=t[sb].sum() / t.sum(), c합=t[c].sum() / t.sum(), d없음=t[none].sum() / t.sum(), 정류장_a=int(sa.sum()), 정류장_b=int(sb.sum()), 정류장_c=int(c.sum()), 정류장_d=int(none.sum())))
            if r == 300 and col != "w65_all":
                g = pd.DataFrame({"gu": st.gu, "v": t, "a": t * sa, "b": t * sb, "c": t * c, "d": t * none}).groupby("gu").sum()
                g2 = pd.DataFrame({"연도": y, "기준": name, "총량_하루": g.v, "a스마트": g.a / g.v, "b무더위": g.b / g.v, "c합": g.c / g.v, "d없음": g.d / g.v}).reset_index()
                gu_rows.append(g2)
pd.DataFrame(city).to_csv(OUT / "o1_coverage_city.csv", index=False, encoding="utf-8-sig")
pd.concat(gu_rows).to_csv(OUT / "o1_coverage_gu.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(city).round(4).to_string())


def o2(st, w, sa, sb):
    cand = ~(sa | sb); idx = np.where(cand)[0]
    order = idx[np.lexsort((st.node.to_numpy()[idx], -w[idx]))]
    return order


def o3(st, w, sa, sb, r, p):
    xy = st[["x", "y"]].to_numpy(); demand_i = np.where(~(sa | sb))[0]; n = len(st)
    tree = cKDTree(xy[demand_i])
    lists = tree.query_ball_point(xy, r=r)   # 후보(전체 정류장) → 수요 인덱스
    rows = np.concatenate([np.full(len(l), i) for i, l in enumerate(lists)]); cols = np.concatenate([np.array(l, dtype=int) for l in lists])
    A = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, len(demand_i)))
    rem = w[demand_i].astype(float).copy(); sel, gains = [], []
    node = st.node.to_numpy()
    for _ in range(p):
        g = A.dot(rem)
        m = g.max()
        ties = np.where(g >= m - 1e-9)[0]
        j = ties[np.argmin(node[ties])]
        covered = A[j].indices
        rem[covered] = 0
        sel.append(int(j)); gains.append(float(m))
    return sel, gains


def run(y, wcol, r, tag):
    st = D[y]; w = st[wcol].to_numpy(); sa, sb = cover(y, r)
    out = {}
    order2 = o2(st, w, sa, sb)
    for p in PS2:
        out[("O2", p)] = order2[:p]
    sel, gains = o3(st, w, sa, sb, r, max(PS3))
    for p in PS3:
        out[("O3", p)] = np.array(sel[:p])
    return out, dict(y=y, wcol=wcol, r=r, tag=tag, order2=order2, sel=sel, gains=gains, sa=sa, sb=sb)


base_y = "2025" if "2025" in YEARS else YEARS[0]
Mbase, Info = run(base_y, "w65", 300, "기준(65+ 11~17시, 300m)")
st = D[base_y]; w = st.w65.to_numpy(); sa, sb = Info["sa"], Info["sb"]
tot = w.sum(); un = w[~(sa | sb)].sum()


def covered_w(st, w, sa, sb, idx, kind, r):
    if kind == "O2":
        return w[idx].sum()
    xy = st[["x", "y"]].to_numpy(); dem = ~(sa | sb)
    near = cKDTree(xy[idx]).query_ball_point(xy[dem], r=r)
    return w[dem][[len(n) > 0 for n in near]].sum()


# 기준 결과 표·목록
S = []
for (k, p), idx in Mbase.items():
    cov = covered_w(st, w, sa, sb, idx, k, 300)
    S.append(dict(방법=k, p=p, 기준연도=base_y, 신규커버_w65_하루=cov, 비율_전체=cov / tot, 비율_미커버=cov / un, 전체_w65=tot, 미커버_w65=un))
pd.DataFrame(S).to_csv(OUT / "o2_o3_summary.csv", index=False, encoding="utf-8-sig"); print(pd.DataFrame(S).round(4).to_string())
g = Info["gains"]; order2 = Info["order2"]
pd.DataFrame({"선택순서": range(1, 201), "ars": st.ars.iloc[order2[:200]].to_numpy(), "정류장명": st.name.iloc[order2[:200]].to_numpy(), "자치구": st.gu.iloc[order2[:200]].to_numpy(), "w_65승차_11_17시_하루평균": w[order2[:200]], "하루총승차_11_17시": st.wtot.iloc[order2[:200]].to_numpy()}).to_csv(OUT / f"o2_selected_{base_y}.csv", index=False, encoding="utf-8-sig")
s3 = Info["sel"]
pd.DataFrame({"선택순서": range(1, 51), "ars": st.ars.iloc[s3].to_numpy(), "정류장명": st.name.iloc[s3].to_numpy(), "자치구": st.gu.iloc[s3].to_numpy(), "w_65승차_11_17시_하루평균": w[s3], "그리디_추가커버_w65": g, "무더위쉼터_위치대용": True}).to_csv(OUT / f"o3_selected_{base_y}.csv", index=False, encoding="utf-8-sig")

# O4
variants = [("총승차 가중(11~17시)", base_y, "wtot", 300), ("65+ 하한 가중", base_y, "w65_lo", 300), ("65+ 상한 가중", base_y, "w65_hi", 300), ("65+ 하루 전체(0~23시)", base_y, "w65_all", 300), ("반경 150m", base_y, "w65", 150), ("반경 500m", base_y, "w65", 500)]
if len(YEARS) == 2:
    variants.append(("2024 기준", "2024", "w65", 300))
OV = []
base_nodes = {k: set(st.node.iloc[v]) for k, v in Mbase.items()}
ALLSEL = []
for k, idx in Mbase.items():
    ALLSEL.append(pd.DataFrame({"변형": "기준(65+ 11~17시, 300m)", "방법": k[0], "p": k[1], "순서": range(1, len(idx) + 1), "node": st.node.iloc[idx].to_numpy(), "ars": st.ars.iloc[idx].to_numpy(), "정류장명": st.name.iloc[idx].to_numpy()}))
for name, y, col, r in variants:
    M, info = run(y, col, r, name); sv = D[y]
    for k, idx in M.items():
        nodes = set(sv.node.iloc[idx]); b = base_nodes[k]
        cov_var = np.nan
        if y == base_y:
            sa2, sb2 = info["sa"], info["sb"]
            if r == 300:
                cov_var = covered_w(st, w, sa, sb, idx, k[0], 300)
            else:  # 반경 변형은 해당 반경 정의의 신규 커버량
                cov_var = covered_w(sv, sv.w65.to_numpy(), sa2, sb2, idx, k[0], r)
        cov_base = covered_w(st, w, sa, sb, Mbase[k], k[0], 300) if r == 300 else np.nan
        OV.append(dict(변형=name, 방법=k[0], p=k[1], 겹침개수=len(nodes & b), 합집합=len(nodes | b), Jaccard=len(nodes & b) / len(nodes | b), 기준_65커버=cov_base, 변형선택의_65커버=cov_var, 커버차이=(cov_var - cov_base) if r == 300 and y == base_y else np.nan))
        ALLSEL.append(pd.DataFrame({"변형": name, "방법": k[0], "p": k[1], "순서": range(1, len(idx) + 1), "node": sv.node.iloc[idx].to_numpy(), "ars": sv.ars.iloc[idx].to_numpy(), "정류장명": sv.name.iloc[idx].to_numpy()}))
ov = pd.DataFrame(OV); ov.to_csv(OUT / "o4_overlap.csv", index=False, encoding="utf-8-sig"); print(ov.round(3).to_string())
pd.concat(ALLSEL).to_csv(OUT / "o4_selected_all_variants.csv", index=False, encoding="utf-8-sig")
# 그림용(스크래치)
FG = SCRATCH / "fig"; FG.mkdir(exist_ok=True)
pd.DataFrame({"node": st.node, "x": st.x, "y": st.y, "w65": w, "smart": sa, "cool": sb}).to_parquet(FG / f"stops_{base_y}.parquet", index=False)
pd.DataFrame({"node": st.node.iloc[s3], "order": range(1, 51)}).to_parquet(FG / f"o3_sel_{base_y}.parquet", index=False)

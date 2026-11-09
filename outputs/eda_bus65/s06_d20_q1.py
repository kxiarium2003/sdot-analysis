"""
s06_d20_q1.py - D20 대중교통 이용패턴(OA-21216)으로 Q1: 경로 승객의 버스 포함 통행 비율과 월별 안정성, 과소집계 점검

입력(읽기만): data/raw/D20_transit_pattern/서울시 대중교통 이용패턴 정보.csv (cp949, 빈칸 = 0; metadata/D20_transit_pattern.md)
         outputs/eda_bus65/q2_monthly_citywide.csv, q2_station_ratio_summer2025.csv (s03), q1_d19_sample_usertype.csv (s03),
         outputs/eda_bus65/d12_dep_dong_hour.csv (s02)
출력(outputs/eda_bus65/):
  q1_d20_pattern_class.csv     패턴 → 분류(버스만 / 버스+지하철 / 지하철만 / 경기버스 포함 …), 구간 수, 서울버스 구간 수
  q1_d20_class_totals.csv      분류별 유형별 승객 합과 경로 비중(분모 둘: 총_승객수, 유형 합)
  q1_d20_monthly.csv           월별 경로 승객의 분류별 비율과 변동계수
  q1_d20_compare.csv           비교 1(지하철: D20 vs D17×D19) · 비교 2(버스: D20 vs D12)
  fig_q1_d20_monthly.png
실행: python outputs/eda_bus65/s06_d20_q1.py
"""
from pathlib import Path
import re
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]; OUT = ROOT / "outputs/eda_bus65"
plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e", "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb", "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": .6})
COL = {"버스만": "#2a78d6", "버스+지하철": "#eb6834", "지하철만": "#1baf7a", "경기버스 포함(서울버스 포함)": "#eda100", "경기버스 포함(서울버스 없음)": "#e87ba4"}
TYPES = ["총_승객수_일반", "총_승객수_어린이", "총_승객수_청소년", "총_승객수_경로", "총_승객수_장애인"]

d = pd.read_csv(ROOT / "data/raw/D20_transit_pattern/서울시 대중교통 이용패턴 정보.csv", encoding="cp949", dtype=str)
num = ["총_승객수"] + TYPES
d[num] = d[num].apply(pd.to_numeric).fillna(0)          # 빈칸 = 0 (메타데이터 문서)
d["ym"] = d.기준_날짜.str[:6]; d["type_sum"] = d[TYPES].sum(1)


def classify(p):
    seg = re.findall(r"\[(.+?)\]", p)
    b, g, s = seg.count("버스"), seg.count("경기버스"), seg.count("지하철")
    if g: cls = "경기버스 포함(서울버스 포함)" if b else "경기버스 포함(서울버스 없음)"
    elif b and s: cls = "버스+지하철"
    elif b: cls = "버스만"
    else: cls = "지하철만"
    return pd.Series(dict(cls=cls, n_seg=len(seg), n_bus=b, n_gbus=g, n_sub=s, has_bus=b > 0))


P = pd.DataFrame({"pattern": d.목적통행_패턴.unique()}); P = P.join(P.pattern.apply(classify))
P.to_csv(OUT / "q1_d20_pattern_class.csv", index=False, encoding="utf-8-sig")
d = d.merge(P, left_on="목적통행_패턴", right_on="pattern")
assert set(re.findall(r"\[(.+?)\]", " ".join(P.pattern))) == {"버스", "경기버스", "지하철"}

# 분류별 합계
T = d.groupby("cls")[num + ["type_sum"]].sum()
T.loc["합계"] = T.sum()
T["경로_비중_총승객"] = T.총_승객수_경로 / T.총_승객수; T["경로_비중_유형합"] = T.총_승객수_경로 / T.type_sum
T["경로승객_중_분류비율"] = T.총_승객수_경로 / T.loc["합계", "총_승객수_경로"]
T["일반_중_분류비율"] = T.총_승객수_일반 / T.loc["합계", "총_승객수_일반"]
T.to_csv(OUT / "q1_d20_class_totals.csv", encoding="utf-8-sig")
print(T[["총_승객수", "총_승객수_경로", "경로_비중_총승객", "경로승객_중_분류비율", "일반_중_분류비율"]].round(4).to_string())
eld = d.groupby("has_bus").총_승객수_경로.sum(); print("경로 승객 중 서울버스 포함 통행 %.4f" % (eld[True] / eld.sum()))

# 월별 안정성
M = d.groupby(["ym", "cls"]).총_승객수_경로.sum().unstack(); M = M.div(M.sum(1), axis=0)
M["서울버스 포함"] = d.groupby(["ym", "has_bus"]).총_승객수_경로.sum().unstack()[True] / d.groupby("ym").총_승객수_경로.sum()
nd = d.groupby("ym").기준_날짜.nunique().rename("n_days")
M = M.join(nd); cv = (M.drop(columns="n_days").std() / M.drop(columns="n_days").mean()).rename("CV")
M.to_csv(OUT / "q1_d20_monthly.csv", encoding="utf-8-sig"); print(M.round(4).to_string()); print("CV", cv.round(4).to_dict())

fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(M.index, M["서울버스 포함"] * 100, color="#52514e", lw=1.5, ls="--", label="서울버스 포함 합계")
for c in ["버스만", "경기버스 포함(서울버스 포함)", "경기버스 포함(서울버스 없음)", "버스+지하철"]:
    if c in M: ax.plot(M.index, M[c] * 100, color=COL[c], lw=2, marker="o", ms=4, label=c)
ax.set_ylabel("경로 승객 중 비율 (%)"); ax.set_xlabel("연월 (2026)"); ax.set_ylim(0, None)
ax.legend(frameon=False, fontsize=8, loc="center right"); ax.set_title("D20 경로 승객 중 버스 관련 패턴 비율, 월별 (나머지 ≈86% = 지하철만)", fontsize=11, loc="left")
fig.tight_layout(); fig.savefig(OUT / "fig_q1_d20_monthly.png", dpi=150); plt.close(fig)

# 비교 1: 지하철 — D20 '지하철만'의 경로 비중 vs D17 우대권 비율 × D19 표본 경로 비중
cm = pd.read_csv(OUT / "q2_monthly_citywide.csv", dtype={"ym": str}).set_index("ym")
d19 = pd.read_csv(OUT / "q1_d19_sample_usertype.csv").set_index("사용자구분(BILL_USER)")
pref = d19.loc[["경로", "장애인", "국가유공자"]]; k19 = pref.passengers["경로"] / pref.passengers.sum()
r17 = cm.loc[[f"2025{m:02d}" for m in range(3, 11)], "ratio"].mean()       # D20과 같은 3~10월, 2025년
sub = T.loc["지하철만"]
# 비교 2: 버스 — D20 버스 패턴 경로 비중 vs D12 65세 이상 이동 비중
d12 = pd.read_csv(OUT / "d12_dep_dong_hour.csv", dtype={"dong7": str})
a = d12.groupby("ag").v.sum(); a1016 = d12[d12.hour.between(10, 16)].groupby("ag").v.sum()
bus_rows = d[d.n_bus > 0]
bus_board_eld = (bus_rows.n_bus * bus_rows.총_승객수_경로).sum(); bus_board_all = (bus_rows.n_bus * bus_rows.총_승객수).sum()
C = pd.Series({
    "D19_경로/(경로+장애인+유공자)_인원": k19, "D19_표본_우대3종_인원": pref.passengers.sum(), "D19_표본_전체행": int(d19.rows.sum()),
    "D17_우대권비율_2025_3~10월평균": r17, "D17×D19_경로비중_추정": r17 * k19,
    "D20_지하철만_경로/총": sub.경로_비중_총승객, "D20_지하철만_(경로+장애인)/총": (sub.총_승객수_경로 + sub.총_승객수_장애인) / sub.총_승객수,
    "D20_버스만_경로/총": T.loc["버스만", "경로_비중_총승객"], "D20_버스+지하철_경로/총": T.loc["버스+지하철", "경로_비중_총승객"],
    "D20_서울버스구간_경로비중(구간가중)": bus_board_eld / bus_board_all,
    "D20_서울버스구간_승차/일_전체": bus_board_all / d.기준_날짜.nunique(), "D20_서울버스구간_승차/일_경로": bus_board_eld / d.기준_날짜.nunique(),
    "D12_65+비중_전시간_상한": a["65p"] / a.sum(), "D12_65+비중_10~16시_상한": a1016["65p"] / a1016.sum(),
})
C.to_csv(OUT / "q1_d20_compare.csv", header=["value"], encoding="utf-8-sig"); print(C.round(4).to_string())

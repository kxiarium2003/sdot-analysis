"""s05 - D20(2026-03~10) 수단 조합별 일평균과 경로 비중, 월보 2026-03 버스·지하철·버스+지하철 행 대조."""
from pathlib import Path
import re
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
df = pd.read_csv(ROOT / "data/raw/D20_transit_pattern/서울시 대중교통 이용패턴 정보.csv", encoding="cp949", dtype=str)
df.columns = ["date", "pat", "n", "gen", "kid", "teen", "eld", "dis"]
for c in ["n", "gen", "kid", "teen", "eld", "dis"]:
    df[c] = pd.to_numeric(df[c]).fillna(0)
df["ym"] = df.date.str[:6]
df["modes"] = df.pat.map(lambda p: "+".join(sorted(set(re.findall(r"\[(.*?)\]", p)))))
df["legs_bus"] = df.pat.map(lambda p: len(re.findall(r"\[(?:버스|경기버스)\]", p)))


def rep_class(m):  # 월보 분류(2026-03 대조로 확인한 규칙)
    s = set(m.split("+"))
    if "지하철" not in s:
        return "버스"
    if "버스" in s:
        return "버스+지하철"
    return "지하철"  # 지하철만, 경기버스+지하철


df["rep_class"] = df.modes.map(rep_class)
days = df.groupby("ym").date.nunique()
a = df.groupby(["ym", "modes"])[["n", "eld"]].sum().reset_index()
a["days"] = a.ym.map(days)
a["n_per_day"] = a.n / a.days
a["eld_per_day"] = a.eld / a.days
a["eld_pct"] = 100 * a.eld / a.n
a.to_csv(OUT / "d20_by_modeset_2026.csv", index=False, encoding="utf-8-sig")
b = df.groupby(["ym", "rep_class"])[["n", "eld"]].sum().reset_index()
b["days"] = b.ym.map(days)
b["n_per_day"] = b.n / b.days
b["eld_per_day"] = b.eld / b.days
b["eld_pct"] = 100 * b.eld / b.n
# 버스 구간(승차) 가중: 버스 분류 통행의 버스 구간 수
bus = df[df.rep_class == "버스"].assign(nl=lambda x: x.n * x.legs_bus, el=lambda x: x.eld * x.legs_bus).groupby("ym")[["nl", "el"]].sum()
allbus = df.assign(nl=lambda x: x.n * x.legs_bus, el=lambda x: x.eld * x.legs_bus).groupby("ym")[["nl", "el"]].sum()
b = b.merge((100 * allbus.el / allbus.nl).rename("eld_pct_of_all_bus_legs").reset_index(), on="ym")
b = b.merge((allbus.nl / days).rename("all_bus_legs_per_day").reset_index(), on="ym")
rep = {("202603", "버스"): (2905554, 141593), ("202603", "지하철"): (5392442, 965121), ("202603", "버스+지하철"): (1164596, 209)}
b["report_n_per_day"] = [rep.get((y, c), (None, None))[0] for y, c in zip(b.ym, b.rep_class)]
b["report_eld_per_day"] = [rep.get((y, c), (None, None))[1] for y, c in zip(b.ym, b.rep_class)]
b.to_csv(OUT / "d20_vs_report_2026.csv", index=False, encoding="utf-8-sig")
print(b.round(3).to_string())

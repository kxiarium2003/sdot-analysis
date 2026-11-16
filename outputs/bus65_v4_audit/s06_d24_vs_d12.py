"""s06 - D24 SS 경로 비중(승차 정류장 → 행정동·자치구 합)이 D12 65+ 출발 비중(2025-08, 기존 eda_bus65 표)과 순위가 맞는지 점검.
D12 표: outputs/eda_bus65/d12_dep_dong_hour.csv (출발 행정동 x 시각, 65p/u65, 동 내 이동 포함/제외 구분)."""
from pathlib import Path
import pandas as pd
from scipy.stats import spearmanr

OUT = Path(__file__).resolve().parent
st = pd.read_csv(OUT / "table_d24_stop_share_202508.csv", dtype={"on_id": str, "dong7": str})
d12 = pd.read_csv(OUT.parent / "eda_bus65/d12_dep_dong_hour.csv", dtype={"dong7": str})
p = d12.pivot_table(index="dong7", columns="ag", values="v", aggfunc="sum")
p["d12_65p_share"] = 100 * p["65p"] / (p["65p"] + p["u65"])
p["gu5"] = p.index.str[:5]
dong = st.groupby("dong7")[["n_ss", "eld_ss"]].sum()
dong["d24_share"] = 100 * dong.eld_ss / dong.n_ss
m = dong.join(p, how="inner")
rows = []
for lab, mm in [("행정동 전체", m), ("행정동 경로 30건 이상", m[m.eld_ss >= 30]), ("행정동 경로 100건 이상", m[m.eld_ss >= 100])]:
    r = spearmanr(mm.d24_share, mm.d12_65p_share)
    rows.append(dict(unit=lab, n=len(mm), spearman=r.statistic, pvalue=r.pvalue))
g = m.groupby("gu5")[["n_ss", "eld_ss", "65p", "u65"]].sum()
r = spearmanr(g.eld_ss / g.n_ss, g["65p"] / (g["65p"] + g["u65"]))
rows.append(dict(unit="자치구 25", n=len(g), spearman=r.statistic, pvalue=r.pvalue))
pd.DataFrame(rows).to_csv(OUT / "d24_vs_d12_65p_rank_202508.csv", index=False, encoding="utf-8-sig")
m.reset_index().to_csv(OUT / "d24_vs_d12_65p_dong_202508.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(rows))
print("D12 65+ share dong range", m.d12_65p_share.describe().round(2).to_dict())

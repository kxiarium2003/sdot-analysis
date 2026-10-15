"""RQ1 후속 4단계: 행정동 생활이동(KT) 14시 순유입 vs 생활인구(14시 − 03시) 변화.

자료: 서울 열린데이터광장 '서울 생활이동' 행정동 단위(infSeq=2), 2025-06·07·08·09 월 파일(zip, 도착시각별 CSV, cp949).
      https://data.seoul.go.kr/dataVisual/seoul/seoulLivingMigration.do  (로그인 없이 POST 다운로드)
      원천: KT LTE/5G 시그널(매뉴얼 v3.1 p.9) — 생활인구와 같은 KT 원천이라 독립 검증이 아니다.

[사전등록 — 결과 보기 전에 고정] (작성 2026-10-12)
  기간      2025 여름(6–9월). 생활이동은 월 × 요일 합을 모두 더한 값, 생활인구는 2025 여름 하루 평균. (순위 비교라 척도 무관)
  14시 순유입(주 지표)  행정동 d: Σ(도착 = d, 도착시간 = 14) − Σ(출발 = d, 도착시간 = 14). 같은 동 안 이동은 상쇄.
                       서울 밖 출발·도착 이동 포함. '*'(3명 미만)는 0으로 둔다(하한).
  누적 순유입(참고)      같은 정의를 도착시간 03–13시로 더한 값 (03시 → 14시 인구 변화에 대응하는 흐름). 판정 대상 아님, 참고로만.
  생활인구 변화         2025 여름 하루 평균 (14시 − 03시), 행정동(2016 코드 앞 7자리, 424개), 연령 보정 = common.load_livingpop.
  비교                 스피어만 순위 상관, 상위 10% 일치(42개 동).
  판정                 ρ ≥ 0.8 "비슷함", 0.6 ≤ ρ < 0.8 "부분적으로 비슷함", ρ < 0.6 "다름".
  연령                 0–14세 = 나이 코드 00(0–9세)+10(10–14세), 65세 이상 = 65·70·75·80(80세 이상). 전 연령 = 모든 코드.
실행: python -m rq1_followup.step4_mobility_vs_livingpop [zip 폴더]
출력: rq1_followup/out/step4/
"""
import sys, zipfile, json, time
from pathlib import Path
import numpy as np, pandas as pd
import rq1_modules.common as c

OUT = c.ROOT / "rq1_followup/out/step4"; OUT.mkdir(parents=True, exist_ok=True)
ZDIR = Path(sys.argv[1]) if len(sys.argv) > 1 else c.ROOT / "rq1_followup/data/lm"
MONTHS = ["202506", "202507", "202508", "202509"]
AGEMAP = {"a0_14": {"00", "10"}, "a65p": {"65", "70", "75", "80"}}
HRS = list(range(3, 15))
JUDGE = lambda r: "비슷함" if r >= .8 else ("부분적으로 비슷함" if r >= .6 else "다름")


def flows():
    rows = []
    for m in MONTHS:
        z = zipfile.ZipFile(ZDIR / f"생활이동_행정동_{m}.zip")
        for n in z.namelist():
            h = int(n.rsplit("_", 1)[1][:2])
            if h not in HRS: continue
            d = pd.read_csv(z.open(n), encoding="cp949", dtype=str, usecols=["출발 행정동 코드", "도착 행정동 코드", "나이", "이동인구(합)"])
            d["v"] = pd.to_numeric(d["이동인구(합)"], errors="coerce"); star = d.v.isna().mean(); d["v"] = d.v.fillna(0)
            d = d[d["출발 행정동 코드"].str.startswith("11") | d["도착 행정동 코드"].str.startswith("11")]
            for a, codes in [("all", None), *AGEMAP.items()]:
                s = d if codes is None else d[d["나이"].isin(codes)]
                inn = s.groupby("도착 행정동 코드").v.sum(); out = s.groupby("출발 행정동 코드").v.sum()
                net = inn.sub(out, fill_value=0)
                rows.append(pd.DataFrame({"dong7": net.index, "month": m, "hour": h, "age": a, "net": net.values, "star_share": star}))
            print(f"  {m} {h:02d}시", flush=True)
    F = pd.concat(rows); F = F[F.dong7.str.startswith("11")]
    return F


def main():
    t0 = time.time(); names = c.dong_names()
    F = flows(); F.to_parquet(OUT / "net_inflow_by_dong_month_hour.parquet", index=False)
    lp = c.load_livingpop(); lp = lp[(lp.season == "summer") & (lp.year == 2025)].copy()
    for a in ("all", "a0_14", "a65p"): lp[a] = lp[a] / lp.n_days
    lp["dong7"] = lp.tract16.str[:7]; P = lp.groupby(["dong7", "hour"])[["all", "a0_14", "a65p"]].sum()
    res = {}; tabs = []
    for a in ("all", "a0_14", "a65p"):
        dpop = (P.xs(14, level="hour")[a] - P.xs(3, level="hour")[a]).rename("dpop")
        g = F[F.age == a].groupby(["dong7", "hour"]).net.sum().unstack("hour").reindex(columns=HRS).fillna(0)
        T = pd.DataFrame({"net14": g[14], "net03_13": g[list(range(3, 14))].sum(1)}).join(dpop, how="inner")
        T["name"] = [names.get(u, u) for u in T.index]; tabs.append(T.assign(age=a))
        r = {}
        for k in ("net14", "net03_13"):
            rho = c.rho(T[k], T.dpop); r[k] = dict(rho=rho, top10=c.top_overlap(T[k], T.dpop, .10), judge=JUDGE(rho) if k == "net14" else "참고(판정 대상 아님)")
        r["n_dong"] = len(T); res[a] = r
        print(a, json.dumps(r, ensure_ascii=False))
    pd.concat(tabs).to_csv(OUT / "dong_net_inflow_vs_dpop.csv", encoding="utf-8-sig")
    res["star_share_rows"] = float(F.star_share.mean())
    json.dump(res, open(OUT / "step4_summary.json", "w"), ensure_ascii=False, indent=1, default=float)
    print(f"완료 {time.time() - t0:.0f}s → {OUT}")


if __name__ == "__main__":
    main()

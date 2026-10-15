"""RQ1 모듈 전체 실행: S1 → H1 → H2 → H3 → H4 → H5 → S4 → S5 → Q6. 결과는 rq1_modules/out/*.json 에 저장된다.

실행: .venv/bin/python -m rq1_modules.run_rq1 [--scale=tract|dong|gu|all] [--threshold] [--only=H1,H2]
  --threshold  H5 의 30·33°C 초과 노출까지 계산 (매시간 기온을 다시 보간, 약 3분 추가)
  --only       일부 모듈만 실행
소요 시간: 약 1분 (--threshold 포함 약 4분)
"""
import sys, time
from rq1_modules import S1_basics, H1_how_much, H2_where, H3_when, H4_who, H5_absolute, S4_robustness, S5_foreigner, Q6_census_match
from rq1_modules.common import parse_scales

MODULES = {"S1": S1_basics, "H1": H1_how_much, "H2": H2_where, "H3": H3_when, "H4": H4_who, "H5": H5_absolute,
           "S4": S4_robustness, "S5": S5_foreigner, "Q6": Q6_census_match}

if __name__ == "__main__":
    scales = parse_scales(sys.argv)
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), list(MODULES))
    t0 = time.time()
    for k in only:
        t = time.time(); print(f"\n################ {k}: {MODULES[k].__doc__.splitlines()[0]}")
        if k == "H5": MODULES[k].run(scales, with_threshold="--threshold" in sys.argv)
        else: MODULES[k].run(scales)
        print(f"({k} {time.time() - t:.0f}초)")
    print(f"\n전체 {time.time() - t0:.0f}초. 결과: rq1_modules/out/")

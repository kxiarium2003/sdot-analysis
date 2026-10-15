"""공유 묶음 만들기: rq1_modules 코드 + 모듈이 읽는 입력 파일을 원래 경로 구조 그대로 zip 으로 묶는다.
받는 사람은 압축을 풀고 그 폴더에서 바로 `python -m rq1_modules.run_rq1` 을 실행할 수 있다.

실행: .venv/bin/python -m rq1_modules.make_bundle [--no-s4]   →  RQ1_모듈_공유.zip (약 300MB)
  --no-s4  강건성 변형(phase3/gap_2y_by_tract_*.parquet, 약 64MB)을 빼고 묶는다(S4 는 기본 설정만 계산됨)
"""
import sys, zipfile, glob
from pathlib import Path
from rq1_modules.common import ROOT

INPUTS = [
    "phase2/anomaly_by_zone_2y_merged.parquet",                 # ΔT 지도 (모든 모듈)
    "merged_data/D5_livingpop/livingpop_agg_2024_2025_native.parquet", "merged_data/D5_livingpop/age_scale.csv",
    "merged_data/D5_livingpop/foreigner_agg_2024_2025.parquet",  # S5
    "merged_data/D6_census/census2024_age3_tract16.parquet",
    "merged_data/covariates/zone_ses.parquet",                  # H4 SES
    "merged_data/D9_boundary/bnd_oa_11_2016_4Q/*",              # 집계구 경계 (동 이름 결합, H5 임계)
    "data2/D9_zone_boundary/sgis_api_2025/2016/emd_*.geojson",  # 행정동 이름
    "phase3/absolute_temp_tract.parquet",                       # H5
    "merged_data/D2_aws/awsh_2024_2025.parquet", "merged_data/D2_aws/stations_kma.csv",   # H5 --threshold
    "phase1/variogram_monthly_2y_merged.csv", "phase2/covariates_tract16_buf250.parquet",
    "phase3/threshold_by_tract_2y_merged.parquet",              # S4 임계
    "phase3/gap_2y_by_tract*.parquet",                          # S4 강건성 변형
    "requirements.txt",
]

if __name__ == "__main__":
    out = ROOT / "RQ1_모듈_공유.zip"; n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "rq1_modules").glob("*.py")) + [ROOT / "rq1_modules/README.md"]:
            z.write(f, f.relative_to(ROOT)); n += 1
        for pat in INPUTS:
            if "--no-s4" in sys.argv and "gap_2y_by_tract" in pat: continue
            fs = glob.glob(str(ROOT / pat))
            if not fs: print("없음:", pat)
            for f in fs: z.write(f, Path(f).relative_to(ROOT)); n += 1
    print(f"{out.name}: 파일 {n}개, {out.stat().st_size / 1e6:.0f} MB")

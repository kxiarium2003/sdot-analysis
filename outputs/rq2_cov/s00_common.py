"""s00_common.py - rq2_cov 공통 경로. 환경변수 RQ2_SCRATCH 필요. 큰 파일은 스크래치에서만 쓴다.

D7·D14·D21 처리 규칙은 outputs/est_v3의 s01·s07·s08과 같다. est_v3 스크립트는 그 폴더의 요약표를 덮어쓰므로 실행하지 않고 로직만 옮겼다.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(os.environ["RQ2_SCRATCH"])
OUT = ROOT / "outputs/rq2_cov"
EST3 = ROOT / "outputs/est_v3"
RAW = ROOT / "data/raw"
D6 = RAW / "D6_SGIS_stats"
D9_2016_DONG = RAW / "D9_zone_boundary/seoul_census_oa_boundary_2016/행정구역.shp"
D9_2016_OA = RAW / "D9_zone_boundary/seoul_census_oa_boundary_2016/집계구.shp"
D9_2025 = RAW / "D9_zone_boundary/bnd_oa_11_2025_2Q/bnd_oa_11_2025_2Q.shp"
D9_2024 = RAW / "D9_zone_boundary/bnd_oa_11_2024_2Q/bnd_oa_11_2024_2Q.shp"
D21_DIR = RAW / "D21_bus_stop_location"
COOL = RAW / "D7_cooling_shelter/02. 무더위쉼터 목록(20250916 기준).xlsx"
R = 300
GU_NAMES = dict(zip([f"11{i:02d}0" for i in range(1, 26)],
                    "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split()))

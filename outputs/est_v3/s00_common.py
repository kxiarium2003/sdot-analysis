"""s00_common.py - est_v3 공통 경로·상수.

환경변수 EST_V3_SCRATCH 필요. 원자료·중간 산출물은 전부 스크래치에 두고, 이 폴더에는 요약표·그림·보고서만 둔다.
규칙(est_v2와 같음): D21 판본, ARS 01~25, 가상정류장 제외, 09642·05229 좌표 덮어쓰기, 마스킹 분모 0/3, 출발시 변환 3시간에서 자름.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(os.environ["EST_V3_SCRATCH"])
OUT = ROOT / "outputs/est_v3"
RAW_LOCAL = ROOT / "data/raw"
DRIVE = "googledrive:sdot-analysis"
D21_DIR = RAW_LOCAL / "D21_bus_stop_location"
D21_VINTAGE = {"2024": "서울시버스정류소위치정보(20240903).xlsx", "2025": "서울시버스정류소위치정보(20250801).xlsx"}
D21_OVERRIDE = {"09642": "서울시버스정류소위치정보(20251117).xlsx", "05229": "서울시버스정류소위치정보(20260902).xlsx"}
SEOUL_ARS = {f"{i:02d}" for i in range(1, 26)}
DONG_SHP = RAW_LOCAL / "D9_zone_boundary/seoul_census_oa_boundary_2016/행정구역.shp"
WEEKDAY_KO = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
GU_NAMES = dict(zip([f"11{i:02d}0" for i in range(1, 26)],
                    "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split()))
# 사용자 지정 대체일. 2024-08-20은 D25가 있지만 결측일과 같은 방식으로 대체한다.
IMPUTED_DAYS = {"202408": ["20240820", "20240821"], "202507": ["20250701", "20250702"]}
SURVEY = {"bus": 23.4, "subway": 24.2, "walk": 38.1}  # 2024 서울시 노인실태조사(서울시복지재단 2024-26) p.39


def d25_zip(ym):
    if ym == "202508":
        return RAW_LOCAL / "D25_stop_mode_od/kscc_dx_ra_od_202508.zip"
    return SCRATCH / f"raw/d25/kscc_dx_ra_od_{ym}.zip"


def d16_csv(ym):
    return RAW_LOCAL / f"D16_bus_hourly/{ym[:4]}년_버스노선별_정류장별_시간대별_승하차_인원_정보({ym[4:]}월).csv"


def d15_csv(ym):
    return RAW_LOCAL / f"D15_bus_daily/BUS_STATION_BOARDING_MONTH_{ym}.csv"


def duck(mem="8GB", threads=4):
    import duckdb
    tmp = SCRATCH / "duck_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{mem}'; SET threads={threads}; SET temp_directory='{tmp}'; SET preserve_insertion_order=false;")
    return con

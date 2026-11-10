"""s00_common.py - est_v2 공통 경로·상수.

실행 전 환경변수 EST_V2_SCRATCH 를 지정한다(원자료 사본과 중간 산출물 위치).
원자료 위치(모두 읽기만):
  <SCRATCH>/raw/d12/YYYYMM.parquet          D12 (Drive interim/seoul_living_migration/seoul_living_migration_admdong)
  <SCRATCH>/raw/d5/YYYYMM.parquet           D5 내국인 (Drive interim/seoul_living_population/native)
  <SCRATCH>/raw/d25/*.zip                   D25 3개월 (2025-08은 data/raw/D25_stop_mode_od)
  <SCRATCH>/raw/d26, raw/d27                CSV만 (Drive data1/D26_*, D27_*)
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(os.environ["EST_V2_SCRATCH"])
OUT = ROOT / "outputs/est_v2"
RAW_LOCAL = ROOT / "data/raw"
MONTHS = ["202407", "202408", "202507", "202508"]
D21_DIR = RAW_LOCAL / "D21_bus_stop_location"
D21_VINTAGE = {"2024": "서울시버스정류소위치정보(20240903).xlsx", "2025": "서울시버스정류소위치정보(20250801).xlsx"}
D21_OVERRIDE = {"09642": "서울시버스정류소위치정보(20251117).xlsx", "05229": "서울시버스정류소위치정보(20260902).xlsx"}
SEOUL_ARS = {f"{i:02d}" for i in range(1, 26)}
D25_MISSING = ["20240821", "20250701", "20250702"]
HOLIDAYS = ["20240815", "20250815"]
OA_SHP = RAW_LOCAL / "D9_zone_boundary/seoul_census_oa_boundary_2016/집계구.shp"
DONG_SHP = RAW_LOCAL / "D9_zone_boundary/seoul_census_oa_boundary_2016/행정구역.shp"
OA2025_DIR = RAW_LOCAL / "D9_zone_boundary/bnd_oa_11_2025_2Q"
D22_JSON = RAW_LOCAL / "D22_station_master/subwayStationMaster_000001_000784.json"
WEEKDAY_KO = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
GU_NAMES = dict(zip([f"11{i:02d}0" for i in range(1, 26)],
                    "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split()))


def d25_zip(ym):
    if ym == "202508":
        return RAW_LOCAL / "D25_stop_mode_od/kscc_dx_ra_od_202508.zip"
    return SCRATCH / f"raw/d25/kscc_dx_ra_od_{ym}.zip"


def d16_csv(ym):
    return RAW_LOCAL / f"D16_bus_hourly/{ym[:4]}년_버스노선별_정류장별_시간대별_승하차_인원_정보({ym[4:]}월).csv"


def d15_csv(ym):
    return RAW_LOCAL / f"D15_bus_daily/BUS_STATION_BOARDING_MONTH_{ym}.csv"


def duck(mem="5GB", threads=4):
    import duckdb
    tmp = SCRATCH / "duck_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{mem}'; SET threads={threads}; SET temp_directory='{tmp}'; SET preserve_insertion_order=false;")
    return con

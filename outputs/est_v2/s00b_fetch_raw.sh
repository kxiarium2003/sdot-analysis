#!/usr/bin/env zsh
# s00b_fetch_raw.sh - est_v2 재실행에 필요한 Drive 원자료를 스크래치로 내려받는다.
# 사용: EST_V2_SCRATCH=<경로> zsh s00b_fetch_raw.sh
# D26 폴더의 .xlsx 2개(구글 시트 사본)는 받지 않는다. 포털 2025 D26 파일은 Drive에 없다.
# 실행 순서: s00b → s01 → s02 → s03 → s03b → s04 → s05 → s06 → s07 → s08 → s09(station_month,station_hour) → s09(cell) → s10
set -e
SC=${EST_V2_SCRATCH:?EST_V2_SCRATCH 필요}
RM=googledrive:sdot-analysis
mkdir -p $SC/raw/{d12,d5,d25,d26,d27}
rclone copy $RM/data1/D26_subway_elderly_hourly $SC/raw/d26 --include '*.csv'
rclone copy $RM/data1/D27_subway_passenger_type_hourly $SC/raw/d27 --include '*.csv'
rclone copy $RM/data1/D25_stop_mode_od $SC/raw/d25 --include 'kscc_dx_ra_od_202407.zip' --include 'kscc_dx_ra_od_202408.zip' --include 'kscc_dx_ra_od_202507.zip'
rclone copy $RM/interim/seoul_living_migration/seoul_living_migration_admdong $SC/raw/d12 --include '20240[78].parquet' --include '20250[78].parquet'
rclone copy $RM/interim/seoul_living_population/native $SC/raw/d5 --include '20240[78].parquet' --include '20250[78].parquet'

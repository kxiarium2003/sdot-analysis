"""
script24-collect-kma-asos.py - KMA API Hub ASOS 종로(108) 시간자료 수집 (D3, 홀드아웃 검증용)

기상자료개방포털 API 허브(apihub.kma.go.kr)의 ASOS 시간자료 조회 API
(kma_sfctm3.php)를 이용해 종로(지점번호 108) 시간별 기온/습도/일조/일사를
S-DoT 마스터 데이터 수집기간(2020-04 ~ 2026-08)과 동일한 범위로 수집한다.

주의사항 (실측으로 확인한 API 제약):
1. 한 번의 요청으로 최대 약 31일(744시간)치까지만 반환되며, 그보다 긴 기간을
   요청하면 에러 없이 "요청 구간의 뒷부분(최신 쪽) 31일치"만 조용히 잘려서
   돌아온다. 따라서 반드시 월 단위(달력월, 최대 31일)로 나눠서 요청해야 하며,
   월별로 기대 행수(그 달의 일수*24)와 실제 행수를 대조하는 감사를 반드시 남긴다.
2. 결측값 표기: HM(습도)/SS(일조)/SI(일사)는 물리적으로 음수가 될 수 없으므로
   -9/-9.0/-9.00은 결측으로 명확히 판정 가능하다. 반면 TA(기온)는 겨울철에
   실제로 -9.0도 근방 값이 나올 수 있어 결측 신호(-9.0)와 실측값이 원본 텍스트
   상에서 구분되지 않는다 (KMA 원본 API의 알려진 한계). 이 스크립트는 TA를
   임의로 NaN 처리하지 않고 `ta_at_sentinel` 플래그만 남겨 판단을 다음 단계로
   미룬다 (S-DoT 파이프라인과 동일하게 "버리지 않고 표시만" 원칙 적용).
"""
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env')

API_KEY = os.environ.get('KMA_API_KEY')
if not API_KEY:
    print("❌ [오류] .env에 KMA_API_KEY가 설정되어 있지 않습니다.")
    sys.exit(1)

STN_ID = 108  # 종로
STN_NAME = 'jongno'
BASE_URL = 'https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php'

# S-DoT 마스터 데이터(data/processed/sdot_master_2020_2026_v2.parquet) 실측 범위:
# 2020-04-01 01:00 ~ 2026-08-30 23:07 → 동일 범위로 맞추되 달력월 단위로 청킹
START_YM = (2020, 4)
END_YM = (2026, 8)

raw_dir = PROJECT_ROOT / 'data' / 'raw' / 'D3_KMA_ASOS_108'
interim_dir = PROJECT_ROOT / 'data' / 'interim'
raw_dir.mkdir(parents=True, exist_ok=True)
interim_dir.mkdir(parents=True, exist_ok=True)
output_file = interim_dir / 'kma_asos_108.parquet'
audit_log_file = PROJECT_ROOT / 'docs' / 'kma-asos-collection-audit.csv'

COLUMNS = [
    'TM', 'STN', 'WD', 'WS', 'GST_WD', 'GST_WS', 'GST_TM', 'PA', 'PS', 'PT',
    'PR', 'TA', 'TD', 'HM', 'PV', 'RN', 'RN_DAY', 'RN_JUN', 'RN_INT',
    'SD_HR3', 'SD_DAY', 'SD_TOT', 'WC', 'WP', 'WW', 'CA_TOT', 'CA_MID',
    'CH_MIN', 'CT', 'CT_TOP', 'CT_MID', 'CT_LOW', 'VS', 'SS', 'SI', 'ST_GD',
    'TS', 'TE_005', 'TE_01', 'TE_02', 'TE_03', 'ST_SEA', 'WH', 'BF', 'IR', 'IX',
]
KEEP_COLUMNS = ['TM', 'STN', 'TA', 'HM', 'SS', 'SI']


def month_range(start_ym, end_ym):
    y, m = start_ym
    while (y, m) <= end_ym:
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def days_in_month(y, m):
    if m == 12:
        next_month = date(y + 1, 1, 1)
    else:
        next_month = date(y, m + 1, 1)
    return (next_month - date(y, m, 1)).days


def fetch_month(y, m, max_retries=3):
    tm1 = f"{y:04d}{m:02d}010000"
    last_day = days_in_month(y, m)
    tm2 = f"{y:04d}{m:02d}{last_day:02d}2300"
    params = {'tm1': tm1, 'tm2': tm2, 'stn': STN_ID, 'help': 0, 'authKey': API_KEY}

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"  ⚠️  요청 실패(시도 {attempt}/{max_retries}): {e}")
            time.sleep(3 * attempt)
    return None


def parse_response(text):
    if text is None:
        return None
    if '"result"' in text and '"status"' in text:
        # API 자체 에러 응답(JSON) - 활용신청 필요/인증 실패 등
        print(f"  ❌ [API 오류 응답] {text.strip()[:200]}")
        return None
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        tokens = line.split()
        if len(tokens) != len(COLUMNS):
            print(f"  ⚠️  컬럼 수 불일치(기대 {len(COLUMNS)}, 실제 {len(tokens)}): {line[:80]}")
            continue
        rows.append(tokens)
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame(rows, columns=COLUMNS)


def main():
    print("🚀 [ KMA ASOS 108(종로) 시간자료 수집 시작 ]")
    print(f"📅 수집 범위: {START_YM[0]}-{START_YM[1]:02d} ~ {END_YM[0]}-{END_YM[1]:02d} (달력월 단위)\n")

    all_months = []
    audit_rows = []

    for y, m in month_range(START_YM, END_YM):
        ym = f"{y:04d}{m:02d}"
        raw_file = raw_dir / f"asos_108_{ym}.txt"
        expected_rows = days_in_month(y, m) * 24

        if raw_file.exists():
            text = raw_file.read_text(encoding='utf-8', errors='replace')
            print(f"[{ym}] 캐시된 원본 파일 사용")
        else:
            print(f"[{ym}] API 요청 중...")
            text = fetch_month(y, m)
            if text is not None:
                raw_file.write_text(text, encoding='utf-8')
            time.sleep(0.3)  # 과도한 연속 요청 방지

        df_month = parse_response(text)
        actual_rows = 0 if df_month is None else len(df_month)
        status = 'ok'
        if df_month is None:
            status = 'fetch_failed'
        elif actual_rows != expected_rows:
            status = 'row_count_mismatch'

        audit_rows.append({
            'year_month': ym, 'expected_rows': expected_rows,
            'actual_rows': actual_rows, 'status': status,
        })
        print(f"  → 기대 {expected_rows}행 / 실제 {actual_rows}행 [{status}]")

        if df_month is not None and not df_month.empty:
            all_months.append(df_month[KEEP_COLUMNS])

    if not all_months:
        print("\n❌ [오류] 수집된 데이터가 없습니다.")
        sys.exit(1)

    df = pd.concat(all_months, ignore_index=True)
    df['measure_time'] = pd.to_datetime(df['TM'], format='%Y%m%d%H%M')
    df['stn'] = df['STN'].astype(int)
    for col in ['TA', 'HM', 'SS', 'SI']:
        df[col.lower()] = pd.to_numeric(df[col], errors='coerce')

    # HM/SS/SI: 음수 불가능 → sentinel(-9/-9.0/-9.00)은 결측으로 확정 처리
    for col in ['hm', 'ss', 'si']:
        df.loc[df[col] <= -9, col] = pd.NA

    # TA: 겨울철 실측값과 결측 sentinel(-9.0)이 원본상 구분 불가 → 플래그만 남기고 보존
    df['ta_at_sentinel'] = df['ta'] == -9.0

    df = df[['measure_time', 'stn', 'ta', 'ta_at_sentinel', 'hm', 'ss', 'si']]
    df = df.sort_values('measure_time').reset_index(drop=True)

    df.to_parquet(output_file, index=False)
    audit_df = pd.DataFrame(audit_rows)
    audit_df.to_csv(audit_log_file, index=False, encoding='utf-8-sig')

    print(f"\n✅ [완료] {len(df):,}행 저장 → {output_file}")
    print(f"📋 감사 로그 저장 → {audit_log_file}")
    mismatch = audit_df[audit_df['status'] != 'ok']
    if not mismatch.empty:
        print(f"⚠️  행수 불일치/실패 {len(mismatch)}개월 있음 (감사 로그 참조):")
        print(mismatch.to_string(index=False))
    ta_sentinel_count = df['ta_at_sentinel'].sum()
    if ta_sentinel_count:
        print(f"⚠️  TA=-9.0(결측 의심) {ta_sentinel_count}건 — ta_at_sentinel 플래그로 표시, 삭제하지 않음")


if __name__ == '__main__':
    main()

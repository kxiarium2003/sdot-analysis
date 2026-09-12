"""
script25-collect-kma-aws-seoul.py - KMA API Hub AWS(방재기상관측) 서울 지역 시간자료 수집
(D2, 참조장/크리깅 구축용 - 홀드아웃인 ASOS 108(종로)와 달리 여러 지점)

기상자료개방포털 API 허브(apihub.kma.go.kr)의 AWS 시간자료 조회 API(awsh.php)로
서울 지역 AWS 지점들의 기온/습도 등을 S-DoT 마스터 데이터 수집기간(2020-04~2026-08)과
동일한 범위로 수집한다.

주의사항 (실측으로 확인한 API 특성 - script24/ASOS와 다름):
1. awsh.php는 ASOS(kma_sfctm3.php)와 달리 기간(tm1~tm2) 조회를 지원하지 않는다.
   tm1/tm2를 넣어도 조용히 무시되고 "최근 데이터"가 반환된다 (에러 없음, 주의).
   대신 단일 시각(tm) 스냅샷 조회만 되며, 그 한 번의 호출로 전국 모든 지점이
   동시에 반환된다. 따라서 지점별이 아니라 "시간별로 1회씩" 호출해서 전국
   응답을 받은 뒤 서울 지점만 걸러내는 방식을 쓴다 (지점 수만큼 곱해서 호출할
   필요 없음).
2. AWS는 일조(SS)/일사(SI) 항목이 아예 없다 (TA/WD/WS/RN_DAY/RN_HR1/HM/PA/PS만
   제공). 일조·일사는 script24로 수집한 ASOS 108(종로) 데이터에만 있다.
3. 결측값 표기는 모든 필드에서 -99.0으로 통일되어 있어(실측 확인: 겨울철 실제
   기온 -9.x와 결측 sentinel -99.0이 텍스트 상 명확히 구분됨) ASOS의 TA 모호성
   문제가 없다. -99 이하 값은 전부 결측으로 확정 처리한다.
4. 동시 요청 처리량 실측: 동시성 10~15에서는 안정적(초당 20~45건), 20 이상에서는
   간헐적으로 ReadTimeout이 급증하는 구간이 있었다(서버 측 순간 제한으로 추정,
   재현 불안정). 안전하게 동시성 10 + 재시도(최대 3회, 지수 backoff)로 운용한다.
5. 전체 기간(약 5.4년, 시간당 1회 호출)은 약 5.6만 회 호출이 필요해 러닝타임이
   수십 분 걸린다. 월 단위로 끊어서 처리하고 월별 parquet + .done 마커를 남겨
   중단 시 이어서 재개할 수 있게 한다 (S-DoT 파이프라인과 동일한 재개 전략).
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
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

BASE_URL = 'https://apihub.kma.go.kr/api/typ01/url/awsh.php'
STN_INF_URL = 'https://apihub.kma.go.kr/api/typ01/url/stn_inf.php'
MAX_WORKERS = 10
RETRIES = 3

# S-DoT 마스터/ASOS 수집과 동일 범위
START_YM = (2020, 4)
END_YM = (2026, 8)

raw_dir = PROJECT_ROOT / 'data' / 'raw' / 'KMA_AWS_seoul'
interim_dir = PROJECT_ROOT / 'data' / 'interim' / 'kma_aws_seoul'
metadata_dir = PROJECT_ROOT / 'metadata'
raw_dir.mkdir(parents=True, exist_ok=True)
interim_dir.mkdir(parents=True, exist_ok=True)

output_file = PROJECT_ROOT / 'data' / 'interim' / 'kma_aws_seoul.parquet'
audit_log_file = PROJECT_ROOT / 'docs' / 'kma-aws-collection-audit.csv'
station_file = metadata_dir / 'kma_aws_stations_seoul.csv'

OBS_COLUMNS = ['TM', 'STN', 'TA', 'WD', 'WS', 'RN_DAY', 'RN_HR1', 'HM', 'PA', 'PS']
NUMERIC_COLS = ['ta', 'wd', 'ws', 'rn_day', 'rn_hr1', 'hm', 'pa', 'ps']


def month_range(start_ym, end_ym):
    y, m = start_ym
    while (y, m) <= end_ym:
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def days_in_month(y, m):
    next_month = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return (next_month - date(y, m, 1)).days


def load_seoul_stations():
    if station_file.exists():
        df = pd.read_csv(station_file, dtype={'stn_id': int})
        print(f"📍 서울 지점 목록 캐시 사용: {len(df)}개")
        return df

    print("📍 지점정보(stn_inf.php) 조회 중...")
    resp = requests.get(STN_INF_URL, params={
        'inf': 'AWS', 'stn': '', 'tm': '202211300900', 'help': 1, 'authKey': API_KEY,
    }, timeout=30)
    resp.raise_for_status()
    text = resp.content.decode('euc-kr', errors='replace')

    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        tokens = line.split()
        if len(tokens) < 14 or '----' not in tokens:
            continue
        # STN_KO(지점명)가 "송파 *"처럼 공백을 포함하는 경우가 있어 고정 위치가
        # 아니라 STN_EN 자리의 "----" 토큰을 앵커로 삼아 앞뒤를 가변 파싱한다.
        idx = tokens.index('----')
        stn_id = int(tokens[0])
        stn_ko = ' '.join(tokens[8:idx])
        law_addr = ' '.join(tokens[idx + 4:])
        rows.append({'stn_id': stn_id, 'lon': float(tokens[1]), 'lat': float(tokens[2]),
                     'stn_ko': stn_ko, 'law_addr': law_addr})
    df_all = pd.DataFrame(rows)
    df_seoul = df_all[df_all['law_addr'].str.startswith('서울특별시')].reset_index(drop=True)
    df_seoul.to_csv(station_file, index=False, encoding='utf-8-sig')
    print(f"📍 서울 지점 {len(df_seoul)}개 확인 → {station_file}")
    return df_seoul


class DailyLimitExceeded(Exception):
    pass


def fetch_hour(tm_str):
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(BASE_URL, params={'tm': tm_str, 'help': 0, 'authKey': API_KEY}, timeout=20)
            if resp.status_code == 403 and '일일 최대 호출' in resp.text:
                # 계정 단위 일일(또는 24시간 롤링) 호출 한도 초과 - 재시도해도
                # 즉시 같은 응답만 돌아오므로 재시도하지 않고 곧바로 상위로 전파해
                # 전체 수집을 중단시킨다 (2026-09-08 사고 이후 추가한 안전장치).
                raise DailyLimitExceeded(resp.text.strip())
            resp.raise_for_status()
            return tm_str, resp.content.decode('euc-kr', errors='replace')
        except DailyLimitExceeded:
            raise
        except requests.RequestException:
            if attempt == RETRIES:
                return tm_str, None
            time.sleep(1.5 * attempt)
    return tm_str, None


def parse_hour_text(text, seoul_ids):
    if text is None or ('"result"' in text and '"status"' in text):
        return []
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        tokens = line.split()
        if len(tokens) != len(OBS_COLUMNS):
            continue
        stn_id = int(tokens[1])
        if stn_id in seoul_ids:
            rows.append(tokens)
    return rows


def process_month(y, m, seoul_ids, n_stations):
    ym = f"{y:04d}{m:02d}"
    done_marker = interim_dir / f"{ym}.done"
    month_parquet = interim_dir / f"{ym}.parquet"

    if done_marker.exists() and month_parquet.exists():
        df = pd.read_parquet(month_parquet)
        print(f"[{ym}] 캐시 사용 ({len(df)}행)")
        return df, None

    last_day = days_in_month(y, m)
    hours = []
    d = date(y, m, 1)
    end_d = date(y, m, last_day)
    while d <= end_d:
        for h in range(24):
            hours.append(f"{d.strftime('%Y%m%d')}{h:02d}00")
        d += timedelta(days=1)

    expected_rows = len(hours) * n_stations
    all_rows = []
    failed_hours = []
    raw_file = raw_dir / f"aws_seoul_{ym}_raw.txt"

    with raw_file.open('w', encoding='utf-8') as rf, ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_hour, tm): tm for tm in hours}
        try:
            for fut in as_completed(futures):
                tm_str, text = fut.result()
                if text is None:
                    failed_hours.append(tm_str)
                    continue
                rf.write(f"### tm={tm_str} ###\n{text}\n")
                all_rows.extend(parse_hour_text(text, seoul_ids))
        except DailyLimitExceeded as e:
            for f in futures:
                f.cancel()
            print(f"\n🛑 [일일 호출 한도 초과 감지] {ym} 처리 중 발생 - 재시도 무의미하므로 "
                  f"즉시 전체 수집 중단. 이 달({ym})은 done 마커를 남기지 않아 다음 실행 시 "
                  f"자동 재수집됩니다. ({e})")
            raise

    if not all_rows:
        df_month = pd.DataFrame(columns=[c.lower() for c in OBS_COLUMNS])
    else:
        df_month = pd.DataFrame(all_rows, columns=OBS_COLUMNS)
        df_month.columns = [c.lower() for c in df_month.columns]

    for col in NUMERIC_COLS:
        if col in df_month.columns:
            df_month[col] = pd.to_numeric(df_month[col], errors='coerce')
            df_month.loc[df_month[col] <= -99, col] = pd.NA

    if 'tm' in df_month.columns and not df_month.empty:
        df_month['measure_time'] = pd.to_datetime(df_month['tm'], format='%Y%m%d%H%M')
        df_month = df_month.drop(columns=['tm']).rename(columns={'stn': 'stn_id'})

    df_month.to_parquet(month_parquet, index=False)

    actual_rows = len(df_month)
    completeness = actual_rows / expected_rows if expected_rows else 0.0
    status = 'ok' if actual_rows == expected_rows and not failed_hours else (
        'fetch_failed' if failed_hours else 'row_count_mismatch')

    # 완성도가 낮은 달은 .done을 찍지 않는다 - API 서버 장애 등으로 그 달이
    # 통째로(또는 대부분) 비어도 "완료"로 잘못 마킹되는 것을 막기 위함(실측으로
    # 발견한 버그: 2024-08~2024-11이 0행인 채 done 마킹된 적 있음). 95% 미만이면
    # done 마커를 남기지 않아 다음 실행 때 자동으로 재수집되게 한다.
    if completeness >= 0.95:
        done_marker.touch()
    else:
        print(f"  ⚠️  완성도 {completeness:.1%} < 95% → done 마커 남기지 않음 (다음 실행 시 재수집)")

    audit_row = {
        'year_month': ym, 'expected_rows': expected_rows, 'actual_rows': actual_rows,
        'n_hours_requested': len(hours), 'n_hours_failed': len(failed_hours),
        'completeness': round(completeness, 4), 'status': status,
    }
    print(f"[{ym}] 기대 {expected_rows}행 / 실제 {actual_rows}행 / 요청실패 {len(failed_hours)}시간 [{status}]")
    return df_month, audit_row


def main():
    print("🚀 [ KMA AWS 서울 지역 시간자료 수집 시작 ]")
    seoul_df = load_seoul_stations()
    seoul_ids = set(seoul_df['stn_id'].tolist())
    n_stations = len(seoul_ids)
    print(f"📅 수집 범위: {START_YM[0]}-{START_YM[1]:02d} ~ {END_YM[0]}-{END_YM[1]:02d}, 서울 {n_stations}개 지점\n")

    all_months = []
    start_time = time.time()
    consecutive_total_failures = 0
    CIRCUIT_BREAKER_LIMIT = 2  # 완전 실패(0% 완성도)가 연속 이만큼 나오면 즉시 중단

    for y, m in month_range(START_YM, END_YM):
        try:
            df_month, audit_row = process_month(y, m, seoul_ids, n_stations)
        except DailyLimitExceeded:
            print(f"\n📋 이번 실행에서 {len(all_months)}개월 처리(캐시 포함). "
                  f"일일 한도가 풀리면 재실행 - 이미 끝난 달은 건너뛰고 이어서 진행됩니다.")
            sys.exit(1)

        if audit_row:
            # 월별로 즉시 감사 로그에 append - 중간에 프로세스가 죽어도(kill, 정전 등)
            # 이미 처리한 달의 감사 기록은 남도록 함(예전엔 전체 끝나고 한번에 저장해서
            # 중단 시 감사 기록이 통째로 유실되는 문제가 있었음).
            prev_audit = pd.read_csv(audit_log_file) if audit_log_file.exists() else pd.DataFrame()
            new_audit = pd.DataFrame([audit_row])
            combined = pd.concat([prev_audit, new_audit]).drop_duplicates('year_month', keep='last')
            combined.to_csv(audit_log_file, index=False, encoding='utf-8-sig')

            if audit_row['completeness'] == 0.0:
                consecutive_total_failures += 1
            else:
                consecutive_total_failures = 0

        if not df_month.empty:
            all_months.append(df_month)

        if consecutive_total_failures >= CIRCUIT_BREAKER_LIMIT:
            print(f"\n🛑 [중단] 완전 실패(완성도 0%)가 {CIRCUIT_BREAKER_LIMIT}개월 연속 발생 → "
                  f"API 서버 장애로 판단, 더 진행해도 낭비이므로 여기서 멈춤. "
                  f"연결 복구 확인 후 재실행하면 이어서 진행됩니다.")
            sys.exit(1)

    df_all = pd.concat(all_months, ignore_index=True) if all_months else pd.DataFrame()
    df_all = df_all.sort_values(['measure_time', 'stn_id']).reset_index(drop=True)
    df_all.to_parquet(output_file, index=False)

    elapsed = time.time() - start_time
    print(f"\n✅ [완료] {len(df_all):,}행 저장 → {output_file} ({elapsed/60:.1f}분 소요)")
    print(f"📋 감사 로그 → {audit_log_file}")


if __name__ == '__main__':
    main()

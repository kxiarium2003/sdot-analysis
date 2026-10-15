"""
script39-collect-mois-yearbook-shelters.py - 행정안전부 통계연보 "지역별 무더위 쉼터" 수집 (D7 보조)

공공데이터포털 15107290 (행정안전부_통계연보_지역별 무더위 쉼터) OpenAPI를 전 페이지 수집한다.
지점 목록이 아니라 기준년도×지역별 시설유형 개수 통계다. 연도별 서울 쉼터 총량을
2026 스냅샷(지점 목록)과 비교하는 용도.

엔드포인트: https://apis.data.go.kr/1741000/HealthSheltersForEachRegion/getHealthSheltersForEachRegion
파라미터: ServiceKey, pageNo, numOfRows (응답 XML)
명세에는 없지만 type=xml을 붙여야 한다. 빠지면 게이트웨이가 resultCode 04(HTTP 에러)를 돌려준다.

포털 키는 URL 인코딩된 형태(%2B, %3D)로 발급되므로, requests params에 넣으면 이중 인코딩된다.
인코딩 키를 쿼리스트링에 직접 붙여 먼저 시도하고, 실패하면 디코딩 키를 params로 넘긴다.
키 값은 어디에도 출력하지 않는다.

출력:
- data/raw/D7_cooling_shelter/stats_yearbook/page_NNN.xml - 원본 응답 그대로
- data/raw/D7_cooling_shelter/stats_yearbook/mois_yearbook_shelters_by_region.csv - 파싱한 표

사용법: python scripts/script39-collect-mois-yearbook-shelters.py
"""
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env')

API_KEY = os.environ.get('DATA_GO_KR_KEY')
if not API_KEY:
    print("❌ [오류] .env에 DATA_GO_KR_KEY가 설정되어 있지 않습니다.")
    sys.exit(1)

URL = 'https://apis.data.go.kr/1741000/HealthSheltersForEachRegion/getHealthSheltersForEachRegion'
NUM_OF_ROWS = 100
ROW_FIELDS = ['wrttimeid', 'seq', 'regi', 'tot', 'seni_shelts', 'welfhall', 'villhall',
              'health_center', 'resident_center', 'eupmyndng_office', 'religion_shelts',
              'financial_org', 'etc']

out_dir = PROJECT_ROOT / 'data' / 'raw' / 'D7_cooling_shelter' / 'stats_yearbook'
out_dir.mkdir(parents=True, exist_ok=True)
csv_file = out_dir / 'mois_yearbook_shelters_by_region.csv'


def request_page(page_no, key_mode):
    """key_mode='encoded': 포털 인코딩 키를 쿼리스트링에 직접, 'decoded': 디코딩 키를 params로."""
    if key_mode == 'encoded':
        url = f"{URL}?ServiceKey={API_KEY}&pageNo={page_no}&numOfRows={NUM_OF_ROWS}&type=xml"
        return requests.get(url, timeout=30)
    params = {'ServiceKey': unquote(API_KEY), 'pageNo': page_no, 'numOfRows': NUM_OF_ROWS, 'type': 'xml'}
    return requests.get(URL, params=params, timeout=30)


def parse(content):
    """(resultCode, resultMsg, totalCount, rows) 반환. 게이트웨이 오류 XML이면 rows=None."""
    root = ET.fromstring(content)
    if root.tag == 'OpenAPI_ServiceResponse':
        return root.findtext('.//returnReasonCode'), root.findtext('.//returnAuthMsg'), None, None
    code = root.findtext('.//RESULT/resultCode')
    msg = root.findtext('.//RESULT/resultMsg')
    total = root.findtext('.//head/totalCount')
    rows = [{f: r.findtext(f) for f in ROW_FIELDS} for r in root.iter('row')]
    return code, msg, int(total) if total else None, rows


def fetch_page(page_no, key_mode):
    resp = request_page(page_no, key_mode)
    resp.raise_for_status()
    code, msg, total, rows = parse(resp.content)
    return resp.content, code, msg, total, rows


# 1페이지로 키 형식 결정
key_mode = None
for mode in ('encoded', 'decoded'):
    try:
        content, code, msg, total, rows = fetch_page(1, mode)
    except Exception as e:
        print(f"⚠️  [{mode}] 요청 실패: {type(e).__name__}")
        continue
    if rows is not None and total is not None:
        key_mode = mode
        print(f"✅ [{mode}] 키로 응답 수신 (resultCode={code}, resultMsg={msg}, totalCount={total})")
        break
    print(f"⚠️  [{mode}] 오류 응답: code={code}, msg={msg}")

if key_mode is None:
    print("❌ [오류] 두 키 형식 모두 실패했습니다.")
    sys.exit(1)

n_pages = max(1, -(-total // NUM_OF_ROWS))
all_rows = []
for page_no in range(1, n_pages + 1):
    if page_no > 1:
        time.sleep(0.3)
        content, code, msg, _, rows = fetch_page(page_no, key_mode)
        if rows is None:
            print(f"❌ [오류] {page_no}페이지 오류 응답: code={code}, msg={msg}")
            sys.exit(1)
    (out_dir / f'page_{page_no:03d}.xml').write_bytes(content)
    all_rows.extend(rows)
    print(f"   page {page_no}/{n_pages}: {len(rows)}행")

df = pd.DataFrame(all_rows, columns=ROW_FIELDS)
if len(df) != total:
    print(f"⚠️  수집 행 수({len(df)})가 totalCount({total})와 다릅니다.")
df.to_csv(csv_file, index=False, encoding='utf-8-sig')
print(f"💾 {csv_file.relative_to(PROJECT_ROOT)} ({len(df)}행)")

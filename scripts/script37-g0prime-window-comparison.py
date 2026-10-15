"""
script37-g0prime-window-comparison.py - 기존 G0′ 기준을 우리 마스터(v2)에 적용한 창 비교 (Phase 0)

기존 정리: G0(연속 24개월)를 "네트워크 전체가 한 시간도 안 빠진 연속 24개월"로 엄격히
재실측하니 최장 4.83개월이라 G0′("시간별 완결도 ≥95% + 시간별 보고센서 ≥300대가 창의 90% 이상")로
재정의했고 2023-10-01~2025-09-30 창(완결도 97.8%)을 채택했다. 이 스크립트는 같은 기준을 우리
`master-v2`에 적용했을 때의 숫자를 계산해 보여줄 뿐이며, 어느 창을 채택할지는 판단하지 않는다.

정의(기존 정의를 그대로 재현할 수 없어 여기서 정한 것 — 반드시 함께 인용할 것):
- 시각(hour) = measure_time을 정시로 내림. `measure_time_year_outlier` 행은 제외.
- "행 있음"(R1) : 그 시각에 해당 센서의 행이 하나라도 있음.
- "기온 유효"(R2) : 그 시각에 temp_avg가 결측이 아니고 [-25, 45]°C 안 (script26 물리 범위와 동일).
- 보고 센서 수 n(h) : R2를 만족한 서로 다른 센서 수 (기본). R1 기준도 별도로 계산.
- 기대 센서 수 E(h) : 센서의 활동기간(그 센서의 최초~최후 R2 유효 시각, script26의 관측기간 개념)
  안에 h가 들어가는 센서 수. 센서 집합은 (ALL) 기온 유효값이 한 번이라도 있는 전체 센서,
  (NORMAL) 센서 등급표 최종 '정상' 469대 두 가지.
- 시간별 완결도 c(h) = n(h) / E(h).
- 시각 h가 G0′를 충족 = (c(h) ≥ 0.95) AND (n(h) ≥ 300).
- 창 = 달력월 시작 기준 24개월(자료 끝 2026-08-30 23:00에서 잘림). 창 충족 비율 = 충족 시각 ÷ 창 시간수.
  G0′ 통과 = 그 비율 ≥ 0.90.
- 기존 "창 완결도"는 정의가 불분명해 "어떤 센서든 행이 있는 시각 비율"(네트워크 발행률, R1)도
  같이 산출한다(그의 '미발행 시간 540시간(3.1%)' 서술과 대응).

주의: master-v2는 12시간제 접힘이 미해결(docs/data-source-notes.md 2026-09-08)이라 일부 행의 시각이
12시간 어긋나 있을 수 있다. 이 스크립트는 시각을 있는 그대로 사용하므로 시각별 집계에 그 영향이 남아 있다.

출력: data/interim/g0prime_hourly.parquet(시각별 지표), docs/g0prime-window-candidates.csv(창별 지표)
"""
import os
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASTER = PROJECT_ROOT / 'data' / 'processed' / 'master-v2' / 'sdot_master_2020_2026_v2.parquet'
QUALITY = PROJECT_ROOT / 'docs' / 'sdot-sensor-quality-report.csv'
HOURLY_OUT = PROJECT_ROOT / 'data' / 'interim' / 'g0prime_hourly.parquet'
WINDOW_OUT = PROJECT_ROOT / 'docs' / 'g0prime-window-candidates.csv'

DATA_START = pd.Timestamp('2020-04-01 00:00:00')
DATA_END = pd.Timestamp('2026-08-30 23:00:00')
COMP_MIN, N_MIN, WIN_MIN = 0.95, 300, 0.90
NAMED = {
    '기존 채택 창 2023-10-01~2025-09-30': (pd.Timestamp('2023-10-01'), pd.Timestamp('2025-10-01')),
    '우리 분석범위 2024-09-01~2026-08-30': (pd.Timestamp('2024-09-01'), pd.Timestamp('2026-08-31')),
    '기존 2년 자료 2024-01-01~2025-12-31': (pd.Timestamp('2024-01-01'), pd.Timestamp('2026-01-01')),
}


def hourly_metrics():
    normal = pd.read_csv(QUALITY).query("final_grade == '정상'")['sensor_id'].tolist()
    con = duckdb.connect()
    con.execute("SET memory_limit='5GB'")
    con.execute(f"SET temp_directory='{(PROJECT_ROOT / 'data' / 'interim' / '.duckdb_tmp').as_posix()}'")
    con.execute("CREATE TEMP TABLE normal_ids(sensor_id VARCHAR)")
    con.executemany("INSERT INTO normal_ids VALUES (?)", [(s,) for s in normal])
    base = f"""
        SELECT sensor_id, date_trunc('hour', TRY_CAST(measure_time AS TIMESTAMP)) AS h,
               (temp_avg IS NOT NULL AND temp_avg BETWEEN -25 AND 45) AS valid
        FROM read_parquet('{MASTER.as_posix()}')
        WHERE NOT coalesce(measure_time_year_outlier, false) AND TRY_CAST(measure_time AS TIMESTAMP) IS NOT NULL
    """
    unparsed = con.execute(f"SELECT count(*) FROM read_parquet('{MASTER.as_posix()}') WHERE TRY_CAST(measure_time AS TIMESTAMP) IS NULL").fetchone()[0]
    print(f"measure_time 파싱 실패 행: {unparsed:,}")
    hourly = con.execute(f"""
        SELECT h,
               count(DISTINCT sensor_id) AS n_rows_all,
               count(DISTINCT CASE WHEN valid THEN sensor_id END) AS n_valid_all,
               count(DISTINCT CASE WHEN sensor_id IN (SELECT sensor_id FROM normal_ids) THEN sensor_id END) AS n_rows_normal,
               count(DISTINCT CASE WHEN valid AND sensor_id IN (SELECT sensor_id FROM normal_ids) THEN sensor_id END) AS n_valid_normal
        FROM ({base}) GROUP BY h
    """).fetchdf()
    spans = con.execute(f"""
        SELECT sensor_id, min(h) AS first_h, max(h) AS last_h
        FROM ({base}) WHERE valid GROUP BY sensor_id
    """).fetchdf()
    return hourly, spans, set(normal)


def expected_counts(spans, grid):
    first = np.sort(spans['first_h'].values.astype('datetime64[ns]'))
    last = np.sort(spans['last_h'].values.astype('datetime64[ns]'))
    g = grid.values.astype('datetime64[ns]')
    started = np.searchsorted(first, g, side='right')      # first <= h
    ended = np.searchsorted(last, g, side='left')          # last < h
    return started - ended


def window_stats(df, start, end):
    w = df[(df['h'] >= start) & (df['h'] < end)]
    n = len(w)
    out = {'hours': n}
    for tag in ['all', 'normal']:
        comp = w[f'c_{tag}']
        nv = w[f'n_valid_{tag}']
        ok = (comp >= COMP_MIN) & (nv >= N_MIN)
        out[f'{tag}_G0p_share'] = ok.mean()
        out[f'{tag}_n>=300_share'] = (nv >= N_MIN).mean()
        out[f'{tag}_c>=0.95_share'] = (comp >= COMP_MIN).mean()
        out[f'{tag}_mean_c'] = comp.mean()
        out[f'{tag}_median_n'] = nv.median()
    out['network_published_R1'] = (w['n_rows_all'] > 0).mean()
    out['network_published_R2'] = (w['n_valid_all'] > 0).mean()
    out['empty_hours_R1'] = int((w['n_rows_all'] == 0).sum())
    return out


def main():
    hourly, spans, normal = hourly_metrics()
    grid = pd.Series(pd.date_range(DATA_START, DATA_END, freq='h'), name='h')
    df = grid.to_frame().merge(hourly, on='h', how='left').fillna(0)
    for c in ['n_rows_all', 'n_valid_all', 'n_rows_normal', 'n_valid_normal']:
        df[c] = df[c].astype(int)
    df['E_all'] = expected_counts(spans, grid)
    sp_n = spans[spans['sensor_id'].isin(normal)]
    df['E_normal'] = expected_counts(sp_n, grid)
    for tag in ['all', 'normal']:
        df[f'c_{tag}'] = np.where(df[f'E_{tag}'] > 0, df[f'n_valid_{tag}'] / df[f'E_{tag}'].where(df[f'E_{tag}'] > 0, 1), 0.0)
    df.to_parquet(HOURLY_OUT, index=False)
    print(f"시각 수 {len(df):,}, 센서 {len(spans):,}대(정상 {len(sp_n):,}대) 기온 유효 활동기간 산출")

    rows = []
    for name, (s, e) in NAMED.items():
        r = window_stats(df, s, e); r['window'] = name; r['kind'] = 'named'; rows.append(r)
    starts = pd.date_range('2020-04-01', '2024-09-01', freq='MS')
    for s in starts:
        e = s + pd.DateOffset(months=24)
        r = window_stats(df, s, e)
        r['window'] = f"{s:%Y-%m}~{(min(e, DATA_END + pd.Timedelta(hours=1)) - pd.Timedelta(days=1)):%Y-%m}"
        r['kind'] = 'sliding24'; rows.append(r)
    res = pd.DataFrame(rows)
    cols = ['kind', 'window', 'hours', 'all_G0p_share', 'all_n>=300_share', 'all_c>=0.95_share', 'all_mean_c', 'all_median_n',
            'normal_G0p_share', 'normal_n>=300_share', 'normal_c>=0.95_share', 'normal_mean_c', 'normal_median_n',
            'network_published_R1', 'network_published_R2', 'empty_hours_R1']
    res = res[cols]
    res.to_csv(WINDOW_OUT, index=False)
    pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
    fmt = res.copy()
    for c in fmt.columns:
        if fmt[c].dtype == float:
            fmt[c] = fmt[c].round(4)
    print("\n=== 지정 창 ===")
    print(fmt[fmt.kind == 'named'].drop(columns='kind').T.to_string())
    sl = fmt[fmt.kind == 'sliding24'].drop(columns='kind')
    print("\n=== 24개월 슬라이딩 상위 8 (ALL 기준 G0′ 충족 시각 비율) ===")
    print(sl.sort_values('all_G0p_share', ascending=False).head(8)[['window', 'hours', 'all_G0p_share', 'all_n>=300_share', 'all_c>=0.95_share', 'all_mean_c', 'network_published_R1', 'network_published_R2', 'normal_G0p_share']].to_string(index=False))
    print("\n=== 24개월 슬라이딩 상위 8 (네트워크 발행률 R1) ===")
    print(sl.sort_values('network_published_R1', ascending=False).head(8)[['window', 'hours', 'network_published_R1', 'network_published_R2', 'all_n>=300_share', 'all_G0p_share']].to_string(index=False))
    print("\n=== 전체 슬라이딩 창 요약 ===")
    print(sl[['window', 'all_G0p_share', 'all_n>=300_share', 'all_c>=0.95_share', 'network_published_R1']].to_string(index=False))


if __name__ == '__main__':
    main()

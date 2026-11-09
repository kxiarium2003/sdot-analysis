# D1 시각 출처(`measure_time_source`) 판정 로직 — 인계 자료

작성: 2026-10-05 · 대상: 박현우 조교 (RQ1 진행 보고서 7.2절 "시각 출처 코드 미수령" 대응)
근거 코드: `scripts/script22-merge-yearly-v8.py` (현행 정식 병합 파이프라인)
근거 기록: `docs/data-source-notes.md` 2026-08-07 항목

---

## 0. 먼저 읽어주실 것 — 적용 범위

**이 로직은 2023년 이후 데이터에는 적용되지 않습니다.** 코드가 `측정시간` 컬럼이
있으면 즉시 그 값을 쓰고 `전송시간`/`등록일자`는 쳐다보지도 않기 때문입니다(아래 ①번 분기).

조교님께서 "2024-25 원본에는 전송시간 열이 없어서 양쪽 다 100% 측정시간을 쓴다"고
전처리 결정표에 적어두신 것과 **일치하며, 저희 산출물로도 확인됩니다.**

| 연도 | `mt`(측정시간) | `reg_fallback`(등록일자 폴백) | `tx`(전송시간) | `reg_dateguard` |
|---|---|---|---|---|
| 2020 | 22.6% | 77.4% | — | — |
| 2021 | 1.6% | 98.4% | — | 0.0% (1,091행) |
| 2022 | 3.5% | 94.2% | 2.3% | — |
| **2023** | **100%** | — | — | — |
| **2024** | **100%** | — | — | — |
| **2025** | **100%** | — | — | — |
| 2026 | 100% | — | — | — |

전체 53,134,947행 기준: `mt` 59.16%, `reg_fallback` 40.49%, `tx` 0.35%, `reg_dateguard` 0.00%.

따라서 조교님 분석 창(2024-01~2025-12)에서는 **이 판정 로직이 한 번도 작동하지 않았습니다.**
아래 내용은 "왜 2020~2022에 대해 그런 판정을 했는가"의 근거 자료로만 쓰시면 됩니다.

---

## 1. `resolve_measure_time()` 전체 코드

`scripts/script22-merge-yearly-v8.py` 112~188행.

```python
112  def resolve_measure_time(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
113      """전송시간 우선, 결측/E+/더미값일 때만 등록일자로 폴백.
114      단, 전송시간이 유효해도 등록일자와 날짜(캘린더 일자)가 갈리는 경우엔
115      일별 집계 왜곡을 막기 위해 등록일자를 우선한다 (measure_time_tx_reg_mismatch=True로 표시).
116      (measure_time, source, tx_reg_mismatch) 반환
117      """
118      norm_lookup = {normalize_key(c): c for c in df.columns}
119      tx_col = norm_lookup.get('전송시간')
120      reg_col = norm_lookup.get('등록일자')
121      mt_col = norm_lookup.get('측정시간')
122
123      n = len(df)
124      measure_time = pd.Series([None] * n, index=df.index, dtype=object)
125      source = pd.Series(['missing'] * n, index=df.index, dtype=object)
126      mismatch = pd.Series([False] * n, index=df.index, dtype=bool)
127
128      # 2023년 이후 스키마는 측정시간 컬럼을 쓰지만, "정상"이라는 건 아직 검증된 적 없는 가정이므로
129      # 다른 분기와 동일하게 정규화-파싱을 거친다 (여기서 실패하면 NaN -> 이후 행 폐기 대상)
130      if mt_col is not None:
131          measure_time = normalize_and_parse(df[mt_col])
132          source = pd.Series(['mt'] * n, index=df.index, dtype=object)
133          return measure_time, source, mismatch
134
135      reg_raw = df[reg_col].astype(str) if reg_col is not None else pd.Series([None] * n, index=df.index)
136
137      # 전송시간 검증/파싱 - 전량 벡터화 (행 단위 .map()은 수천만 행에서 치명적으로 느림, 스팟체크 중 실측)
138      tx_parsed = pd.Series([None] * n, index=df.index, dtype=object)
139      if tx_col is not None:
140          tx_raw = df[tx_col].astype(str).str.strip()
141          tx_is_null = tx_raw.isna() | tx_raw.isin(['None', 'nan'])
142          tx_has_e = tx_raw.str.upper().str.contains('E+', regex=False)
143          digits = tx_raw.str.split('.', n=1).str[0]
144          numeric_match = tx_raw.str.match(r'^(\d{12}|\d{14})(\.0)?$')
145          dummy_mask = numeric_match & ((digits.str.slice(4, 6) == '00') | (digits.str.slice(6, 8) == '00'))
146
147          tx_valid_mask = (~tx_is_null) & (~tx_has_e) & (~dummy_mask)
148
149          len12_mask = tx_valid_mask & (digits.str.len() == 12)
150          len14_mask = tx_valid_mask & (digits.str.len() == 14)
151          if len12_mask.any():
152              dt12 = pd.to_datetime(digits[len12_mask], format='%Y%m%d%H%M', errors='coerce')
153              tx_parsed.loc[len12_mask] = dt12.dt.strftime('%Y-%m-%d %H:%M:%S')
154          if len14_mask.any():
155              dt14 = pd.to_datetime(digits[len14_mask], format='%Y%m%d%H%M%S', errors='coerce')
156              tx_parsed.loc[len14_mask] = dt14.dt.strftime('%Y-%m-%d %H:%M:%S')
157
158          # 파싱 자체가 실패하면(예외 케이스) 유효 마스크에서 제외
159          tx_valid_mask = tx_valid_mask & tx_parsed.notna()
160      else:
161          tx_raw = pd.Series([None] * n, index=df.index)
162          tx_valid_mask = pd.Series([False] * n, index=df.index)
163
164      # 등록일자는 대시/점/언더스코어+초/PM접미사 4개 포맷이 섞여 있으므로 여기서 정규화-파싱까지 끝낸다
165      reg_parsed = normalize_and_parse(reg_raw) if reg_col is not None else pd.Series([None] * n, index=df.index)
166      reg_available_mask = reg_parsed.notna()
167      reg_date = reg_parsed.str.slice(0, 10)
168      tx_date = tx_parsed.str.slice(0, 10)
169
170      date_mismatch_mask = tx_valid_mask & reg_available_mask & (tx_date != reg_date)
171      mismatch.loc[date_mismatch_mask] = True
172
173      # 1) 전송시간 유효 + 등록일자와 날짜 일치 (또는 등록일자 자체가 없음) -> 전송시간 채택
174      tx_final_mask = tx_valid_mask & ~date_mismatch_mask
175      measure_time.loc[tx_final_mask] = tx_parsed.loc[tx_final_mask]
176      source.loc[tx_final_mask] = 'tx'
177
178      # 2) 전송시간 유효하지만 등록일자와 날짜가 갈림 -> 일자 왜곡 방지 위해 등록일자 채택
179      dateguard_mask = date_mismatch_mask & reg_available_mask
180      measure_time.loc[dateguard_mask] = reg_parsed.loc[dateguard_mask]
181      source.loc[dateguard_mask] = 'reg_dateguard'
182
183      # 3) 전송시간 자체가 무효 -> 등록일자로 폴백
184      fallback_mask = (~tx_valid_mask) & reg_available_mask
185      measure_time.loc[fallback_mask] = reg_parsed.loc[fallback_mask]
186      source.loc[fallback_mask] = 'reg_fallback'
187
188      return measure_time, source, mismatch
```

### `measure_time_source`가 실제로 채워지는 지점 (242~268행)

`resolve_measure_time()`이 반환한 `source`가 **254행**에서 컬럼으로 붙습니다.

```python
242          measure_time, source, tx_reg_mismatch = resolve_measure_time(df)
243
244          rename_map = rename_dicts.get(version, {})
245          actual_rename = {col: rename_map[col.strip()] for col in df.columns if col.strip() in rename_map}
246          df = df.rename(columns=actual_rename)
247
248          if df.columns.duplicated().any():
249              df = df.loc[:, ~df.columns.duplicated()]
250
251          cols_to_keep = [c for c in df.columns if c in master_columns and c != 'measure_time']
252          df = df[cols_to_keep]
253          df['measure_time'] = measure_time
254          df['measure_time_source'] = source
255          df['measure_time_tx_reg_mismatch'] = tx_reg_mismatch
256
257          # 밀림 행(측정시간에 온도가 들어간 경우) 폐기 - script16과 동일 기준
258          measure_time_str = df['measure_time'].astype(str)
259          valid_mask = (measure_time_str.str.len() >= 8) & (measure_time_str != 'None')
260          dropped = (~valid_mask).sum()
261
262          drop_reasons = df.loc[~valid_mask, 'measure_time_source'].map({
263              'missing': 'tx_invalid_and_reg_missing',
264              'mt': 'mt_present_but_unparseable',
265          }).fillna('other')
266          drop_reason_counter.update(drop_reasons.value_counts().to_dict())
267
268          df = df[valid_mask]
```

`source` 값은 5종이며, 이 중 `missing`(전송시간 무효 + 등록일자도 없음/파싱불가)은
259~268행에서 행째로 폐기되므로 최종 산출물에는 남지 않습니다.

| 값 | 의미 |
|---|---|
| `mt` | `측정시간` 컬럼이 존재해 그대로 채택 (2023년 이후 전부) |
| `tx` | `전송시간`이 유효하고 `등록일자`와 날짜가 일치(또는 등록일자 없음) → 전송시간 채택 |
| `reg_dateguard` | `전송시간`은 유효하나 `등록일자`와 **캘린더 일자가 다름** → 등록일자 채택 |
| `reg_fallback` | `전송시간`이 무효(결측/E+/더미/파싱실패) → 등록일자 채택 |
| `missing` | 둘 다 쓸 수 없음 → **행 폐기** (산출물에 없음) |

---

## 2. 로직 요약 (두 문장)

`측정시간` 컬럼이 있으면 그것을 쓰고, 없을 때만 `전송시간`을 우선하되 전송시간이
결측·`E+` 지수표기·더미값(월 또는 일이 `00`)·파싱실패면 `등록일자`로 폴백합니다.
다만 전송시간이 유효하더라도 등록일자와 **캘린더 일자가 갈리는 경우**에는 일별 집계
왜곡을 막기 위해 등록일자를 채택하고, 모든 행에 어느 쪽을 썼는지를
`measure_time_source`로 남깁니다.

### ⚠️ 기존 한 줄 설명과 실제 코드의 차이 (코드 재확인 결과)

"전송시간 우선, 결측/E+/더미값일 때만 등록일자로 대체"라는 요약은 **2020~2022 스키마에
한해, 그리고 부분적으로만** 맞습니다. 실제 코드에는 그 설명에 없는 동작이 세 가지 있습니다.

1. **`측정시간` 단락(short-circuit)이 최우선** — 130~133행. `측정시간` 컬럼이 존재하면
   전송시간/등록일자를 **아예 보지 않고** 즉시 반환합니다. "전송시간 우선"은 측정시간
   컬럼이 없는 스키마에서만 성립합니다.
2. **날짜 불일치 시 등록일자가 전송시간을 이김** — 170~181행. 전송시간이 완전히 유효해도
   등록일자와 날짜가 다르면 등록일자를 씁니다(`reg_dateguard`). 즉 "전송시간 우선"이
   절대적이지 않습니다. (함수 docstring 114~115행에는 적혀 있으나 한 줄 요약에는 빠져
   있던 부분입니다. 실측 1,091행, 2021년에만 발생)
3. **파싱 실패도 폴백 사유** — 159행. 결측/E+/더미가 아니어도 12자리·14자리 숫자로
   파싱되지 않으면 무효 처리됩니다. 사실상 `YYYYMMDDHHMM(SS)` 숫자형만 전송시간으로
   인정됩니다.

---

## 3. 원천부서 확인 근거

`docs/data-source-notes.md` 2026-08-07 항목 원문입니다.

> **2026-08-07 — 전송시간 결측 시 등록일자 대체 관련 확인**
> - **일시**: 2026-08-07(금) 14:09, 약 8분간
> - **대상**: 원천 부서 (02-2133-1839)
> - **확인 내용**: `전송시간`(IoT 센서가 값을 전송한 시각) 값이 결측이거나 사용 불가능한
>   경우, `등록일자`(DB 저장 시각)로 대체해서 사용해도 데이터 정합성에 문제가 없다는
>   답변을 유선으로 확인함.
> - **적용 범위**: `metadata/sdot-schema-mapping.xlsx`의 `v2020_2022_recovered`,
>   `v2020_2022_corrupted` 스키마 — `전송시간`이 결측/E+ 표기/더미값(`YYYYMMDDHHMM`로
>   파싱 시 월 또는 일이 `00`)인 경우에 한해 `등록일자`로 폴백.
> - **구현**: `scripts/script22-merge-yearly-v8.py`의 `resolve_measure_time()` — 대체된
>   행은 `measure_time_source='reg_fallback'`으로 별도 표시해 원본 소스를 추적 가능하게 함.
> - **한계**: 이 근거는 현재 유선 확인(구두)에만 의존하고 있음. 서면 회신이나 공식 문서가
>   있다면 이 파일에 추가해 보강할 것.

**이 통화가 다루지 않은 것(중요)**: 이 확인은 "전송시간이 못 쓸 값일 때 등록일자로
대체해도 되는가"에 대한 것이며, **`측정시간`과 `전송시간` 중 무엇을 우선할지에 대한
확인이 아닙니다.** 범위도 2020~2022 스키마로 명시되어 있어, 2023년 이후 `측정시간`
채택에 대한 근거로는 쓸 수 없습니다. 2023년 이후 `측정시간`의 12시간제(AM/PM) 접힘
의심 건은 별도 미해결 사안으로 `docs/data-source-notes.md` 2026-09-08 항목에 있으며,
원천부서 확인 없이 정황 증거만으로 진행 중입니다.

---

## 4. 참고 — 함께 생성되는 컬럼

| 컬럼 | 설명 |
|---|---|
| `measure_time_source` | 위 5종 코드 |
| `measure_time_tx_reg_mismatch` | 전송시간·등록일자의 캘린더 일자가 갈린 행 플래그 (전체 1,091행, 전부 2021년) |
| `measure_time_year_outlier` | 파일이 대표하는 연도에서 ±1년 넘게 벗어난 행 플래그 (전체 1행) |

세 컬럼 모두 "버리지 않고 표시만 한다(flag, don't filter)" 원칙에 따라 마스터
(`data/processed/master-v2/sdot_master_2020_2026_v2.parquet`)까지 보존됩니다.

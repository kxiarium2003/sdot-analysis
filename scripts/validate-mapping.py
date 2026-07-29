import pandas as pd
from pathlib import Path

# 1. 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parent.parent
excel_path = PROJECT_ROOT / 'metadata' / 'sdot-schema-mapping.xlsx'

print(f"🔍 엑셀 파일 로드 및 교차 검증 시작... ({excel_path.name})\n")

df_inv = pd.read_excel(excel_path, sheet_name='FileInventory')
df_mapping = pd.read_excel(excel_path, sheet_name='ColumnMapping')

schema_versions = df_inv['schema_version'].dropna().unique()

# 🚫 우리가 의도적으로 버리기로 한 컬럼들의 키워드
ignore_keywords = ['기관', '모델', '구분', '등록', 'unnamed', '지역', '행정동', '자치구']

all_perfect = True

for version in schema_versions:
    if version not in df_mapping.columns:
        continue
        
    # 1️⃣ 원본 데이터에 존재하는 모든 고유 컬럼 수집 (A집합)
    version_files = df_inv[df_inv['schema_version'] == version]
    original_cols = set()
    for col_list_str in version_files['all_columns_list'].dropna():
        # Inventory에 저장될 때 쉼표(,)로 저장되었으므로 분리해서 집합에 추가
        cols = [c.strip() for c in str(col_list_str).split(',')]
        original_cols.update(cols)
        
    # 2️⃣ ColumnMapping 시트에 매핑된 원본 컬럼명 수집 (B집합)
    mapped_cols = set()
    for val in df_mapping[version].dropna():
        # 한 마스터 컬럼에 여러 원본 컬럼이 콤마로 매핑되었을 수 있으므로 분리
        cols = [c.strip() for c in str(val).split(',')]
        mapped_cols.update(cols)
        
    # 3️⃣ 차집합(A - B) 계산: 원본에는 있는데 매핑 시트에는 없는 컬럼
    unmapped_cols = original_cols - mapped_cols
    
    # 4️⃣ 매핑 안 된 컬럼 중, '의도된 누락'인지 '진짜 실수'인지 분류
    expected_ignores = []
    unexpected_misses = []
    
    for col in unmapped_cols:
        norm = col.replace(" ", "").replace("_", "").lower()
        if any(kw in norm for kw in ignore_keywords):
            expected_ignores.append(col)
        else:
            unexpected_misses.append(col)
            
    # 📊 결과 출력
    print(f"📌 [ {version} ]")
    print(f"  - 원본 컬럼 총 개수: {len(original_cols)}개")
    print(f"  - 매핑 완료된 개수: {len(mapped_cols)}개")
    print(f"  - 의도적 제외(Ignore): {len(expected_ignores)}개 ({', '.join(expected_ignores[:5])}{' 등' if len(expected_ignores)>5 else ''})")
    
    if len(unexpected_misses) == 0:
        print("  ✅ 누락된 필수 컬럼 없음! (Perfect Match)\n")
    else:
        print(f"  🚨 [경고] 매핑 누락된 필수 컬럼 발견!: {unexpected_misses}\n")
        all_perfect = False

# 5. 최종 판정
print("-" * 50)
if all_perfect:
    print("🎉 [최종 결과] 모든 스키마가 완벽하게 검증되었습니다! 🚀 다음 병합(Merge) 단계로 넘어가셔도 좋습니다!")
else:
    print("⚠️ [최종 결과] 일부 스키마에 누락된 필수 컬럼이 있습니다. 'sdot-schema-mapping.xlsx'를 열어 확인해 주세요.")
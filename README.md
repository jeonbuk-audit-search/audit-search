import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="전북특별자치도교육청 감사사례 검색기", page_icon="🔍", layout="wide")

st.title("🏫 전북교육청 학교 감사 지적사례 검색기")
st.markdown("**행정실·교무실 실무자를 위한 맞춤형 사전 예방 도구** (기획: 감사관실 최대호)")
st.markdown("---")

@st.cache_data
def load_data():
    df = pd.read_excel("감사결과_통합DB.xlsx")
    df['본문내용'] = df['본문내용'].fillna('')
    return df

try:
    df = load_data()
except FileNotFoundError:
    st.error("🚨 '감사결과_통합DB.xlsx' 파일을 찾을 수 없습니다. 파일이 같은 폴더에 있는지 확인해주세요!")
    st.stop()

col1, col2 = st.columns([3, 1])
with col1:
    search_query = st.text_input("🔍 검색어를 입력하세요 (예: 수의계약, 수학여행, 초과근무, 여비)", "")

if search_query:
    mask = df['본문내용'].str.contains(search_query, case=False, na=False)
    results = df[mask]
    
    st.markdown(f"### 📊 검색 결과: 총 **{len(results)}건**의 문서가 발견되었습니다.")
    
    if len(results) > 0:
        for index, row in results.iterrows():
            with st.expander(f"📄 {row['파일명']}"):
                content = row['본문내용']
                matches = [m.start() for m in re.finditer(search_query, content)]
                
                if matches:
                    st.markdown("**📌 주요 발견 부분 (앞뒤 문맥 요약):**")
                    for match_idx in matches[:3]: 
                        start = max(0, match_idx - 50)
                        end = min(len(content), match_idx + 150)
                        snippet = content[start:end]
                        snippet = snippet.replace(search_query, f"**<span style='color:red'>{search_query}</span>**")
                        st.markdown(f"> ...{snippet}...")
                        st.markdown("---")
                
                if st.button("전체 본문 보기", key=f"btn_{index}"):
                    st.text_area("문서 전체 내용", row['본문내용'], height=300)
    else:
        st.info("해당 키워드가 포함된 감사 지적 사례가 없습니다. 다른 검색어로 시도해 보세요.")
else:
    st.info("👆 위 검색창에 궁금한 감사 지적 키워드를 입력해 보세요.")


---

## 📋 학교 업무 인수인계 프로그램

일·월·분기·년 주기별 업무 카드, 마감 알림 배너, 감사사례 연계, 인계서 확정·서명·PDF, 학교별 비밀번호를 제공합니다.
기획서: `docs/인수인계_프로그램_기획서.md`

```bash
pip install -r requirements.txt
HANDOVER_ADMIN_PASSWORD=관리자암호 streamlit run handover_app.py   # 관리자 암호는 비밀번호 초기화용(선택)
```

- 데이터: 로컬 `handover.db`(SQLite, git 제외). 정기 백업 권장
- PDF 한글: `fonts/NanumGothic.ttf`를 넣어 두면 어느 PC에서나 동일하게 출력
- 표준 업무 카드: `handover_templates.csv` (학교에서 불러와 수정)
- 외부 공개 시 https 필수. 인계서에 개인정보 입력 금지

- 간편 실행: Windows는 `실행.bat` 더블클릭, 리눅스·맥은 `./run.sh` (처음 한 번 자동 설치 후 브라우저에서 열림)

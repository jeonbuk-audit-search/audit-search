import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="전북특별자치도교육청 감사사례 검색기", page_icon="🔍", layout="wide")

st.title("🏫 전북교육청 학교 감사 지적사례 검색기")
st.markdown("**행정실·교무실 실무자를 위한 맞춤형 사전 예방 도구** (기획: 감사관실 최대호)")
st.markdown("---")

@st.cache_data
def load_data():
    # 엑셀 대신 가벼운 CSV 파일을 읽도록 수정된 부분입니다!
    df = pd.read_csv("감사결과_통합DB.csv")
    df['본문내용'] = df['본문내용'].fillna('')
    return df

try:
    df = load_data()
except FileNotFoundError:
    st.error("🚨 '감사결과_통합DB.csv' 파일을 찾을 수 없습니다. 파일이 같은 폴더에 있는지 확인해주세요!")
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

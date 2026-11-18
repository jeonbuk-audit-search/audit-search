"""학교 업무 인수인계 프로그램 (MVP)
실행: streamlit run handover_app.py
- 학교 기준으로 업무 카드를 직접 작성/관리 (행정실·교무실 모두)
- 일·월·분기·년 주기별 체크리스트, 감사사례 자동 연결, 인수인계서 생성
- 로컬 SQLite 저장 → 내부망/외부 어디서든 동일하게 동작
"""
import calendar
import hashlib
import io
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

BASE = Path(__file__).parent
DB_PATH = BASE / "handover.db"
TEMPLATE_CSV = BASE / "handover_templates.csv"
AUDIT_CSV = BASE / "감사결과_통합DB.csv"

DEPTS = ["행정실", "교무실"]
CYCLES = ["일", "월", "분기", "년"]
STATUSES = ["미착수", "진행", "완료", "해당없음"]

st.set_page_config(page_title="학교 업무 인수인계", page_icon="📋", layout="wide")


# ---------- DB ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT, school TEXT, dept TEXT,
            role TEXT, title TEXT, cycle TEXT, months TEXT, due_day INTEGER,
            basis TEXT, procedure TEXT, systems TEXT, keywords TEXT, notes TEXT);
        CREATE TABLE IF NOT EXISTS logs(
            task_id INTEGER, period TEXT, status TEXT, memo TEXT, updated TEXT,
            PRIMARY KEY(task_id, period));
        CREATE TABLE IF NOT EXISTS handover_docs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, school TEXT, role TEXT,
            from_name TEXT, to_name TEXT, content TEXT, doc_hash TEXT, created TEXT,
            signed_from_at TEXT, signed_to_at TEXT);
        """
    )
    return con


# ---------- 주기 계산 ----------
def parse_months(s):
    return [int(m) for m in re.findall(r"\d+", s or "") if 1 <= int(m) <= 12]


def period_key(cycle, d):
    if cycle == "일":
        return d.isoformat()
    if cycle == "월":
        return f"{d.year}-{d.month:02d}"
    if cycle == "분기":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    return str(d.year)


def is_active(task, d):
    if task["cycle"] in ("일", "월"):
        return True
    return d.month in parse_months(task["months"])


def due_date(task, d):
    """이번 주기의 기한일. 기한(일)=0이면 말일."""
    last = calendar.monthrange(d.year, d.month)[1]
    day = task["due_day"] or 0
    return date(d.year, d.month, last if day == 0 or day > last else day)


# ---------- 감사사례 ----------
@st.cache_data
def load_audit():
    if not AUDIT_CSV.exists():
        return None
    df = pd.read_csv(AUDIT_CSV, encoding="utf-8-sig")
    df["본문내용"] = df["본문내용"].fillna("")
    return df


def audit_snippets(keywords, limit=3):
    df = load_audit()
    out = []
    if df is None:
        return out
    for kw in [k.strip() for k in re.split(r"[,·]", keywords or "") if k.strip()]:
        hits = 0
        for _, row in df.iterrows():
            m = re.search(re.escape(kw), row["본문내용"])
            if m:
                s = max(0, m.start() - 60)
                out.append((kw, row["파일명"], row["본문내용"][s : m.end() + 140].replace("\n", " ")))
                hits += 1
                if hits >= limit:
                    break
    return out[:limit]


# ---------- 사이드바 ----------
st.sidebar.title("📋 학교 업무 인수인계")
school = st.sidebar.text_input("학교명", value=st.session_state.get("school", ""), placeholder="예: ○○초등학교")
st.session_state["school"] = school
dept_filter = st.sidebar.multiselect("부서", DEPTS, default=DEPTS)
today = st.sidebar.date_input("기준 날짜", value=date.today())
st.sidebar.info(
    "⚠️ 인계서에는 주민번호·계좌번호·비밀번호 등 개인정보를 입력하지 마세요. "
    "증빙은 '위치(문서번호·폴더 경로)'만 적습니다."
)

if not school.strip():
    st.title("📋 학교 업무 인수인계 프로그램")
    st.info("👈 왼쪽에 학교명을 입력하면 시작할 수 있습니다. 업무 카드는 학교별로 따로 저장됩니다.")
    st.stop()

con = db()
tasks = pd.read_sql_query(
    "SELECT * FROM tasks WHERE school=? AND dept IN (%s) ORDER BY dept, cycle, id"
    % ",".join("?" * len(dept_filter or [""])),
    con,
    params=[school, *(dept_filter or [""])],
)

st.title(f"📋 {school} 업무 인수인계")
tab_today, tab_cards, tab_handover = st.tabs(["✅ 주기별 업무", "🗂️ 업무 카드 관리", "📄 인수인계서"])

# ---------- 탭1: 주기별 업무 ----------
with tab_today:
    if tasks.empty:
        st.info("등록된 업무 카드가 없습니다. '업무 카드 관리' 탭에서 표준 양식을 불러오거나 직접 추가하세요.")
    cycle_tabs = st.tabs([f"{c}별" for c in CYCLES])
    for c, ctab in zip(CYCLES, cycle_tabs):
        with ctab:
            sub = [t for _, t in tasks.iterrows() if t["cycle"] == c and is_active(t, today)]
            pkey_label = {"일": "오늘", "월": "이번 달", "분기": "이번 분기", "년": "올해"}[c]
            if not sub:
                st.caption(f"{pkey_label} 해당하는 {c}별 업무가 없습니다.")
                continue
            pk = period_key(c, today)
            logs = {
                r["task_id"]: r
                for r in con.execute("SELECT * FROM logs WHERE period=?", (pk,)).fetchall()
            }
            done = sum(1 for t in sub if logs.get(t["id"]) and logs[t["id"]]["status"] in ("완료", "해당없음"))
            st.progress(done / len(sub), text=f"{pkey_label} 진행률 {done}/{len(sub)}")
            for t in sub:
                log = logs.get(t["id"])
                status = log["status"] if log else "미착수"
                dd = due_date(t, today)
                dday = (dd - today).days
                tag = "" if c == "일" else f" · 기한 {dd.month}/{dd.day}" + (
                    f" (D{dday:+d})" if status not in ("완료", "해당없음") else ""
                )
                icon = {"미착수": "⬜", "진행": "🟨", "완료": "✅", "해당없음": "➖"}[status]
                with st.expander(f"{icon} [{t['dept']}] {t['title']}{tag}"):
                    cc1, cc2 = st.columns([1, 2])
                    new_status = cc1.selectbox("상태", STATUSES, index=STATUSES.index(status), key=f"s{c}{t['id']}")
                    memo = cc2.text_input("메모·증빙 위치", value=(log["memo"] if log else "") or "", key=f"m{c}{t['id']}")
                    if st.button("저장", key=f"b{c}{t['id']}"):
                        con.execute(
                            "INSERT OR REPLACE INTO logs VALUES(?,?,?,?,?)",
                            (int(t["id"]), pk, new_status, memo, date.today().isoformat()),
                        )
                        con.commit()
                        st.rerun()
                    st.markdown(f"**근거**: {t['basis'] or '-'}  \n**시스템**: {t['systems'] or '-'}")
                    st.markdown("**처리 절차**")
                    st.text(t["procedure"] or "-")
                    if t["notes"]:
                        st.markdown(f"**유의사항**: {t['notes']}")
                    snips = audit_snippets(t["keywords"])
                    if snips:
                        st.markdown("**⚖️ 관련 감사 지적사례**")
                        for kw, fn, snip in snips:
                            st.caption(f"[{kw}] {fn}")
                            st.markdown(f"> …{snip}…")

# ---------- 탭2: 업무 카드 관리 ----------
with tab_cards:
    st.subheader("표준 양식 불러오기")
    if TEMPLATE_CSV.exists():
        tpl = pd.read_csv(TEMPLATE_CSV).fillna("")
        st.caption(f"표준 업무 카드 {len(tpl)}건 (행정실·교무실). 불러온 뒤 학교 실정에 맞게 수정하세요.")
        if st.button("📥 표준 양식을 우리 학교에 추가"):
            existing = {(r["dept"], r["title"]) for _, r in tasks.iterrows()}
            n = 0
            for _, r in tpl.iterrows():
                if (r["부서"], r["업무명"]) in existing:
                    continue
                con.execute(
                    "INSERT INTO tasks(school,dept,role,title,cycle,months,due_day,basis,procedure,systems,keywords,notes) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (school, r["부서"], r["부서"], r["업무명"], r["주기"], str(r["시기(월)"]),
                     int(r["기한(일)"] or 0), r["근거"], r["처리절차"], r["사용시스템"], r["감사키워드"], ""),
                )
                n += 1
            con.commit()
            st.success(f"{n}건 추가했습니다.")
            st.rerun()

    st.subheader("업무 카드 추가")
    with st.form("add_task", clear_on_submit=True):
        a, b, c_ = st.columns(3)
        dept = a.selectbox("부서", DEPTS)
        cycle = b.selectbox("주기", CYCLES)
        role = c_.text_input("담당 역할(직위)", placeholder="예: 회계담당, 시설담당, 교무기획")
        title = st.text_input("업무명")
        d1, d2 = st.columns(2)
        months = d1.text_input("시기(월) — 분기·년만", placeholder="분기: 3,6,9,12 / 년: 3")
        due_day = d2.number_input("기한(일) — 0이면 말일", 0, 31, 0)
        basis = st.text_input("근거 법령·지침")
        procedure = st.text_area("처리 절차")
        systems = st.text_input("사용 시스템")
        keywords = st.text_input("감사 키워드(쉼표 구분)", placeholder="수의계약, 여비")
        notes = st.text_area("유의사항")
        if st.form_submit_button("추가") and title.strip():
            con.execute(
                "INSERT INTO tasks(school,dept,role,title,cycle,months,due_day,basis,procedure,systems,keywords,notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (school, dept, role or dept, title, cycle, months, int(due_day), basis, procedure, systems, keywords, notes),
            )
            con.commit()
            st.success("추가했습니다.")
            st.rerun()

    st.subheader("등록된 카드")
    if not tasks.empty:
        view = tasks[["id", "dept", "role", "title", "cycle", "months", "due_day", "keywords"]]
        view.columns = ["ID", "부서", "역할", "업무명", "주기", "시기(월)", "기한(일)", "감사키워드"]
        st.dataframe(view, width="stretch", hide_index=True)
        del_id = st.number_input("삭제할 카드 ID", 0, step=1)
        if st.button("🗑️ 삭제") and del_id:
            con.execute("DELETE FROM tasks WHERE id=? AND school=?", (int(del_id), school))
            con.commit()
            st.rerun()

# ---------- 탭3: 인수인계서 ----------
def build_handover(role_sel, from_name, to_name):
    rows = tasks if role_sel == "전체" else tasks[tasks["role"] == role_sel]
    L = [f"# {school} 업무 인수인계서", "",
         f"- 작성일: {date.today().isoformat()}",
         f"- 인계자: {from_name or '(미입력)'} / 인수자: {to_name or '(미입력)'}",
         f"- 대상: {role_sel}", ""]
    for c in CYCLES:
        sub = rows[rows["cycle"] == c]
        L.append(f"## {c}별 업무 ({len(sub)}건)")
        if sub.empty:
            L += ["(없음)", ""]
            continue
        for _, t in sub.iterrows():
            when = ""
            if c in ("분기", "년"):
                when = f" — {t['months']}월"
            if c != "일":
                when += f" {'말일' if not t['due_day'] else str(t['due_day']) + '일'}까지"
            L += [f"### [{t['dept']}] {t['title']}{when}",
                  f"- 담당 역할: {t['role']}", f"- 근거: {t['basis'] or '-'}",
                  f"- 시스템: {t['systems'] or '-'}", f"- 절차: {t['procedure'] or '-'}"]
            if t["notes"]:
                L.append(f"- 유의사항: {t['notes']}")
            if t["keywords"]:
                L.append(f"- 감사 주의 키워드: {t['keywords']}")
            L.append("")
    pend = con.execute(
        "SELECT t.title, l.period, l.status, l.memo FROM logs l JOIN tasks t ON t.id=l.task_id "
        "WHERE t.school=? AND l.status IN ('미착수','진행') ORDER BY l.period DESC", (school,)).fetchall()
    L.append(f"## 미결·진행 중 업무 ({len(pend)}건)")
    L += [f"- {p['title']} ({p['period']}, {p['status']}) {p['memo'] or ''}" for p in pend] or ["(없음)"]
    return "\n".join(L)


# ---------- PDF ----------
FONT_CANDIDATES = [
    (BASE / "fonts" / "NanumGothic.ttf", None),
    (Path("C:/Windows/Fonts/malgun.ttf"), None),
    (Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"), 0),
    (Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"), None),
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 0),
    (Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"), 0),
]


def register_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path, idx in FONT_CANDIDATES:
        if path.exists():
            kw = {"subfontIndex": idx} if idx is not None else {}
            pdfmetrics.registerFont(TTFont("KR", str(path), **kw))
            return "KR"
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))  # 폰트 미내장(뷰어 의존)
    return "HYSMyeongJo-Medium"


def doc_status(doc):
    if doc and doc["signed_from_at"] and doc["signed_to_at"]:
        return "서명 완료"
    if doc and doc["signed_from_at"]:
        return "인수자 서명 대기"
    return "인계자 서명 대기"


def build_pdf(doc):
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    f = register_font()
    st_ = {
        "h1": ParagraphStyle("h1", fontName=f, fontSize=18, leading=24, spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName=f, fontSize=13, leading=18, spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("h3", fontName=f, fontSize=10.5, leading=15, spaceBefore=6),
        "li": ParagraphStyle("li", fontName=f, fontSize=9, leading=13, leftIndent=10),
        "p": ParagraphStyle("p", fontName=f, fontSize=9, leading=13),
    }
    flow = []
    for line in doc["content"].split("\n"):
        if not line.strip():
            flow.append(Spacer(1, 3))
        elif line.startswith("### "):
            flow.append(Paragraph(escape(line[4:]), st_["h3"]))
        elif line.startswith("## "):
            flow.append(Paragraph(escape(line[3:]), st_["h2"]))
        elif line.startswith("# "):
            flow.append(Paragraph(escape(line[2:]), st_["h1"]))
        elif line.startswith("- "):
            flow.append(Paragraph("• " + escape(line[2:]), st_["li"]))
        else:
            flow.append(Paragraph(escape(line), st_["p"]))

    flow += [Spacer(1, 10), Paragraph("서명", st_["h2"])]
    def cell(name, at):
        return f"{name}\n" + (f"전자서명 {at}" if at else "서명 전")
    tbl = Table(
        [["구분", "성명", "서명 일시"],
         ["인계자", doc["from_name"], doc["signed_from_at"] or "서명 전"],
         ["인수자", doc["to_name"], doc["signed_to_at"] or "서명 전"]],
        colWidths=[30 * mm, 50 * mm, 80 * mm],
    )
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow += [tbl, Spacer(1, 6),
             Paragraph(f"상태: {doc_status(doc)} · 문서 무결성 코드(SHA-256): {doc['doc_hash'][:32]}…", st_["p"])]
    if not doc["signed_to_at"]:
        flow.append(Paragraph("※ 양측 서명 전의 초안입니다.", st_["p"]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=16 * mm, bottomMargin=16 * mm,
                      title=f"{school} 인수인계서").build(flow)
    return buf.getvalue()


with tab_handover:
    st.subheader("1. 인계서 작성·확정")
    if tasks.empty:
        st.info("먼저 업무 카드를 등록하세요.")
    else:
        roles = ["전체"] + sorted(tasks["role"].unique().tolist())
        r1, r2, r3 = st.columns(3)
        role_sel = r1.selectbox("인계 대상 역할", roles)
        from_name = r2.text_input("인계자 성명")
        to_name = r3.text_input("인수자 성명")
        md = build_handover(role_sel, from_name, to_name)
        with st.expander("미리보기"):
            st.markdown(md)
        st.caption("확정하면 현재 내용이 그대로 저장되고 수정할 수 없습니다. 내용을 바꾸려면 새로 확정하세요.")
        if st.button("📌 인계서 확정(저장)", disabled=not (from_name.strip() and to_name.strip())):
            h = hashlib.sha256(md.encode("utf-8")).hexdigest()
            con.execute(
                "INSERT INTO handover_docs(school,role,from_name,to_name,content,doc_hash,created) VALUES(?,?,?,?,?,?,?)",
                (school, role_sel, from_name.strip(), to_name.strip(), md, h, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            con.commit()
            st.success("확정했습니다. 아래에서 서명하세요.")
            st.rerun()

    st.subheader("2. 서명 및 PDF")
    docs = con.execute("SELECT * FROM handover_docs WHERE school=? ORDER BY id DESC", (school,)).fetchall()
    if not docs:
        st.caption("확정된 인계서가 없습니다.")
    for d in docs:
        with st.expander(f"#{d['id']} {d['role']} · {d['from_name']} → {d['to_name']} · {d['created']} · **{doc_status(d)}**"):
            if not d["signed_from_at"]:
                who, col, nm = "인계자", "signed_from_at", d["from_name"]
            elif not d["signed_to_at"]:
                who, col, nm = "인수자", "signed_to_at", d["to_name"]
            else:
                who = None
            if who:
                st.markdown(f"**{who} 서명** — 본인 성명 `{nm}`을(를) 그대로 입력하고 확인에 체크하세요.")
                typed = st.text_input("성명 입력", key=f"sg{d['id']}{col}")
                ok = st.checkbox("인계서 내용을 확인했으며 이에 서명합니다.", key=f"ck{d['id']}{col}")
                if st.button(f"✍️ {who} 서명", key=f"sb{d['id']}{col}", disabled=not (ok and typed.strip() == nm)):
                    con.execute(f"UPDATE handover_docs SET {col}=? WHERE id=?",
                                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), d["id"]))
                    con.commit()
                    st.rerun()
            else:
                st.success("양측 서명이 완료되었습니다.")
            try:
                st.download_button("⬇️ PDF 다운로드", build_pdf(d), file_name=f"{school}_인수인계서_{d['id']}.pdf",
                                   mime="application/pdf", key=f"pdf{d['id']}")
            except Exception as e:  # reportlab 미설치 등
                st.error(f"PDF 생성 실패: {e}")
            st.download_button("⬇️ 마크다운", d["content"].encode("utf-8"),
                               file_name=f"{school}_인수인계서_{d['id']}.md", key=f"md{d['id']}")
            st.caption(f"무결성 코드(SHA-256): {d['doc_hash']}")

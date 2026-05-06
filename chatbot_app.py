import streamlit as st
import json
import unicodedata
from datetime import datetime
from groq import Groq
import re
import os
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List

import time
# ═══════════════════════════════════════════════════════════════════════════════
# PRE-COMPILED REGEX & CONSTANTS (Performance boost)
# ═══════════════════════════════════════════════════════════════════════════════
import os
import streamlit as st

# Groq
os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]

# LangSmith


# ═══════════════════════════════════════════════════════════════════════════════


STUDENT_ID_REGEX = re.compile(r'\b(202\d{5,})\b')
GRADE_PATTERNS = []
SCHEDULE_PATTERNS = []
GRADE_KEYWORDS = [
        "درجة", "درجه", "نتيجة", "نتيجه", "علامة", "علامه", 
        "grade", "نمرة", "نمره", "درجات", "درجاتي"
    ]
SCHEDULE_KEYWORDS = [
        "جدول", "النهارده", "اليوم", "بكره", "بكرا", "غدا", "محاضرات", "محاضرة", 
        "سكشن", "موعد", "دكتور", "د.", "مادة", "درس", "حصة"
    ]
def init_patterns():
    """Pre-compile all regex patterns"""
    global GRADE_PATTERNS, SCHEDULE_PATTERNS
    
    
    GRADE_PATTERNS = [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in GRADE_KEYWORDS]
    SCHEDULE_PATTERNS = [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in SCHEDULE_KEYWORDS]

init_patterns()

DAY_AR = {0:"الاثنين",1:"الثلاثاء",2:"الاربعاء",3:"الخميس",4:"الجمعة",5:"السبت",6:"الاحد"}
TIME_ORDER = {"الاولى":1,"الأولى":1,"الثانية":2,"الثالثة":3,"الرابعة":4,"الخامسة":5}

# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS (Cached & Optimized)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data
def load_json_file(filename: str) -> List[Dict[str, Any]]:
    """Unified JSON loader with multiple path fallback"""
    paths = [
        filename,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        os.path.join(os.getcwd(), filename),
    ]
    for path in paths:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return json.load(f)
    return []

@st.cache_data
def load_schedule() -> List[Dict[str, Any]]:
    return load_json_file("output.json")

@st.cache_data
def load_grades() -> Dict[str, Dict[str, Any]]:
    data = load_json_file("grades.json")
    return {str(item.get("id", "")).strip(): item for item in data if item.get("id")}

@st.cache_data
def load_rl() -> Dict[str, Dict[str, Any]]:
    data = load_json_file("rl.json")
    return {str(item.get("id", "")).strip(): item for item in data if item.get("id")}

# ═══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def fix(text: Optional[str]) -> str:
    return unicodedata.normalize('NFKC', str(text or "")).strip()

def norm(text: Optional[str]) -> str:
    if not text:
        return ""
    text = fix(text)
    replacements = {'ة':'ه','أ':'ا','إ':'ا','آ':'ا','ى':'ي','ئ':'ي','ؤ':'و'}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.strip()

def sort_time(t: str) -> int:
    for k, v in TIME_ORDER.items():
        if k in t: 
            return v
    return 99

def today_ar() -> str:
    return DAY_AR.get(datetime.now().weekday(), "")

def tomorrow_ar() -> str:
    return DAY_AR.get((datetime.now().weekday() + 1) % 7, "")

# ═══════════════════════════════════════════════════════════════════════════════
# DATA PROCESSORS
# ═══════════════════════════════════════════════════════════════════════════════

def get_records(data: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Process raw schedule data into flat records"""
    records = []
    for student in data:
        sid = fix(student.get("student_id"))
        name = fix(student.get("name"))
        program = fix(student.get("program"))
        
        for course in student.get("courses", []):
            records.append({
                "id": sid, "name": name, "program": program,
                "course": fix(course.get("course_name")),
                "type": fix(course.get("type")),
                "day": fix(course.get("day")),
                "time": fix(course.get("time")),
                "group": fix(course.get("section")),
                "room": fix(course.get("room")),
                "doctor": fix(course.get("instructor")),
            })
    return records

# ═══════════════════════════════════════════════════════════════════════════════
# GRADE HANDLER (Production-ready)
# ═══════════════════════════════════════════════════════════════════════════════

def get_grade(sid: str, grades: Dict[str, Dict], rl: Dict[str, Dict]) -> Optional[float]:
    """Safe grade extraction with validation"""
    if not sid or len(sid) < 8:
        return None
    
    # RL first (priority)
    if sid in rl:
        grade_str = rl[sid].get("grade")
        if grade_str is not None:
            try:
                return float(grade_str)
            except (ValueError, TypeError):
                pass
    
    # NLP fallback
    if sid in grades:
        grade_str = grades[sid].get("grade")
        if grade_str is not None:
            try:
                return float(grade_str)
            except (ValueError, TypeError):
                pass
    
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def search_by_student(records: List[Dict], sid: str) -> List[Dict]:
    return [r for r in records if r["id"] == sid]

def search_by_doctor(records: List[Dict], doctor_name: str) -> List[Dict]:
    q = norm(doctor_name)
    return [r for r in records if q in norm(r["doctor"])]

def search_by_course(records: List[Dict], course_name: str) -> List[Dict]:
    q = norm(course_name)
    return [r for r in records if q in norm(r["course"])]

# ═══════════════════════════════════════════════════════════════════════════════
# QUERY PARSERS (Pre-compiled)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_student_id(text: str) -> Optional[str]:
    match = STUDENT_ID_REGEX.search(text)
    return match.group(1) if match else None

def get_last_student_id(messages: List[Dict]) -> Optional[str]:
    for msg in reversed(messages):
        sid = extract_student_id(msg["content"])
        if sid: 
            return sid
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_day_schedule(rows: List[Dict], day: str) -> str:
    filtered = [r for r in rows if norm(day) in norm(r["day"])]
    filtered.sort(key=lambda x: sort_time(x["time"]))
    
    if not filtered:
        return f"❌ لا توجد محاضرات يوم {day}"
    
    lines = [f"📅 جدول يوم {day}:"]
    for r in filtered:
        t = "محاضرة" if r["type"] == "Lecture" else "سكشن"
        doc = f"\n    👨‍🏫 {r['doctor']}" if r['doctor'] else ""
        lines.append(f"• ⏰ {r['time']}\n  📚 {r['course']} ({t}) | 🏛️ {r['room']}{doc}")
    return "\n".join(lines)

def format_full_schedule(rows: List[Dict], name: str, sid: str) -> str:
    lines = [f"👤 {name} | 🆔 {sid}\n📚 {rows[0]['program']}\n"]
    days = ["السبت","الاحد","الاثنين","الثلاثاء","الاربعاء","الخميس"]
    
    for day in days:
        day_rows = [r for r in rows if norm(r["day"]) == norm(day)]
        if day_rows:
            day_rows.sort(key=lambda x: sort_time(x["time"]))
            lines.append(f"📅 {day}:")
            for r in day_rows:
                tp = "محاضرة" if "lecture" in r["type"].lower() else "سكشن"
                doc = f" | {r['doctor']}" if r["doctor"] else ""
                lines.append(f"  • {r['time']} — {r['course']} ({tp}) | {r['room']}{doc}")
    return "\n".join(lines)

def format_doctor_schedule(rows: List[Dict]) -> str:
    if not rows:
        return "❌ لم أجد هذا الدكتور في الجدول."
    
    doctor_name = rows[0]["doctor"]
    lines = [f"📋 جدول {doctor_name}:"]
    by_day = {}
    
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    
    days = ["السبت","الاحد","الاثنين","الثلاثاء","الاربعاء","الخميس"]
    for day in days:
        if day in by_day:
            lines.append(f"\n📅 {day}:")
            for r in sorted(by_day[day], key=lambda x: sort_time(x["time"])):
                t = "محاضرة" if "lecture" in r["type"].lower() else "سكشن"
                lines.append(f"  • ⏰ {r['time']} — {r['course']} ({t}) | 🏛️ {r['room']}")
    return "\n".join(lines)

def format_course_info(rows: List[Dict], course_name: str) -> str:
    if not rows:
        return f"❌ لم أجد مادة '{course_name}' في الجدول."
    
    lines = [f"📚 معلومات مادة {rows[0]['course']}:"]
    seen = set()
    
    for r in rows:
        key = (r["day"], r["time"], r["type"], r["doctor"])
        if key in seen: 
            continue
        seen.add(key)
        t = "محاضرة" if "lecture" in r["type"].lower() else "سكشن"
        doc = f" | 👨‍🏫 {r['doctor']}" if r["doctor"] else ""
        lines.append(f"• 📅 {r['day']} ⏰ {r['time']} ({t}) | 🏛️ {r['room']}{doc}")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════════════════════
# INTELLIGENT CLASSIFIERS (Advanced NLP)
# ═══════════════════════════════════════════════════════════════════════════════

def is_grade_question(text: str) -> bool:
    """Advanced word-boundary + fuzzy matching"""
    t_norm = norm(text)
    
    # Exact regex match (fast)
    if any(pattern.search(t_norm) for pattern in GRADE_PATTERNS):
        return True
    
    # Fuzzy fallback for typos (10% slower, but catches "درجتي")
    return fuzzy_match(t_norm, GRADE_KEYWORDS, 0.75)

def is_schedule_question(text: str, messages: List[Dict]) -> bool:
    """Schedule detection with context"""
    t_norm = norm(text)
    
    # Exact keywords
    if any(pattern.search(t_norm) for pattern in SCHEDULE_PATTERNS):
        return True
    
    # Student ID alone = schedule
    if STUDENT_ID_REGEX.search(text):
        return True
    
    # Context: previous student + schedule words
    if get_last_student_id(messages):
        schedule_context = [norm("بكره"), norm("اليوم"), norm("النهارده"), norm("محاضرات"), norm("جدول")]
        return any(ctx in t_norm for ctx in schedule_context)
    
    return False

def fuzzy_match(text: str, keywords: List[str], threshold: float = 0.7) -> bool:
    """Fuzzy matching for typos/misspellings"""
    for kw in keywords:
        if SequenceMatcher(None, text, norm(kw)).ratio() > threshold:
            return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULE QUERY HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

def handle_schedule_query(text: str, records: List[Dict], messages: List[Dict]) -> Optional[str]:
    """Unified schedule query handler"""
    t_norm = norm(text)
    sid = extract_student_id(text) or get_last_student_id(messages)

    # Student schedule (priority)
    if sid:
        rows = search_by_student(records, sid)
        if not rows:
            return f"❌ الرقم الأكاديمي {sid} غير موجود في الجدول."
        
        name = rows[0]["name"]
        
        # Tomorrow
        tomorrow_words = [norm("بكره"), norm("بكرا"), norm("غدا"), norm("غداً")]
        if any(w in t_norm for w in tomorrow_words):
            return f"👤 {name}\n\n" + format_day_schedule(rows, tomorrow_ar())
        
        # Specific day
        for day_ar in DAY_AR.values():
            if norm(day_ar) in t_norm:
                return f"👤 {name}\n\n" + format_day_schedule(rows, day_ar)
        
        # Today
        today_words = [norm("النهارده"), norm("اليوم"), norm("دلوقتي"), norm("محاضرات")]
        if any(w in t_norm for w in today_words):
            return f"👤 {name}\n\n" + format_day_schedule(rows, today_ar())
        
        # Full schedule
        return format_full_schedule(rows, name, sid)

    # Doctor schedule
    doc_match = re.search(r'(?:دكتور[ه]?|د\.?)\s+([\w\s]+)', text)
    if doc_match:
        doc_name = doc_match.group(1).strip().split()[0]
        rows = search_by_doctor(records, doc_name)
        if rows:
            return format_doctor_schedule(rows)

    # Course info
    course_match = re.search(r'(?:ماد[ةه]|مادة|درس)\s+([\w\s]+)', text)
    if course_match:
        course_name = course_match.group(1).strip()
        rows = search_by_course(records, course_name)
        if rows:
            return format_course_info(rows, course_name)

    return None

# ═══════════════════════════════════════════════════════════════════════════════
# AI FALLBACK
# ═══════════════════════════════════════════════════════════════════════════════


def ask_groq(messages: List[Dict]) -> str:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    recent_messages = messages[-10:]
    
    groq_msgs = [{
        "role": "system", 
        "content": "أنت مساعد جامعي ذكي. رد باختصار ووضوح بالعربية الفصحى. لا تكتب كود."
    }] + [{"role": m["role"], "content": m["content"]} for m in recent_messages]
    
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=groq_msgs,
                max_tokens=512,
                temperature=0.1
            )
            return response.choices[0].message.content

        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                # استخرج الوقت من الـ error message
                wait = 10  # default
                import re
                match = re.search(r'try again in (\d+\.?\d*)s', err, re.IGNORECASE)
                if match:
                    wait = float(match.group(1)) + 1
                
                st.warning(f"الخدمة مشغولة، هنحاول تاني بعد {int(wait)} ثانية...")
                time.sleep(wait)
            else:
                return f"عذراً، حدث خطأ: {err}"
    
    return "عذراً، الخدمة مشغولة دلوقتي. جرب تاني بعد شوية."
# ═══════════════════════════════════════════════════════════════════════════════
# PRODUCTION STREAMLIT APP
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="🎓 مساعد الجدول الدراسي", 
        page_icon="🎓", 
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Beautiful CSS
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap');

* {
    font-family: 'Cairo', sans-serif !important;
}

.stApp {
    background: linear-gradient(135deg, #0f172a, #1e293b);
}

/* العنوان */
.main-title {
    text-align:center;
    font-size:2.5rem;
    font-weight:900;
    color:#facc15;
    margin-top:1rem;
}

.subtitle {
    text-align:center;
    color:#cbd5e1;
    margin-bottom:1rem;
}

/* الرسائل */
.user-msg {
    background: #3b82f6;
    color: white;
    padding: 12px 16px;
    border-radius: 18px 18px 0 18px;
    margin: 8px 0;
    max-width: 70%;
    margin-left: auto;
}

.bot-msg {
    background: rgba(255,255,255,0.08);
    color: white;
    padding: 12px 16px;
    border-radius: 18px 18px 18px 0;
    margin: 8px 0;
    max-width: 70%;
    border: 1px solid rgba(255,255,255,0.1);
}

.grade-display {
    font-size: 3rem;
    text-align:center;
    color:#22c55e;
    font-weight:900;
}

</style>
""", unsafe_allow_html=True)
    # Header
    st.markdown('<div class="main-title">🎓 مساعد الجدول الدراسي</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">كلية الحاسوب والذكاء الاصطناعي — جامعة المنوفية الأهلية</div>', unsafe_allow_html=True)

    # Load all data
    raw_data = load_schedule()
    records = get_records(raw_data)
    grades = load_grades()
    rl_data = load_rl()

    # Status metrics
    if not records:
        st.error(f"❌ ملف output.json غير موجود!\nالمجلد الحالي: {os.getcwd()}")
        st.stop()

    # Chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [{
            "role": "assistant", 
            "content": f"""🎉 **مرحباً بك!** أنا مساعدك الجامعي الذكي 🤖

**اليوم:** {today_ar().upper()}
**الأوامر السريعة:**

**جرب الآن!** 💬"""
        }]

    # Render messages
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.markdown(f"<div class='user-msg'>{msg['content']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='bot-msg'>{msg['content']}</div>", unsafe_allow_html=True)
            # Chat input
    if prompt := st.chat_input("💭 اكتب سؤالك هنا...", key="chat_input"):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("🔍 جاري البحث الذكي..."):
                # Extract student ID
                sid = extract_student_id(prompt)
                if not sid:
                    sid = get_last_student_id(st.session_state.messages)
                
                # PERFECT PRIORITY FLOW
                response = None
                
                # 1️⃣ GRADE (highest priority)
                if is_grade_question(prompt) and sid:
                    grade = get_grade(sid, grades, rl_data)
                    if grade is None:
                        response = "❌ لا توجد درجة مسجلة"
                    else:
                        response = f'<div class="grade-display">{grade}/20</div>'
                
                # 2️⃣ SCHEDULE
                elif is_schedule_question(prompt, st.session_state.messages) and records:
                    response = handle_schedule_query(prompt, records, st.session_state.messages)
                    if not response:
                        response = "❓ ما فهمتش السؤال عن الجدول، جرب:\n• رقمك الأكاديمي\n• اسم دكتور\n• اسم مادة"
                
                # 3️⃣ AI FALLBACK
                else:
                    response = ask_groq(st.session_state.messages)
                
                st.markdown(response, unsafe_allow_html=True)
                st.session_state.messages.append({"role": "assistant", "content": response})

if __name__ == "__main__":
    main()

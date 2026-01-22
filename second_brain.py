import streamlit as st
import sqlite3
import google.generativeai as genai
import os
from datetime import datetime
import pandas as pd
from tavily import TavilyClient
import requests

# ==========================================
# 🔐 安全门禁 (Password Check)
# ==========================================
def check_password():
    """如果不输入正确密码，程序直接停止运行"""
    # 1. 如果是本地运行 (没有 secrets)，为了方便调试，默认不开启密码
    if "APP_PASSWORD" not in st.secrets:
        return True

    # 2. 如果已经登录过，直接放行
    if "password_correct" in st.session_state and st.session_state["password_correct"]:
        return True

    # 3. 显示输入框
    st.markdown("## 🔒 Cortex 安全门禁")
    password_input = st.text_input("请输入访问密码", type="password")
    
    if st.button("解锁大脑"):
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun() # 密码正确，刷新页面进入
        else:
            st.error("🚫 密码错误，禁止访问")
    
    # 4. 只有返回 True 才会继续执行后面的代码，否则在这里就停住了
    return False

# 执行检查：如果没通过，直接停止整个 App 的运行
if not check_password():
    st.stop()

# ==========================================
# 0. 核心配置 (Smart Config)
# ==========================================
# ... (后面接原来的 LOCAL_GEMINI_KEY 等代码)
try:
    genai.configure(api_key=my_api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error(f"AI 配置错误: {e}")

DB_FILE = "second_brain.db"

# ==========================================
# 1. 数据库技能 (SQLite Skills)
# ==========================================

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            category TEXT,
            content TEXT,
            summary TEXT,
            tags TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_memory(category, content, summary, tags):
    conn = get_connection()
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO memories (created_at, category, content, summary, tags)
        VALUES (?, ?, ?, ?, ?)
    ''', (timestamp, category, content, summary, tags))
    conn.commit()
    conn.close()

def load_memories(limit=50):
    init_db()
    conn = get_connection()
    try:
        query = f"SELECT * FROM memories ORDER BY id DESC LIMIT {limit}"
        df = pd.read_sql_query(query, conn)
        return df
    except:
        return pd.DataFrame()
    finally:
        conn.close()

def delete_memory(mid):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM memories WHERE id = ?", (mid,))
    conn.commit()
    conn.close()

# ==========================================
# 2. 智能体技能 (Agent Skills)
# ==========================================

def analyze_logic(text):
    if not text: return "无内容", "未分类"
    prompt = f"""
    你是一位逻辑导师。请将用户输入重组为复习卡片。
    输入：{text}
    ----
    Markdown 输出格式：
    ### (给出一个简短的、不超过10个字的标题)
    
    (一句话总结核心观点，不超过50个字)
    
    ### 💡 核心概念
    (定义)
    ### 🔑 关键逻辑
    (要点)
    
    TAGS: 标签1, 标签2
    """
    try:
        response = model.generate_content(prompt)
        res = response.text.strip()
        if "TAGS:" in res:
            parts = res.split("TAGS:")
            return parts[0].strip(), parts[1].strip()
        return res, "AI未打标"
    except Exception as e:
        return f"AI 错误: {e}", "错误"

def deep_read_url(url):
    try:
        jina_url = f"https://r.jina.ai/{url}"
        # request 会自动跟随系统的环境变量(os.environ)，所以不需要额外改动
        response = requests.get(jina_url, timeout=20)
        if response.status_code == 200:
            return response.text
        else:
            return f"读取失败，状态码: {response.status_code}"
    except Exception as e:
        return f"深阅读连接错误: {e}"

def web_agent_report(query, mode="search"):
    raw_data = ""
    source_type = ""

    if mode == "search":
        try:
            # 使用动态获取的 key
            tavily = TavilyClient(api_key=tavily_key) 
            response = tavily.search(query=query, search_depth="advanced", max_results=5)
            raw_data = "\n".join([f"- {r['title']}: {r['content']} (来源: {r['url']})" for r in response.get('results', [])])
            source_type = "搜索引擎摘要"
            if not raw_data: return None, "未找到网络信息"
        except Exception as e:
            return None, f"搜索工具报错: {e}"

    elif mode == "url":
        st.info(f"正在深度爬取链接: {query} ...")
        raw_content = deep_read_url(query)
        raw_data = raw_content[:15000] 
        source_type = "网页深度全文"

    prompt = f"""
    你是一位资深研究员。用户提供了一份【{source_type}】。
    原始内容：{raw_data}
    ----
    请写一份深度简报：
    ### (这里写简报的标题)
    (这里写一句话的核心结论摘要)
    
    #### 1. 关键细节与数据
    #### 2. 洞察与启示
    
    TAGS: 深阅读, 情报
    """
    try:
        ai_res = model.generate_content(prompt)
        res_text = ai_res.text.strip()
        final_report = res_text
        final_tags = "深阅读"
        if "TAGS:" in res_text:
            parts = res_text.split("TAGS:")
            final_report = parts[0].strip()
            final_tags = parts[1].strip()
        return final_report, final_tags
    except Exception as e:
        return None, f"AI 生成报告失败: {e}"

def chat_with_brain(user_query):
    df = load_memories(limit=50)
    memory_context = ""
    if not df.empty:
        for _, row in df.iterrows():
            memory_context += f"[ID:{row['id']}] [{row['category']}] 摘要: {row['summary']}\n标签: {row['tags']}\n---\n"
    else:
        memory_context = "(数据库暂无记忆)"

    prompt = f"""
    【角色设定】你是用户的“第二大脑”兼“私人顾问”。
    【记忆库】{memory_context}
    【用户提问】"{user_query}"
    【回答原则】
    1. 记忆优先：必须引用 [ID:xx]。
    2. 顾问模式：基于记忆给建议；如果记忆里没有，调用通用知识并标注“⚠️ 基于通用知识”。
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"大脑短路了: {e}"

# ==========================================
# 3. 界面构建 (Product UI - Designer Edition)
# ==========================================

st.set_page_config(page_title="Cortex", layout="wide", page_icon="🧬")
init_db()

# CSS 样式注入
st.markdown("""
<style>
    html, body, [class*="css"] { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
    .title-gradient {
        background: -webkit-linear-gradient(45deg, #6a11cb, #2575fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: bold;
        font-size: 3em;
        padding-bottom: 10px;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px;
        border: 1px solid #f0f0f0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        background-color: white;
        padding: 15px;
    }
    @media (prefers-color-scheme: dark) {
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #262730;
            border: 1px solid #363945;
        }
    }
    div.stButton > button { border-radius: 8px; font-weight: 600; }
    section[data-testid="stSidebar"] { background-color: #f8f9fa; }
    @media (prefers-color-scheme: dark) {
        section[data-testid="stSidebar"] { background-color: #1a1c24; }
    }
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
        height: 240px; 
        overflow: hidden;
    }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧬 Cortex</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: grey;'>Sylvia's Second Brain</p>", unsafe_allow_html=True)
    st.markdown("---")
    st.info("📊 **记忆统计**\n\n已存储: " + str(len(load_memories(1000))) + " 条笔记")
    st.markdown("---")
    st.caption("1. 📝 深度录入 (Input)")
    st.caption("2. 🎨 记忆画廊 (Gallery)")
    st.caption("3. 🔧 数据管理 (Admin)")
    st.caption("4. 🌍 全网侦探 (Agent)")
    st.caption("5. 💬 智能顾问 (Chat)")

st.markdown('<div class="title-gradient">Cortex Intelligence</div>', unsafe_allow_html=True)
st.caption("v3.6 Cloud Edition | 你的外挂神经中枢")
st.markdown("")

# Tab 页面布局
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📝 录入", "🎨 画廊", "🔧 管理", "🌍 侦探", "💬 顾问"])

# Tab 1
with tab1:
    with st.container(border=True):
        st.subheader("💡 存入新想法")
        with st.form("input_form"):
            c1, c2 = st.columns([1, 3])
            cat = c1.selectbox("分类", ["核心知识", "灵感", "复盘", "代码", "AI 顾问", "情报调研"])
            use_ai = c2.checkbox("🪄 启用 AI 逻辑重组", value=True)
            txt = st.text_area("在此输入内容...", height=150)
            
            if st.form_submit_button("🚀 存入大脑"):
                sm, tg = txt, "手动"
                if use_ai and txt:
                    with st.spinner("AI 正在整理逻辑..."):
                        sm, tg = analyze_logic(txt)
                save_memory(cat, txt, sm, tg)
                st.balloons()
                st.success("记忆已固化！")
                st.rerun()

# Tab 2
with tab2:
    df = load_memories(limit=100) 
    if not df.empty:
        st.markdown(f"#### 📚 记忆库 ({len(df)})")
        cols = st.columns(3)
        for i, row in df.iterrows():
            with cols[i % 3]:
                with st.container(border=True):
                    cat_icon = "📝"
                    if row['category'] == "AI 顾问": cat_icon = "💡"
                    elif "情报" in row['category']: cat_icon = "🌍"
                    elif row['category'] == "代码": cat_icon = "💻"
                    elif row['category'] == "复盘": cat_icon = "🔄"
                    st.markdown(f"##### {cat_icon} {row['category']}")
                    short_summary = row['summary'].split('\n')[0][:35]
                    st.markdown(f"<span style='color:grey; font-size:0.9em'>{short_summary}...</span>", unsafe_allow_html=True)
                    st.caption(f"🏷 {row['tags'][:12]}...")
                    with st.popover("🔍 展开", use_container_width=True):
                        st.subheader(f"{cat_icon} {row['category']}")
                        st.markdown("---")
                        st.success("📝 **智能摘要**")
                        st.markdown(row['summary'])
                        st.info("📄 **原始数据**")
                        st.markdown(row['content'])

# Tab 3
with tab3:
    with st.container(border=True):
        st.subheader("🛠️ 数据维护")
        df_m = load_memories(limit=100)
        if not df_m.empty:
            st.dataframe(df_m[['id', 'category', 'tags', 'created_at']], use_container_width=True)
            c1, c2 = st.columns([3, 1])
            d_id = c1.number_input("输入要删除的 ID", min_value=0)
            if c2.button("🗑️ 销毁记忆", type="primary"):
                delete_memory(d_id)
                st.rerun()

# Tab 4
with tab4:
    with st.container(border=True):
        st.subheader("🌍 全网情报侦探")
        search_mode = st.radio("选择模式", ["🔍 关键词搜索", "📖 URL 深阅读"], horizontal=True)
        col_q, col_btn = st.columns([4, 1])
        if "关键词" in search_mode:
            query_input = col_q.text_input("输入话题", placeholder="例如：DeepSeek 核心技术")
            mode_code = "search"
        else:
            query_input = col_q.text_input("粘贴 URL", placeholder="https://...")
            mode_code = "url"
        run_search = col_btn.button("🚀 执行侦查")
        if "search_result" not in st.session_state:
            st.session_state.search_result = None
            st.session_state.search_tags = None
        if run_search and query_input:
            with st.spinner("🕵️‍♂️ 正在执行深层任务..."):
                report, tags = web_agent_report(query_input, mode=mode_code)
                if report:
                    st.session_state.search_result = report
                    st.session_state.search_tags = tags
                else:
                    st.error(tags)
        if st.session_state.search_result:
            st.markdown("---")
            st.markdown(st.session_state.search_result)
            if st.button("💾 归档情报"):
                save_memory("情报调研", f"源: {query_input}", st.session_state.search_result, st.session_state.search_tags)
                st.success("✅ 已归档！")
                st.session_state.search_result = None
                st.rerun()

# Tab 5
with tab5:
    st.subheader("💬 Cortex 顾问")
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "你好 Sylvia，我是 Cortex。基于你的记忆库，有什么我可以帮你的？"}]
    if "last_ai_response" not in st.session_state:
        st.session_state.last_ai_response = None
    if "last_user_query" not in st.session_state:
        st.session_state.last_user_query = ""
    for msg in st.session_state.messages:
        avatar = "🧬" if msg["role"] == "assistant" else "👤"
        st.chat_message(msg["role"], avatar=avatar).write(msg["content"])
    if user_input := st.chat_input("向大脑提问..."):
        st.session_state.messages.append({"role": "user", "content": user_input})
        st.chat_message("user", avatar="👤").write(user_input)
        st.session_state.last_user_query = user_input
        with st.chat_message("assistant", avatar="🧬"):
            with st.spinner("🧠 Cortex 正在思考..."):
                response = chat_with_brain(user_input)
                st.write(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.session_state.last_ai_response = response
                st.rerun()
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
        last_msg = st.session_state.messages[-1]["content"]
        if len(st.session_state.messages) > 1:
            col_save, _ = st.columns([1, 5])
            if col_save.button("📥 归档这条建议"):
                save_memory(category="AI 顾问", content=f"问题: {st.session_state.last_user_query}", summary=last_msg, tags="对话, 建议, 自动归档")
                st.success("✅ 已归档到 [AI 顾问] 分类！")

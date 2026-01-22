import streamlit as st
import sqlite3
import google.generativeai as genai
import os
from datetime import datetime
import pandas as pd
from tavily import TavilyClient
import requests

# ==========================================
# 0. 页面初始化 (必须在最前面)
# ==========================================
st.set_page_config(page_title="Cortex", layout="wide", page_icon="🧬")

# ==========================================
# 🔐 1. 安全门禁
# ==========================================
def check_password():
    """安全检查：云端需要密码，本地自动免密"""
    try:
        # 如果云端没有设置密码，或者本地没有 secrets 文件，直接放行
        if "APP_PASSWORD" not in st.secrets:
            return True 
    except Exception:
        # 本地环境直接放行
        return True

    # 如果已经解锁过
    if "password_correct" in st.session_state and st.session_state["password_correct"]:
        return True

    # 显示密码框
    st.markdown("## 🔒 Cortex 安全门禁")
    st.caption("云端访问保护中，请输入密码")
    password_input = st.text_input("访问密码", type="password")
    
    if st.button("解锁"):
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("🚫 密码错误")
    
    # 没解锁前停止运行
    return False

if not check_password():
    st.stop()

# ==========================================
# ⚙️ 2. 核心配置 (Smart Config)
# ==========================================

# ⚠️ [必须修改] 本地运行时的备用钥匙
LOCAL_GEMINI_KEY = ""  
LOCAL_TAVILY_KEY = ""
LOCAL_PROXY_PORT = "1082"

# 智能环境切换
try:
    my_api_key = st.secrets["GEMINI_KEY"]
    tavily_key = st.secrets["TAVILY_KEY"]
    print("☁️ 云端环境：已移除代理。")
except Exception:
    print(f"🖥️ 本地环境：启用代理 {LOCAL_PROXY_PORT}")
    my_api_key = LOCAL_GEMINI_KEY
    tavily_key = LOCAL_TAVILY_KEY
    # 本地挂代理
    os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{LOCAL_PROXY_PORT}"
    os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{LOCAL_PROXY_PORT}"

# 配置 AI
try:
    genai.configure(api_key=my_api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error(f"AI 配置错误: {e}")

DB_FILE = "second_brain.db"

# ==========================================
# 💾 3. 数据库技能 (含高级重排)
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

# ID 重排 (碎片整理)
def reorder_ids():
    conn = get_connection()
    # 1. 取出所有数据，按旧 ID 排序
    df = pd.read_sql_query("SELECT * FROM memories ORDER BY id ASC", conn)
    conn.close()
    
    if df.empty: return

    # 2. 彻底删表 (重置计数器)
    conn = get_connection()
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS memories")
    conn.commit()
    conn.close()
    init_db() # 重建空表

    # 3. 重新插入 (ID 会自动变成 1, 2, 3...)
    conn = get_connection()
    c = conn.cursor()
    for _, row in df.iterrows():
        c.execute('''
            INSERT INTO memories (created_at, category, content, summary, tags)
            VALUES (?, ?, ?, ?, ?)
        ''', (row['created_at'], row['category'], row['content'], row['summary'], row['tags']))
    conn.commit()
    conn.close()

# 格式化 (清空)
def reset_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS memories")
    conn.commit()
    conn.close()
    init_db()

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
# 🧠 4. 智能体技能
# ==========================================
def analyze_logic(text):
    if not text: return "无内容", "未分类"
    prompt = f"""
    你是一位逻辑导师。请将用户输入重组为复习卡片。
    输入：{text}
    ----
    Markdown 输出格式：
    ### (简短标题)
    (一句话总结)
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
        response = requests.get(jina_url, timeout=20)
        if response.status_code == 200:
            return response.text
        else:
            return f"读取失败: {response.status_code}"
    except Exception as e:
        return f"连接错误: {e}"

def web_agent_report(query, mode="search"):
    raw_data = ""
    source_type = ""
    if mode == "search":
        try:
            tavily = TavilyClient(api_key=tavily_key) 
            response = tavily.search(query=query, search_depth="advanced", max_results=5)
            raw_data = "\n".join([f"- {r['title']}: {r['content']} (来源: {r['url']})" for r in response.get('results', [])])
            source_type = "搜索引擎摘要"
            if not raw_data: return None, "未找到信息"
        except Exception as e:
            return None, f"搜索报错: {e}"
    elif mode == "url":
        st.info(f"正在深度爬取: {query}")
        raw_content = deep_read_url(query)
        raw_data = raw_content[:15000] 
        source_type = "网页深度全文"

    prompt = f"""
    你是一位研究员。用户提供了【{source_type}】。
    内容：{raw_data}
    ----
    请写深度简报：
    ### (标题)
    (结论摘要)
    #### 1. 关键细节
    #### 2. 洞察
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
        return None, f"AI 生成失败: {e}"

def chat_with_brain(user_query):
    df = load_memories(limit=50)
    memory_context = ""
    if not df.empty:
        for _, row in df.iterrows():
            memory_context += f"[ID:{row['id']}] [{row['category']}] 摘要: {row['summary']}\n标签: {row['tags']}\n---\n"
    else:
        memory_context = "(数据库暂无记忆)"

    prompt = f"""
    【角色】你的第二大脑顾问。
    【记忆】{memory_context}
    【提问】"{user_query}"
    【原则】1. 必须引用 [ID:xx]。 2. 无记忆可调用通用知识但需标注。
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"大脑短路: {e}"


# ==========================================
# 🎨 5. 界面构建
# ==========================================

init_db()

# CSS 样式注入 (已修复括号问题)
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
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
        height: 240px; 
        overflow: hidden;
    }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧬 Cortex</h1>", unsafe_allow_html=True)
    st.caption("v4.4 Final Golden Edition")
    st.markdown("---")
    st.info("📊 已存储: " + str(len(load_memories(1000))) + " 条笔记")
    st.markdown("---")
    st.caption("1. 📝 深度录入\n2. 🎨 记忆画廊\n3. 🔧 数据管理\n4. 🌍 全网侦探\n5. 💬 智能顾问")

st.markdown('<div class="title-gradient">Cortex Intelligence</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📝 录入", "🎨 画廊", "🔧 管理", "🌍 侦探", "💬 顾问"])

with tab1:
    with st.container(border=True):
        st.subheader("💡 存入新想法")
        # ⚠️ 已修复括号和参数
        with st.form("input_form", clear_on_submit=True):
            c1, c2 = st.columns([1, 3])
            cat = c1.selectbox("分类", ["核心知识", "灵感", "复盘", "代码", "AI 顾问", "情报调研"])
            use_ai = c2.checkbox("🪄 启用 AI 重组", value=True)
            txt = st.text_area("内容...", height=150)
            
            if st.form_submit_button("🚀 存入"):
                sm, tg = txt, "手动"
                if use_ai and txt:
                    with st.spinner("AI 处理中..."):
                        sm, tg = analyze_logic(txt)
                save_memory(cat, txt, sm, tg)
                st.success("已存入！")
                st.rerun()

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
                    st.markdown(f"##### {cat_icon} {row['category']}")
                    short_summary = row['summary'].split('\n')[0][:35]
                    st.markdown(f"<span style='color:grey; font-size:0.9em'>{short_summary}...</span>", unsafe_allow_html=True)
                    with st.popover("🔍 展开"):
                        st.subheader(f"{cat_icon} {row['category']}")
                        st.markdown(row['summary'])
                        st.markdown("---")
                        st.info("原始数据")
                        st.markdown(row['content'])

with tab3:
    with st.container(border=True):
        st.subheader("🛠️ 数据维护")
        
        df_m = load_memories(limit=100)
        if not df_m.empty:
            st.dataframe(df_m[['id', 'category', 'tags']], use_container_width=True)
            c1, c2 = st.columns([3, 1])
            d_id = c1.number_input("删除指定 ID", min_value=0)
            if c2.button("🗑️ 删除单条"):
                delete_memory(d_id)
                st.rerun()
        
        st.markdown("---")
        st.markdown("#### ⚙️ 高级操作")
        col_clean, col_reset = st.columns(2)
        
        with col_clean:
            st.info("重整不连续的 ID (如 1,3,5 -> 1,2,3)")
            if st.button("🔄 重整 ID 顺序"):
                reorder_ids()
                st.balloons()
                st.success("ID 已重排！")
                st.rerun()

        with col_reset:
            st.warning("危险：清空所有数据！")
            if st.button("🔥 格式化大脑"):
                reset_db()
                st.error("已清空！")
                st.rerun()

with tab4:
    with st.container(border=True):
        st.subheader("🌍 全网侦探")
        search_mode = st.radio("模式", ["🔍 搜关键词", "📖 读 URL"], horizontal=True)
        c_q, c_b = st.columns([4, 1])
        if "关键词" in search_mode:
            q_in = c_q.text_input("话题", placeholder="例如：DeepSeek")
            mode = "search"
        else:
            q_in = c_q.text_input("链接", placeholder="https://...")
            mode = "url"
        
        if c_b.button("🚀 执行"):
            with st.spinner("执行中..."):
                rep, tgs = web_agent_report(q_in, mode=mode)
                if rep:
                    st.session_state.res = rep
                    st.session_state.tags = tgs
                else:
                    st.error(tgs)
        
        if "res" in st.session_state and st.session_state.res:
            st.markdown("---")
            st.markdown(st.session_state.res)
            if st.button("💾 归档"):
                save_memory("情报调研", f"源: {q_in}", st.session_state.res, st.session_state.tags)
                st.success("已归档！")
                st.session_state.res = None
                st.rerun()

with tab5:
    st.subheader("💬 Cortex 顾问")
    if "msgs" not in st.session_state:
        st.session_state.msgs = [{"role": "assistant", "content": "你好，我是 Cortex。"}]
    
    for msg in st.session_state.msgs:
        avatar = "🧬" if msg["role"] == "assistant" else "👤"
        st.chat_message(msg["role"], avatar=avatar).write(msg["content"])
    
    if u_in := st.chat_input("提问..."):
        st.session_state.msgs.append({"role": "user", "content": u_in})
        st.chat_message("user", avatar="👤").write(u_in)
        st.session_state.last_u = u_in
        with st.chat_message("assistant", avatar="🧬"):
            with st.spinner("思考中..."):
                resp = chat_with_brain(u_in)
                st.write(resp)
                st.session_state.msgs.append({"role": "assistant", "content": resp})
                st.session_state.last_a = resp
                st.rerun()
    
    if st.session_state.msgs and st.session_state.msgs[-1]["role"] == "assistant" and len(st.session_state.msgs) > 1:
        if st.button("📥 归档建议"):
            save_memory("AI 顾问", f"问: {st.session_state.get('last_u','')}", st.session_state.msgs[-1]["content"], "对话")
            st.success("已归档")

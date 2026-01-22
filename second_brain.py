import streamlit as st
import sqlite3
import google.generativeai as genai
import os
from datetime import datetime
import pandas as pd
from tavily import TavilyClient
import requests

# ==========================================
# 0. 页面初始化
# ==========================================
st.set_page_config(page_title="Cortex", layout="wide", page_icon="🧬")

# ==========================================
# 🔐 1. 安全门禁
# ==========================================
def check_password():
    try:
        if "APP_PASSWORD" not in st.secrets:
            return True 
    except Exception:
        return True

    if "password_correct" in st.session_state and st.session_state["password_correct"]:
        return True

    st.markdown("## 🔒 Cortex 安全门禁")
    st.caption("云端访问保护中，请输入密码")
    password_input = st.text_input("访问密码", type="password")
    
    if st.button("解锁"):
        if password_input == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("🚫 密码错误")
    return False

if not check_password():
    st.stop()

# ==========================================
# ⚙️ 2. 核心配置
# ==========================================

# ⚠️ [必须修改] 本地运行时的备用钥匙
LOCAL_GEMINI_KEY = ""  
LOCAL_TAVILY_KEY = ""
LOCAL_PROXY_PORT = "1082"

try:
    my_api_key = st.secrets["GEMINI_KEY"]
    tavily_key = st.secrets["TAVILY_KEY"]
    print("☁️ 云端环境：已移除代理。")
except Exception:
    print(f"🖥️ 本地环境：启用代理 {LOCAL_PROXY_PORT}")
    my_api_key = LOCAL_GEMINI_KEY
    tavily_key = LOCAL_TAVILY_KEY
    os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{LOCAL_PROXY_PORT}"
    os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{LOCAL_PROXY_PORT}"

try:
    genai.configure(api_key=my_api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error(f"AI 配置错误: {e}")

DB_FILE = "second_brain.db"

# ==========================================
# 💾 3. 数据库技能 (含重排功能)
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

# 新增：ID 重排 (Re-order IDs)
def reorder_ids():
    # 1. 先把所有数据捞出来，按旧 ID 排序
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM memories ORDER BY id ASC", conn)
    conn.close()
    
    if df.empty:
        return

    # 2. 删表重建 (让 ID 计数器归零)
    conn = get_connection()
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS memories")
    conn.commit()
    conn.close()
    init_db() # 重建空表

    # 3. 把数据原样塞回去 (ID 会自动重新变成 1, 2, 3...)
    conn = get_connection()
    c = conn.cursor()
    for _, row in df.iterrows():
        c.execute('''
            INSERT INTO memories (created_at, category, content, summary, tags)
            VALUES (?, ?, ?, ?, ?)
        ''', (row['created_at'], row['category'], row['content'], row['summary'], row['tags']))
    conn.commit()
    conn.close()

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

with

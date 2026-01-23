import streamlit as st
import sqlite3
import google.generativeai as genai
import os
from datetime import datetime
import pandas as pd
from tavily import TavilyClient
import requests

# ==========================================
# 0. 页面初始化 (必须放在最第一行)
# ==========================================
st.set_page_config(page_title="Cortex", layout="wide", page_icon="🧬")

# ==========================================
# 🎨 UI 美化区 (变量分离法 - 绝对安全)
# ==========================================
# 我们把 CSS 关在这个变量里，Python 解析器就不会报错了
APP_STYLE = """
<style>
    /* 全局字体 */
    html, body, [class*="css"] { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
    
    /* 标题渐变特效 */
    .title-gradient {
        background: -webkit-linear-gradient(45deg, #6a11cb, #2575fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: bold;
        font-size: 3em;
        padding-bottom: 10px;
    }
    
    /* 卡片容器样式 */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 12px;
        border: 1px solid #f0f0f0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        background-color: white; 
        padding: 15px;
    }
    
    /* 深色模式适配 */
    @media (prefers-color-scheme: dark) {
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #262730; 
            border: 1px solid #363945;
        }
    }
    
    /* 按钮圆角 */
    div.stButton > button { border-radius: 8px; font-weight: 600; }
    
    /* 侧边栏微调 */
    section[data-testid="stSidebar"] {
        background-color: #f9f9f9;
    }
    @media (prefers-color-scheme: dark) {
        section[data-testid="stSidebar"] { background-color: #1e1e1e; }
    }
</style>
"""
st.markdown(APP_STYLE, unsafe_allow_html=True)

# ==========================================
# 🔐 1. 安全门禁
# ==========================================
def check_password():
    """云端强制密码，本地自动放行"""
    # 1. 检查是否在云端 (通过是否配置了 secrets)
    try:
        if "APP_PASSWORD" not in st.secrets:
            return True # 没设密码就放行
    except:
        return True # 本地报错说明没 secrets，放行

    # 2. 检查 Session 状态
    if "password_correct" in st.session_state and st.session_state["password_correct"]:
        return True

    # 3. 显示锁屏界面
    st.markdown("## 🔒 Cortex 安全门禁")
    pwd = st.text_input("请输入访问密码", type="password")
    
    if st.button("解锁"):
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("🚫 密码错误")
    return False

# 如果没通过检查，直接停止运行下面的代码
if not check_password():
    st.stop()

# ==========================================
# ⚙️ 2. 核心配置 (Smart Config)
# ==========================================

# 👇👇👇 [请在这里填入你的 Key] 👇👇👇
LOCAL_GEMINI_KEY = ""
LOCAL_TAVILY_KEY = ""
LOCAL_PROXY_PORT = "1082" 

# 自动判断环境
try:
    # 尝试读取云端 Secrets
    my_api_key = st.secrets["GEMINI_KEY"]
    tavily_key = st.secrets["TAVILY_KEY"]
except:
    # 读不到就用本地 Key，并挂代理
    my_api_key = LOCAL_GEMINI_KEY
    tavily_key = LOCAL_TAVILY_KEY
    os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{LOCAL_PROXY_PORT}"
    os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{LOCAL_PROXY_PORT}"

# 激活 AI
try:
    genai.configure(api_key=my_api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    st.error(f"AI 启动失败: {e}")

DB_FILE = "second_brain.db"

# ==========================================
# 💾 3. 数据库技能 (含重排 + 格式化)
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

# 🔥 核心功能：ID 重排 (解决 ID 不连续问题)
def reorder_ids():
    conn = get_connection()
    # 1. 捞出所有数据
    df = pd.read_sql_query("SELECT * FROM memories ORDER BY id ASC", conn)
    conn.close()
    
    if df.empty: return

    # 2. 炸掉旧表
    conn = get_connection()
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS memories")
    conn.commit()
    conn.close()
    
    # 3. 重建新表
    init_db()
    
    # 4. 填回数据 (ID 会自动变成 1, 2, 3...)
    conn = get_connection()
    c = conn.cursor()
    for _, row in df.iterrows():
        c.execute('INSERT INTO memories (created_at, category, content, summary, tags) VALUES (?, ?, ?, ?, ?)', 
                  (row['created_at'], row['category'], row['content'], row['summary'], row['tags']))
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

def save_memory(cat, con, summ, tgs):
    conn = get_connection()
    c = conn.cursor()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('INSERT INTO memories (created_at, category, content, summary, tags) VALUES (?, ?, ?, ?, ?)', 
              (ts, cat, con, summ, tgs))
    conn.commit()
    conn.close()

def load_memories(limit=50):
    init_db()
    conn = get_connection()
    try:
        return pd.read_sql_query(f"SELECT * FROM memories ORDER BY id DESC LIMIT {limit}", conn)
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
# 🧠 4. 智能体技能 (深阅读 + 搜索)
# ==========================================
def analyze_logic(text):
    if not text: return "无内容", "未分类"
    prompt = f"""
    你是一位逻辑导师。请将用户输入重组为复习卡片。
    输入：{text}
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
        res = model.generate_content(prompt).text.strip()
        if "TAGS:" in res:
            p = res.split("TAGS:")
            return p[0].strip(), p[1].strip()
        return res, "AI未打标"
    except:
        return text, "AI错误"

# 深阅读功能
def deep_read_url(url):
    try:
        jina_url = f"https://r.jina.ai/{url}"
        response = requests.get(jina_url, timeout=20)
        return response.text if response.status_code == 200 else "读取失败"
    except Exception as e:
        return f"连接错误: {e}"

def web_agent_report(query, mode="search"):
    if mode == "search":
        try:
            tavily = TavilyClient(api_key=tavily_key) 
            res = tavily.search(query=query, search_depth="advanced", max_results=5)
            raw = "\n".join([f"- {r['title']}: {r['content']} ({r['url']})" for r in res.get('results', [])])
            return raw, "搜索"
        except Exception as e:
            return None, str(e)
    elif mode == "url":
        # 调用 Jina 进行深阅读
        content = deep_read_url(query)
        return content[:10000], "深阅读" # 截取前1万字防止Token爆炸
    return None, "未知模式"

def chat_with_brain(query):
    df = load_memories(limit=50)
    ctx = ""
    if not df.empty:
        for _, row in df.iterrows():
            ctx += f"[ID:{row['id']}] {row['summary']}\n"
    
    prompt = f"角色：第二大脑顾问。\n记忆库：{ctx}\n用户：{query}\n原则：优先引用记忆库内容。"
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"思考失败: {e}"

# ==========================================
# 🎨 5. 界面构建 (Tab逻辑)
# ==========================================
init_db()

with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧬 Cortex</h1>", unsafe_allow_html=True)
    st.caption("v4.6 Reborn Edition")
    st.markdown("---")
    st.info(f"📊 已存储: {len(load_memories(1000))} 条笔记")
    st.markdown("---")
    st.caption("1. 📝 录入\n2. 🎨 画廊\n3. 🔧 管理\n4. 🌍 侦探\n5. 💬 顾问")

st.markdown('<div class="title-gradient">Cortex Intelligence</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📝 录入", "🎨 画廊", "🔧 管理", "🌍 侦探", "💬 顾问"])

with tab1:
    with st.container(border=True):
        st.subheader("💡 存入新想法")
        # ✅ 修正点：clear_on_submit 必须在括号内
        with st.form("input_form", clear_on_submit=True):
            c1, c2 = st.columns([1, 3])
            cat = c1.selectbox("分类", ["核心知识", "灵感", "复盘", "代码", "AI 顾问", "情报调研"])
            use_ai = c2.checkbox("🪄 AI 重组", value=True)
            txt = st.text_area("内容...", height=150)
            
            if st.form_submit_button("🚀 存入"):
                sm, tg = txt, "手动"
                if use_ai and txt:
                    with st.spinner("AI 正在重组..."):
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
                    st.markdown(f"##### 📝 {row['category']}")
                    # 摘要截断显示
                    summary_preview = row['summary'].split('\n')[0][:40]
                    st.caption(f"{summary_preview}...")
                    
                    with st.popover("🔍 查看详情"):
                        st.subheader(f"ID: {row['id']} | {row['category']}")
                        st.markdown(row['summary'])
                        st.divider()
                        st.text("原始数据:")
                        st.code(row['content'])

with tab3:
    with st.container(border=True):
        st.subheader("🛠️ 数据维护")
        
        # 删除区
        df_m = load_memories(100)
        if not df_m.empty:
            st.dataframe(df_m[['id', 'category', 'tags']], use_container_width=True)
            c1, c2 = st.columns([3, 1])
            d_id = c1.number_input("输入要删除的 ID", min_value=0)
            if c2.button("🗑️ 删除"):
                delete_memory(d_id)
                st.success(f"ID {d_id} 已删除")
                st.rerun()
        
        st.markdown("---")
        st.markdown("#### ⚙️ 高级操作")
        col_clean, col_reset = st.columns(2)
        
        # ID 重排区
        with col_clean:
            st.info("笔记 ID 乱了？点击整理 (如 1,3,5 -> 1,2,3)")
            if st.button("🔄 重整 ID 顺序"):
                with st.spinner("正在整理数据库..."):
                    reorder_ids()
                st.balloons()
                st.success("整理完成！")
                st.rerun()

        # 格式化区
        with col_reset:
            st.warning("⚠️ 危险：清空所有数据！")
            if st.button("🔥 格式化大脑"):
                reset_db()
                st.error("已清空所有数据")
                st.rerun()

with tab4:
    with st.container(border=True):
        st.subheader("🌍 全网侦探")
        mode = st.radio("模式", ["🔍 搜关键词", "📖 读 URL (深阅读)"], horizontal=True)
        
        c_q, c_b = st.columns([4, 1])
        if "关键词" in mode:
            q_in = c_q.text_input("输入话题", placeholder="例如：DeepSeek 深度解析")
            s_type = "search"
        else:
            q_in = c_q.text_input("输入文章链接", placeholder="https://...")
            s_type = "url"
            
        if c_b.button("🚀 执行"):
            with st.spinner("侦探行动中..."):
                res, tag = web_agent_report(q_in, s_type)
                if res:
                    st.session_state.res = res
                    st.session_state.tags = tag
                else:
                    st.error("未获取到内容")

        if "res" in st.session_state and st.session_state.res:
            st.markdown("---")
            with st.expander("📄 阅读报告", expanded=True):
                st.markdown(st.session_state.res)
            
            if st.button("💾 归档这份情报"):
                save_memory("情报调研", f"源: {q_in}", st.session_state.res, st.session_state.tags)
                st.success("已归档！")

with tab5:
    st.subheader("💬 Cortex 顾问")
    # 初始化对话
    if "msgs" not in st.session_state:
        st.session_state.msgs = [{"role": "assistant", "content": "我是你的第二大脑，有什么可以帮你？"}]
    
    # 渲染历史
    for msg in st.session_state.msgs:
        avatar = "🧬" if msg["role"] == "assistant" else "👤"
        st.chat_message(msg["role"], avatar=avatar).write(msg["content"])
    
    # 输入与回复
    if u_in := st.chat_input("问问大脑..."):
        st.session_state.msgs.append({"role": "user", "content": u_in})
        st.chat_message("user", avatar="👤").write(u_in)
        
        with st.chat_message("assistant", avatar="🧬"):
            with st.spinner("检索记忆中..."):
                resp = chat_with_brain(u_in)
                st.write(resp)
                st.session_state.msgs.append({"role": "assistant", "content": resp})

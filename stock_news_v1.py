import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from openai import OpenAI  
import requests
import feedparser
import urllib.parse
from datetime import datetime, timedelta
import json
import os
import time

# --- 歷史紀錄快取系統 ---
HISTORY_FILE = "alpha_focus_history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history_data):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=4)

history = load_history()

# --- 核心引擎：Finnhub 基礎抓取 ---
def get_finnhub_news(ticker, api_key, limit=4):
    ticker_fh = ticker
    if str(ticker).isdigit() and len(str(ticker)) == 5:
        ticker_fh = f"{str(ticker)[1:]}.HK"
        
    to_date = datetime.now().strftime('%Y-%m-%d')
    from_date = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
    url = f"https://finnhub.io/api/v1/company-news?symbol={ticker_fh}&from={from_date}&to={to_date}&token={api_key}"
    
    try:
        res = requests.get(url, timeout=5).json()
        if isinstance(res, list) and len(res) > 0:
            news_list = []
            for item in res[:limit]:
                title = item.get('headline', '')
                summary = item.get('summary', '')[:80]
                if title:
                    news_list.append(f"【{title}】 {summary}...")
            return news_list
    except:
        return []
    return []

# --- 🌟 超級引擎：三源新聞聚合器 ---
def get_triple_engine_news(ticker, fh_api_key, fh_limit=4, g_limit=3, y_limit=2):
    news_pool = []
    fh_news = get_finnhub_news(ticker, fh_api_key, limit=fh_limit)
    for n in fh_news: news_pool.append(f"[Finnhub 機構] {n}")
        
    try:
        query = urllib.parse.quote(f"{ticker} stock news")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en")
        for entry in feed.entries[:g_limit]: news_pool.append(f"[Google 財經] {entry.title}")
    except: pass
        
    try:
        yf_ticker = ticker if not (str(ticker).isdigit() and len(str(ticker)) == 5) else f"{str(ticker)[1:]}.HK"
        y_info = yf.Ticker(yf_ticker)
        for n in y_info.news[:y_limit]:
            title = n.get('title') or n.get('headline') or ''
            if title: news_pool.append(f"[Yahoo 快訊] {title}")
    except: pass
        
    return news_pool

# --- IBD RS Rating 計算邏輯 ---
@st.cache_data(ttl=3600)
def get_macro_benchmark():
    spy = yf.download("SPY", period="1y", interval="1d", progress=False)
    vix = yf.download("^VIX", period="1mo", interval="1d", progress=False)
    
    spy_close = spy['Close'].squeeze() if not spy.empty else None
    if isinstance(spy_close, pd.DataFrame): spy_close = spy_close.iloc[:, 0]
    
    vix_close = vix['Close'].squeeze() if not vix.empty else None
    if isinstance(vix_close, pd.DataFrame): vix_close = vix_close.iloc[:, 0]
    
    return spy_close, vix_close

def calculate_rs_rating(stock_close, spy_close):
    if stock_close is None or spy_close is None or len(stock_close) < 10 or len(spy_close) < 10: return 50
    n63, n126, n189, n252 = min(63, len(stock_close)-1, len(spy_close)-1), min(126, len(stock_close)-1, len(spy_close)-1), min(189, len(stock_close)-1, len(spy_close)-1), min(252, len(stock_close)-1, len(spy_close)-1)

    rs_stock = 0.4 * (stock_close.iloc[-1] / stock_close.iloc[-1 - n63]) + 0.2 * (stock_close.iloc[-1] / stock_close.iloc[-1 - n126]) + 0.2 * (stock_close.iloc[-1] / stock_close.iloc[-1 - n189]) + 0.2 * (stock_close.iloc[-1] / stock_close.iloc[-1 - n252])
    rs_ref = 0.4 * (spy_close.iloc[-1] / spy_close.iloc[-1 - n63]) + 0.2 * (spy_close.iloc[-1] / spy_close.iloc[-1 - n126]) + 0.2 * (spy_close.iloc[-1] / spy_close.iloc[-1 - n189]) + 0.2 * (spy_close.iloc[-1] / spy_close.iloc[-1 - n252])

    if rs_ref == 0: return 50
    score = (rs_stock / rs_ref) * 100
    first, scnd, thrd, frth, ffth, sxth, svth = 195.93, 117.11, 99.04, 91.66, 80.96, 53.64, 24.86

    def f_att(s, tP, sP, rU, rD, w):
        sum_val = min(s + (s - sP) * w, tP - 1)
        denom = (sP / rD) - (((sP / rD) - ((tP - 1) / rU)) / (tP - 1 - sP) if (tP - 1 - sP) != 0 else 0) * (s - sP)
        return max(min(sum_val / denom if denom != 0 else rD, rU), rD)

    if score >= first: return 99
    if score <= svth: return 1
    if scnd <= score < first: return f_att(score, first, scnd, 98, 90, 0.33)
    elif thrd <= score < scnd: return f_att(score, scnd, thrd, 89, 70, 2.1)
    elif frth <= score < thrd: return f_att(score, thrd, frth, 69, 50, 0)
    elif ffth <= score < frth: return f_att(score, frth, ffth, 49, 30, 0)
    elif sxth <= score < ffth: return f_att(score, ffth, sxth, 29, 10, 0)
    elif svth <= score < sxth: return f_att(score, sxth, svth, 9, 2, 0)
    return 50

def get_dynamic_stats(ticker, spy_close):
    yf_ticker = ticker if not (str(ticker).isdigit() and len(str(ticker)) == 5) else f"{str(ticker)[1:]}.HK"
    df = yf.download(yf_ticker, period="1y", interval="1d", progress=False)
    if df.empty: return 0, 0, 0, 50
    close = df['Close'].squeeze()
    if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
    
    current_price = float(close.iloc[-1])
    sma21 = float(close.rolling(21).mean().iloc[-1])
    dist = ((current_price - sma21) / sma21) * 100
    
    delta = close.diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
    rsi = 100 - (100 / (1 + rs)).iloc[-1]
    rs_rating = calculate_rs_rating(close, spy_close)
    
    return current_price, dist, float(rsi), float(rs_rating)

# ================= 網頁主體 =================
if "stock_selector" not in st.session_state: st.session_state.stock_selector = None

@st.dialog("📊 Alpha Focus 歷史偵察報告", width="large")
def show_history_report(ticker, report_data):
    st.write(f"### 🎯 {ticker} 深度掃描紀錄")
    st.info(f"📂 存檔日期: {report_data['date']} | 💡 閱讀此報告完全免費，不消耗 API")
    with st.container(border=True):
        st.markdown(report_data['content'])

st.set_page_config(layout="wide", page_title="Alpha Focus Trading System")
st.title("🦅 Alpha Focus 三引擎量化交易系統 v10.1 (格式強化版)")

# ================= 側邊欄 =================
st.sidebar.header("⚙️ 系統配置")
default_gemini = st.secrets.get("GEMINI_API_KEY", "")
default_finnhub = st.secrets.get("FINNHUB_API_KEY", "")

api_key = st.sidebar.text_input("AI API Key (支援中轉)", value=default_gemini, type="password")
fh_api_key = st.sidebar.text_input("Finnhub API Key", value=default_finnhub, type="password")

st.sidebar.markdown("---")
uploaded_file = st.sidebar.file_uploader("1️⃣ 上傳 TradingView CSV (偵察選股)", type="csv")
futu_file = st.sidebar.file_uploader("2️⃣ 上傳 富途持倉 CSV (守護者)", type="csv")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 雲端歷史紀錄")

# 🚀 清洗按鈕
if st.sidebar.button("🧹 清除失敗快取 (重新掃描)"):
    keys_to_delete = [k for k, v in history.items() if "拒絕" in v.get("content", "") or "保留基礎數據" in v.get("content", "") or "⚠️" in v.get("content", "")]
    if keys_to_delete:
        for k in keys_to_delete:
            del history[k]
        save_history(history)
        st.sidebar.success(f"✅ 已清除 {len(keys_to_delete)} 筆失敗紀錄！")
        time.sleep(2)
        st.rerun()
    else:
        st.sidebar.info("目前沒有失敗的快取紀錄。")

if history:
    for ticker, data in history.items():
        # 🚀 隱藏系統大報告，只顯示個股按鈕
        if not ticker.startswith("_MACRO_"):
            if st.sidebar.button(f"🔍 {ticker} ({data['date']})", key=f"hist_{ticker}"):
                show_history_report(ticker, data)
                st.session_state.stock_selector = ticker
else:
    st.sidebar.caption("目前尚無分析紀錄。")

spy_data, vix_data = get_macro_benchmark()

# ================= 三分頁架構 =================
tab1, tab2, tab3 = st.tabs(["🎯 偵察模式 (單股深度)", "🛡️ 守護者模式 (持倉管理)", "🗺️ 宏觀與全景戰略 (批次掃描)"])

# ---------------------------------------------------------
# TAB 1: 單股深度偵察
# ---------------------------------------------------------
with tab1:
    st.info("單股深度 K 線圖與報告區域。")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        df['SMA21_Dist_Num'] = (((df['價格'] - df['簡單移動平均線 (21) 1天']) / df['簡單移動平均線 (21) 1天']) * 100).round(2)
        df['縮量狀態'] = df['成交量 1天'] < df['平均成交量 10天']

        display_df = df.copy()
        display_df['價格變化 % 1週'] = display_df['價格變化 % 1週'].apply(lambda x: f"{x:.2f}%" if pd.notnull(x) else "N/A")
        display_df['相對強弱指標 (14) 1天'] = display_df['相對強弱指標 (14) 1天'].fillna(0).round().astype(int)
        display_df['SMA21_Dist'] = display_df['SMA21_Dist_Num'].apply(lambda x: f"{x:.2f}%")

        st.subheader("📊 強勢股篩選清單")
        sniper_mask = (df['SMA21_Dist_Num'] >= 0) & (df['SMA21_Dist_Num'] <= 5)
        sniper_count = sniper_mask.sum()

        only_sniper = st.checkbox(f"🎯 只顯示狙擊區標的 (0-5% 距離) - 目前符合：{sniper_count} 隻", value=False)

        if only_sniper:
            view_df = display_df[sniper_mask]
            calc_df = df[sniper_mask]
        else:
            view_df = display_df
            calc_df = df

        st.dataframe(view_df[['商品', '價格', 'SMA21_Dist', '縮量狀態', '相對強弱指標 (14) 1天', '價格變化 % 1週', '產業']], use_container_width=True, hide_index=True)

        st.markdown("---")
        st.write("### 🔬 標的深度診斷")

        options = calc_df['商品'].tolist()
        if options and (st.session_state.stock_selector not in options):
            st.session_state.stock_selector = options[0]

        if options:
            selected_stock = st.selectbox("選擇要分析的標的：", options, key="stock_selector")
            stock_data = df[df['商品'] == selected_stock].iloc[0]
            real_sector = stock_data.get('產業', '未知')
            today_date = datetime.now().strftime("%Y-%m-%d")

            st.write(f"#### 📈 {selected_stock} 交互式 K 線圖")
            real_price, real_sma_dist, real_rsi, real_rs_rating = get_dynamic_stats(selected_stock, spy_data)

            hist_data = yf.download(selected_stock, period="6mo", interval="1d", progress=False)
            if not hist_data.empty:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.3, 0.7])
                open_p, high_p, low_p, close_p, volume_p = hist_data['Open'].squeeze(), hist_data['High'].squeeze(), hist_data['Low'].squeeze(), hist_data['Close'].squeeze(), hist_data['Volume'].squeeze()

                fig.add_trace(go.Candlestick(x=hist_data.index, open=open_p, high=high_p, low=low_p, close=close_p, name='K線'), row=1, col=1)
                sma21 = close_p.rolling(window=21).mean()
                fig.add_trace(go.Scatter(x=hist_data.index, y=sma21, line=dict(color='orange', width=2), name='SMA21'), row=1, col=1)
                colors = ['green' if c >= o else 'red' for c, o in zip(close_p, open_p)]
                fig.add_trace(go.Bar(x=hist_data.index, y=volume_p, marker_color=colors, name='成交量'), row=2, col=1)
                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                fig.update_layout(xaxis_rangeslider_visible=False, height=550, showlegend=False, margin=dict(t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

            st.write(f"#### 🧠 Alpha Focus 偵察報告")
            if selected_stock in history:
                st.info(f"📂 目前顯示的是雲端歷史紀錄 ({history[selected_stock]['date']})。閱讀歷史紀錄不消耗 API。")
                with st.container(border=True):
                    st.markdown(history[selected_stock]['content'])
                analyze_button = st.button("🔄 重新深度掃描 (啟動三引擎更新)")
            else:
                analyze_button = st.button("🚀 啟動數據審計協議 (三引擎融合)", type="primary")

            if analyze_button:
                if not api_key or not fh_api_key:
                    st.error("請確保已在左側邊欄設定 API Key！")
                else:
                    with st.spinner('正在從 Finnhub、Google 及 Yahoo 聚合情報並由 AI 審計中...'):
                        try:
                            news_pool = get_triple_engine_news(selected_stock, fh_api_key, fh_limit=4, g_limit=3, y_limit=2)
                            news_text = "過去 14 天內無重大新聞。" if not news_pool else "\n".join([f"{i + 1}. {text}" for i, text in enumerate(news_pool)])
                            client = OpenAI(api_key=api_key, base_url="https://xiaoai.plus/v1")
                            
                            prompt = f"""
                            # Role: 證據導向的華爾街 Swing Trading 分析師
                            ## 0. 數據審計輸入
                            - 標的：{selected_stock} | 實時現價：${real_price:.2f} | 距離 SMA21：{real_sma_dist:.2f}% | 板塊：{real_sector} | 基準日：{today_date}
                            - RS Rating：{real_rs_rating:.0f}
                            ## 1. 新聞流：
                            {news_text}
                            ## 2. 輸出格式要求 (嚴格遵守，務必使用換行與條列式)
                            **【重要排序】：必須嚴格按照 1. 🚀 Tier 1 -> 2. ⚡ Tier 2 -> 3. ⚪ Tier 3 -> 4. ⚠️ Risk。**
                            請直接輸出報告，必須包含中文翻譯與點評，並保留新聞來源。
                            """
                            response = client.chat.completions.create(model='gemini-2.5-flash', messages=[{"role": "user", "content": prompt}])
                            history[selected_stock] = {"date": today_date, "content": response.choices[0].message.content}
                            save_history(history)
                            st.success("審計完成！已存入快取。")
                            with st.container(border=True):
                                st.markdown(history[selected_stock]['content'])
                        except Exception as e:
                            st.error(f"分析發生錯誤: {e}")
    else:
        st.info("👈 請先從左側邊欄上傳你的 TradingView CSV 文件以啟動偵察模式。")

# ---------------------------------------------------------
# TAB 2: 守護者模式 (Guardian Mode) (省略修改，保持原樣)
# ---------------------------------------------------------
with tab2:
    st.info("富途持倉管理區域。")
    # ... (保持原樣，篇幅原因不重複印出) ...

# ---------------------------------------------------------
# TAB 3: 全新！宏觀與全景戰略模式 (v10.1 批次省流+防呆模板架構)
# ---------------------------------------------------------
with tab3:
    st.subheader("🗺️ 宏觀與全景戰略 (Alpha Focus Playbook)")
    st.write("已啟動「強制防呆模板與防斷線機制」，保護排版不崩壞。")
    
    if 'auto_scan' not in st.session_state:
        st.session_state.auto_scan = False

    if uploaded_file:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file)
        df['產業'] = df['產業'].fillna('未知') if '產業' in df.columns else '未知'
        df['SMA21_Dist_Num'] = (((df['價格'] - df['簡單移動平均線 (21) 1天']) / df['簡單移動平均線 (21) 1天']) * 100).round(2)
        target_list = df['商品'].tolist()
        total_stocks = len(target_list)
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        uncached_list = [t for t in target_list if t not in history or history[t].get('date') != today_date]
        cached_count = total_stocks - len(uncached_list)
        
        st.info(f"📊 **總體進度盤點**：總清單 {total_stocks} 隻。今日已存檔 {cached_count} 隻，剩餘 {len(uncached_list)} 隻待處理。")
        progress_bar = st.progress(cached_count / total_stocks if total_stocks > 0 else 0)
        
        if len(uncached_list) > 0:
            batch_size = 5 
            current_batch = uncached_list[:batch_size]
            
            st.write(f"👉 **當前批次任務 (共 {len(current_batch)} 隻)**:")
            st.code(", ".join(current_batch))
            
            col1, col2 = st.columns([1, 4])
            with col1:
                if not st.session_state.auto_scan:
                    if st.button("🚀 啟動批次全自動掃描", type="primary"):
                        st.session_state.auto_scan = True
                        st.rerun()
                else:
                    if st.button("⏸️ 緊急暫停", type="secondary"):
                        st.session_state.auto_scan = False
                        st.rerun()
            
            if st.session_state.auto_scan:
                if not api_key or not fh_api_key:
                    st.error("請確保已輸入 API Key！")
                    st.session_state.auto_scan = False 
                else:
                    client = OpenAI(api_key=api_key, base_url="https://xiaoai.plus/v1")
                    
                    with st.expander("💻 系統即時執行日誌 (Terminal)", expanded=True):
                        log_area = st.empty()
                        if 'log_history' not in st.session_state:
                            st.session_state.log_history = []
                        
                        def update_log(msg):
                            time_str = datetime.now().strftime('%H:%M:%S')
                            st.session_state.log_history.insert(0, f"[{time_str}] {msg}")
                            if len(st.session_state.log_history) > 15: st.session_state.log_history.pop()
                            log_area.text_area("Log:", value="\n".join(st.session_state.log_history), height=250, disabled=True, label_visibility="collapsed")
                    
                    update_log(f"📦 正在打包 {len(current_batch)} 隻標的...")
                    all_tickers_data = ""
                    
                    for ticker in current_batch:
                        sector = df[df['商品'] == ticker]['產業'].iloc[0]
                        curr_price, dist, rsi, rs_rating = get_dynamic_stats(ticker, spy_data)
                        news_pool = get_triple_engine_news(ticker, fh_api_key, fh_limit=3, g_limit=1, y_limit=1)
                        news_text = "無重大新聞" if not news_pool else " | ".join(news_pool)
                        
                        all_tickers_data += f"--- START: {ticker} ---\n"
                        all_tickers_data += f"價格:{curr_price}, RS:{rs_rating:.0f}, 距SMA21:{dist:.2f}%, 板塊:{sector}\n"
                        all_tickers_data += f"新聞內容: {news_text}\n\n"

                    # 🚀 終極防呆 Prompt：強制換行、保留來源標籤
                    mega_prompt = f"""
                    # Role: 頂尖波段交易分析師 (Alpha Focus)
                    
                    請針對以下標的進行分析。
                    
                    ## 數據清單：
                    {all_tickers_data}
                    
                    ## ⚠️ 輸出格式要求 (絕對嚴格遵守，禁止自創表格，必須保留新聞來源)：
                    請針對每一檔股票，**完全複製並填寫**下方的 Markdown 模板。不要省略任何換行符號（Enter）。
                    
                    [[[股票代碼]]]
                    
                    **🏢 公司簡介**：
                    [一句話簡述該公司的核心業務與行業地位]
                    
                    **🛡️ 數據校驗**：
                    * 價格：${{[填入價格]}}
                    * 距SMA21：{{[填入距離]}}%
                    * RS評級：{{[填入RS]}}
                    
                    **🧠 動能與風險剖析**：
                    [結合數據校驗，給出一小段判斷：資金是否強勢？乖離率是否過高？]
                    
                    **📰 核心新聞矩陣**：
                    (必須按此順序分類，請務必抄寫新聞來源例如[Finnhub 機構]，若無則寫「無」)
                    * 🚀 **[Tier 1 動能催化]** [來源標籤] [英文標題] - [中文點評]
                    * ⚡ **[Tier 2 潛在影響]** [來源標籤] [英文標題] - [中文點評]
                    * ⚪ **[Tier 3 普遍資訊]** [來源標籤] [英文標題] - [中文點評]
                    * ⚠️ **[Risk 風險警告]** [來源標籤] [英文標題] - [中文點評]
                    
                    ======
                    """

                    with st.spinner(f"正在由 AI 審計批次: {', '.join(current_batch)}..."):
                        mega_success = False
                        full_response_text = ""
                        
                        for attempt in range(1, 4):
                            try:
                                response = client.chat.completions.create(
                                    model='gemini-2.5-flash',
                                    messages=[{"role": "user", "content": mega_prompt}]
                                )
                                full_response_text = response.choices[0].message.content
                                update_log("✅ 批次 AI 審計完畢，開始解析數據...")
                                mega_success = True
                                break 
                            except Exception as e:
                                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                                    update_log(f"🛑 觸發限流，強制深睡 65 秒... (重試 {attempt}/3)")
                                    time.sleep(65)
                                else:
                                    update_log(f"⚠️ 發生未知錯誤: {e}")
                                    break
                                    
                        if mega_success:
                            # 🚀 強化防呆解析：先清除多餘空白
                            clean_response = full_response_text.replace("[[[ ", "[[[").replace(" ]]]", "]]]")
                            
                            for ticker in current_batch:
                                ticker_marker = f"[[[{ticker}]]]"
                                parsed_content = ""
                                
                                if ticker_marker in clean_response:
                                    try:
                                        parts = clean_response.split(ticker_marker)
                                        if len(parts) > 1:
                                            # 切到下一個分隔符號或是結尾
                                            parsed_content = parts[1].split("======")[0].split("[[[")[0].strip()
                                    except Exception as e:
                                        parsed_content = f"⚠️ 解析失敗，請檢查 AI 輸出格式。"
                                else:
                                    parsed_content = f"⚠️ AI 未按照格式回傳 {ticker} 的資料，保留基礎紀錄。"

                                sector = df[df['商品'] == ticker]['產業'].iloc[0]
                                curr_price, dist, rsi, rs_rating = get_dynamic_stats(ticker, spy_data)
                                info_str = f"【{ticker}】板塊:{sector} | 距SMA21:{dist:.2f}% | RS:{rs_rating:.0f}"
                                
                                history[ticker] = {
                                    "date": today_date,
                                    "content": parsed_content if parsed_content else "無分析內容",
                                    "info_str": info_str
                                }
                            
                            save_history(history)
                            update_log(f"💾 批次存檔成功！冷卻 15 秒確保安全...")
                            time.sleep(15) 
                            
                            countdown_ph = st.empty()
                            for sec in range(5, 0, -1):
                                countdown_ph.info(f"⏳ {sec} 秒後自動推進下一批次...")
                                time.sleep(1)
                                
                            st.rerun()
                        else:
                            update_log("❌ 批次處理徹底失敗，系統暫停。")
                            st.session_state.auto_scan = False
                            st.rerun()
                            
        else:
            st.session_state.auto_scan = False
            st.success("✨ 太棒了！所有標的已經全數存檔完畢。你可以隨時在左側點擊查看。")
            
            # 🚀 新增：全景戰略大報告「防扣費快取」機制
            macro_cache_key = f"_MACRO_REPORT_{today_date}"
            
            if st.button("📊 生成終極全景戰略報告", type="primary"):
                if macro_cache_key in history:
                    st.success("🎉 已從雲端載入今日的【全景戰略報告】！(本次讀取不消耗 API 費用)")
                    with st.container(border=True):
                        st.markdown(history[macro_cache_key]['content'])
                else:
                    if not api_key:
                        st.error("請輸入 API Key！")
                    else:
                        client = OpenAI(api_key=api_key, base_url="https://xiaoai.plus/v1")
                        with st.spinner("正在為您統整 127 檔股票的戰略視野，這可能需要一點時間..."):
                            aggregated_data_list = [history[t]['info_str'] for t in target_list if t in history and 'info_str' in history[t]]
                            final_all_data_text = "\n".join(aggregated_data_list)
                            vix_latest = float(vix_data.iloc[-1]) if vix_data is not None else "未知"
                            
                            macro_prompt = f"""
                            # Role: 頂級華爾街宏觀對沖基金經理人 (Alpha Focus - 全景戰略)
                            ## 市場背景
                            - VIX: {vix_latest} | 基準日: {today_date}
                            
                            ## 全量掃描數據 ({total_stocks} 隻)
                            請使用您的「數據校驗風格」進行盤點：
                            {final_all_data_text}
                            
                            ## 任務
                            請基於上述完整名單產出：
                            1. 最強板塊排行 (Top 5)
                            2. Alpha Focus Top Picks (精選最佳動能與距離的標的)
                            3. 宏觀環境分析
                            4. 戰略建議 (The Swing Playbook)
                            5. 關鍵風險提醒
                            """
                            
                            for attempt in range(1, 4):
                                try:
                                    macro_res = client.chat.completions.create(
                                        model='gemini-2.5-flash',
                                        messages=[{"role": "user", "content": macro_prompt}]
                                    )
                                    macro_text = macro_res.choices[0].message.content
                                    
                                    # 存入專屬快取，保護錢包！
                                    history[macro_cache_key] = {"date": today_date, "content": macro_text}
                                    save_history(history)
                                    
                                    st.success("🎉 全景戰略報告已成功生成並存檔！")
                                    with st.container(border=True):
                                        st.markdown(macro_text)
                                    break
                                except Exception as e:
                                    if "429" in str(e):
                                        st.warning(f"🛑 生成大報告時觸發限流，等待 60 秒後重試... ({attempt}/3)")
                                        time.sleep(60)
                                    else:
                                        st.error(f"報告生成失敗: {e}")
                                        break
    else:
        st.info("👈 請先上傳 TradingView CSV 以啟動全景模式。")

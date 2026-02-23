import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from google import genai
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
    """快取大盤 SPY 與 VIX 數據"""
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

st.set_page_config(layout="wide", page_title="Alpha Focus Trading System")
st.title("🦅 Alpha Focus 三引擎量化交易系統 v8.0")

# ================= 側邊欄 =================
st.sidebar.header("⚙️ 系統配置")
default_gemini = st.secrets.get("GEMINI_API_KEY", "")
default_finnhub = st.secrets.get("FINNHUB_API_KEY", "")

api_key = st.sidebar.text_input("Gemini API Key", value=default_gemini, type="password")
fh_api_key = st.sidebar.text_input("Finnhub API Key", value=default_finnhub, type="password")

st.sidebar.markdown("---")
uploaded_file = st.sidebar.file_uploader("1️⃣ 上傳 TradingView CSV (偵察選股)", type="csv")
futu_file = st.sidebar.file_uploader("2️⃣ 上傳 富途持倉 CSV (守護者)", type="csv")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 雲端歷史紀錄 (點擊跳轉)")
if history:
    for ticker, data in history.items():
        if st.sidebar.button(f"🔍 {ticker} ({data['date']})", key=f"hist_{ticker}"):
            st.session_state.stock_selector = ticker
else:
    st.sidebar.caption("目前尚無分析紀錄。")

spy_data, vix_data = get_macro_benchmark()

# ================= 三分頁架構 =================
tab1, tab2, tab3 = st.tabs(["🎯 偵察模式 (單股深度)", "🛡️ 守護者模式 (持倉管理)", "🗺️ 宏觀與全景戰略 (批次掃描)"])

# ---------------------------------------------------------
# TAB 1 & 2: 保持原本的單股與守護者邏輯 (為節省篇幅，這部分與 v7 相同，請保留原本 tab1, tab2 的代碼，我這裡精簡示意)
# ---------------------------------------------------------
with tab1:
    st.info("此區塊為原本的單股深度 K 線圖與報告區域，代碼與 v7.0 完全相同。")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)

        df['SMA21_Dist_Num'] = (
                    ((df['價格'] - df['簡單移動平均線 (21) 1天']) / df['簡單移動平均線 (21) 1天']) * 100).round(2)
        df['縮量狀態'] = df['成交量 1天'] < df['平均成交量 10天']

        display_df = df.copy()
        display_df['價格變化 % 1週'] = display_df['價格變化 % 1週'].apply(
            lambda x: f"{x:.2f}%" if pd.notnull(x) else "N/A")
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

        st.dataframe(
            view_df[['商品', '價格', 'SMA21_Dist', '縮量狀態', '相對強弱指標 (14) 1天', '價格變化 % 1週', '產業']],
            use_container_width=True, hide_index=True)

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
            # 獲取價格與動能 (RS Rating)
            real_price, real_sma_dist, real_rsi, real_rs_rating = get_dynamic_stats(selected_stock, spy_data)

            # K線圖繪製
            hist_data = yf.download(selected_stock, period="6mo", interval="1d", progress=False)
            if not hist_data.empty:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.3, 0.7])
                open_p = hist_data['Open'].squeeze()
                high_p = hist_data['High'].squeeze()
                low_p = hist_data['Low'].squeeze()
                close_p = hist_data['Close'].squeeze()
                volume_p = hist_data['Volume'].squeeze()

                fig.add_trace(
                    go.Candlestick(x=hist_data.index, open=open_p, high=high_p, low=low_p, close=close_p, name='K線'),
                    row=1, col=1)
                sma21 = close_p.rolling(window=21).mean()
                fig.add_trace(go.Scatter(x=hist_data.index, y=sma21, line=dict(color='orange', width=2), name='SMA21'),
                              row=1, col=1)
                colors = ['green' if c >= o else 'red' for c, o in zip(close_p, open_p)]
                fig.add_trace(go.Bar(x=hist_data.index, y=volume_p, marker_color=colors, name='成交量'), row=2, col=1)

                fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                fig.update_layout(xaxis_rangeslider_visible=False, height=550, showlegend=False,
                                  margin=dict(t=10, b=10))
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
                    st.error("請確保已在左側邊欄或 Streamlit Secrets 設定 API Key！")
                else:
                    with st.spinner('正在從 Finnhub、Google 及 Yahoo 聚合情報並由 AI 審計中...'):
                        try:
                            news_pool = get_triple_engine_news(selected_stock, fh_api_key, fh_limit=4, g_limit=3,
                                                               y_limit=2)

                            if not news_pool:
                                news_text = "過去 14 天內無重大新聞。"
                            else:
                                news_text = "\n".join([f"{i + 1}. {text}" for i, text in enumerate(news_pool)])

                            client = genai.Client(api_key=api_key)
                            prompt = f"""
                            # Role: 證據導向的華爾街 Swing Trading 分析師 (Alpha Focus - 偵察模式)

                            ## 0. 數據審計輸入 (Anti-Hallucination)
                            - 標的：{selected_stock} | 實時現價：${real_price:.2f} | 距離 SMA21：{real_sma_dist:.2f}% | 板塊：{real_sector} | 基準日：{today_date}
                            - 📊 **核心技術參數**：
                                - **RSI (14)**：{real_rsi:.0f} (判斷超買超賣)
                                - **IBD RS Rating (相對強度 1-99)**：{real_rs_rating:.0f}

                            ## 1. 待分析綜合新聞流 (Finnhub + Google + Yahoo)：
                            {news_text}

                            ## 2. 分析師動能判斷法則 (強制執行)：
                            - 結合 RS Rating 判斷新聞動能：
                                - 如果 RS > 80 且出現 Tier 1 消息：這是機構強烈控盤的「真突破/強勢股」，建議高度關注 (健康回踩/買入)。
                                - 如果 RS < 40 且出現 Tier 1 消息：資金面上方套牢賣壓極重，這通常是「死貓反彈」或逃命波，必須在風險矩陣中嚴格警告。

                            ## 3. 輸出格式要求 (嚴格遵守)

                            ### 第一部分：偵察表格
                            `[偵察基準日: {today_date} | 數據源: 三引擎 API | 基準價: ${real_price:.2f} | 美東時間: 盤後]`
                            | 代碼 | 板塊 | 參數概覽 (RSI / RS Rating) | 最新狀態 (Price & % vs SMA21) | 核心催化劑(摘要) | 資金動能邏輯 | 狀態評價 | 評分 |
                            | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
                            | {selected_stock} | {real_sector} | RSI: {real_rsi:.0f} <br> **RS: {real_rs_rating:.0f}** | **${real_price:.2f}** ({real_sma_dist:.2f}%) | [一句話總結 Tier 1 或 Risk] | [結合RS Rating分析動能真偽] | [死貓反彈/健康回踩/強勢突破] | [1-100] |

                            ### 第二部分：消息與風險矩陣明細 (雙語對照)
                            **【重要排序指令】：必須嚴格按照以下順序排列：1. 🚀 Tier 1 -> 2. ⚡ Tier 2 -> 3. ⚪ Tier 3 -> 4. ⚠️ Risk。**

                            - 🚀 **[Tier 1]** (Original English Title Here) [標註新聞來源]
                              - **中文翻譯**：...
                              - **分析點評**：...
                            """
                            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                            history[selected_stock] = {"date": today_date, "content": response.text}
                            save_history(history)
                            st.success("審計完成！已存入快取。")
                            with st.container(border=True):
                                st.markdown(response.text)
                        except Exception as e:
                            st.error(f"分析發生錯誤: {e}")
    else:
        st.info("👈 請先從左側邊欄上傳你的 TradingView CSV 文件以啟動偵察模式。")

# ---------------------------------------------------------
# TAB 2: 守護者模式 (Guardian Mode)
# ---------------------------------------------------------

with tab2:
    st.info("此區塊為原本的富途持倉管理區域，代碼與 v7.0 完全相同。")
    st.subheader("🛡️ 守護者模式：富途持倉健檢與動態止損")
    if futu_file:
        futu_df = pd.read_csv(futu_file)

        my_holdings = futu_df['代碼'].astype(str).tolist()
        st.write("已成功載入您的富途持倉。請選擇要執行健檢的標的：")
        selected_holdings = st.multiselect("選擇持倉：", my_holdings, default=my_holdings)

        if st.button("🛡️ 執行持倉組合審計 (Portfolio Audit)", type="primary"):
            if not api_key or not fh_api_key:
                st.error("請確保已在左側邊欄或 Streamlit Secrets 設定 API Key！")
            else:
                with st.spinner('正在獲取最新技術指標、計算 IBD 相對強度與三引擎新聞，進行深度持倉審計...'):
                    try:
                        portfolio_data = ""
                        today_date = datetime.now().strftime("%Y-%m-%d")

                        for ticker in selected_holdings:
                            row = futu_df[futu_df['代碼'] == ticker].iloc[0]
                            cost_price = row.get('攤薄成本價', 'N/A')
                            profit_pct = row.get('盈虧比例', 'N/A')

                            curr_price, dist, rsi, rs_rating = get_dynamic_stats(ticker, spy_data)

                            news_pool = get_triple_engine_news(ticker, fh_api_key, fh_limit=3, g_limit=2, y_limit=2)

                            if not news_pool:
                                n_text = "過去 14 天內無重大新聞。"
                            else:
                                n_text = "\n".join([f"{i + 1}. {text}" for i, text in enumerate(news_pool)])

                            portfolio_data += f"\n====================\n【{ticker}】\n- 券商成本: ${cost_price} | 目前盈虧: {profit_pct}\n- 實時現價: ${curr_price:.2f} | 距SMA21: {dist:.2f}% | RSI: {rsi:.0f} | **IBD RS Rating: {rs_rating:.0f}**\n- 綜合新聞流:\n{n_text}\n"

                        client = genai.Client(api_key=api_key)

                        guardian_prompt = f"""
                        # Role: 證據導向的華爾街 Swing Trading 分析師 (Alpha Focus - 守護者模式)

                        ## 0. 數據審計協議 (Data Integrity Protocol 3.0)
                        以下是我的真實持倉數據，包含三引擎新聞與 IBD 動能參數，請根據這些數據給我深度建議：
                        {portfolio_data}
                        基準日：{today_date}

                        ## 1. 輸出格式要求 (請嚴格遵守以下 Markdown 結構)

                        `[數據源: 三引擎 API/Futu | 審計基準日: {today_date} | 美東時間: 盤後]`

                        ### 📊 1. 持倉速覽總表 (Overview)
                        | 代碼 | 持倉成本 / 最新價格 (% vs SMA21) | 目前盈虧 | 動能參數 (RSI / RS Rating) | 決策建議 | 守護策略 (具體止損/止盈位) |
                        | :--- | :--- | :--- | :--- | :--- | :--- |
                        (請為我選擇的每一檔股票生成一行總結)

                        ---
                        ### 🔬 2. 個股深度消息與風險矩陣 (Deep Dive)
                        (請為上述每一檔持倉股票，單獨列出新聞的 Tier 評級與雙語點評。必須嚴格按照 1. 🚀 Tier 1 -> 2. ⚡ Tier 2 -> 3. ⚪ Tier 3 -> 4. ⚠️ Risk 排序)
                        (點評時，務必結合 RS Rating 告訴我，目前資金的控盤強度是否支持該股票繼續持有，或是已經轉弱需要 Trim！)

                        (針對每一檔持倉，請使用以下格式：)
                        #### 📌 [股票代碼] 消息面與動能剖析
                        - 🚀 **[Tier 1]** (Original English Title Here) [標註新聞來源]
                          - **中文翻譯**：...
                          - **守護者點評**：[這則消息對我們目前的持倉有什麼具體影響？結合動能評級，該股票還能抱嗎？]
                        - ⚠️ **[Risk]** (Original English Title Here) [標註新聞來源]
                          - **中文翻譯**：...
                          - **守護者點評**：...

                        ---
                        ### 📋 3. 持倉組合總結 (Portfolio Playbook)
                        1. **組合風險警告**：是否有過度曝險的狀況？資金分配是否合理？
                        2. **急迫行動清單**：列出必須在今日內做出決策的股票（例如破位、動能 RS < 50 且虧損擴大、或利多出盡需獲利了結）。
                        3. **動態止損指南**：根據當前大盤環境，建議如何調整整體的移動止盈策略。
                        """

                        g_response = client.models.generate_content(model='gemini-2.5-flash', contents=guardian_prompt)
                        st.success("持倉審計完成！")
                        with st.container(border=True):
                            st.markdown(g_response.text)

                    except Exception as e:
                        st.error(f"分析時發生錯誤: {e}")
    else:
        st.info("👈 請上傳您的富途持倉 CSV 以啟動守護者模式。")




# ---------------------------------------------------------
# TAB 3: 全新！宏觀與全景戰略模式 (v9.5 永動機護航版)
# ---------------------------------------------------------
with tab3:
    st.subheader("🗺️ 宏觀與全景戰略 (Alpha Focus Playbook)")
    st.write("已啟動「物理限速與自動接關模式」：精準控制每分鐘 RPM，每 10 檔自動重整網頁防斷線。")
    
    # 🛡️ 狀態鎖定器：確保網頁重整後還記得要繼續跑
    if 'auto_scan' not in st.session_state:
        st.session_state.auto_scan = False

    if uploaded_file:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file)
        
        # 預防資料缺失
        if '產業' in df.columns:
            df['產業'] = df['產業'].fillna('未知')
        else:
            df['產業'] = '未知'
            
        df['SMA21_Dist_Num'] = (((df['價格'] - df['簡單移動平均線 (21) 1天']) / df['簡單移動平均線 (21) 1天']) * 100).round(2)
        target_list = df['商品'].tolist()
        total_stocks = len(target_list)
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        # 🔍 核心盤點：找出今天還沒掃描的股票
        uncached_list = [t for t in target_list if t not in history or history[t].get('date') != today_date]
        cached_count = total_stocks - len(uncached_list)
        
        st.info(f"📊 **總體進度盤點**：總清單 {total_stocks} 隻。今日已存檔 {cached_count} 隻，剩餘 {len(uncached_list)} 隻待處理。")
        progress_bar = st.progress(cached_count / total_stocks if total_stocks > 0 else 0)
        
        # ================= 階段一：自動分批推進 =================
        if len(uncached_list) > 0:
            batch_size = 5
            current_batch = uncached_list[:batch_size]
            
            st.write(f"👉 **當前批次任務 (共 {len(current_batch)} 隻)**:")
            st.code(", ".join(current_batch))
            
            col1, col2 = st.columns([1, 4])
            with col1:
                # 按鈕邏輯切換
                if not st.session_state.auto_scan:
                    if st.button("🚀 啟動全自動掃描", type="primary"):
                        st.session_state.auto_scan = True
                        st.rerun()
                else:
                    if st.button("⏸️ 緊急暫停", type="secondary"):
                        st.session_state.auto_scan = False
                        st.rerun()
            
            # ⚙️ 如果狀態是「啟動」，則開始執行無敵迴圈
            if st.session_state.auto_scan:
                if not api_key or not fh_api_key:
                    st.error("請確保已輸入 API Key！")
                    st.session_state.auto_scan = False 
                else:
                    client = genai.Client(api_key=api_key)
                    
                    with st.expander("💻 系統即時執行日誌 (Terminal)", expanded=True):
                        log_area = st.empty()
                        log_history = []
                        
                    def update_log(msg):
                        time_str = datetime.now().strftime('%H:%M:%S')
                        log_history.insert(0, f"[{time_str}] {msg}")
                        if len(log_history) > 15: log_history.pop()
                        log_area.text_area("Log:", value="\n".join(log_history), height=250, disabled=True, label_visibility="collapsed")
                        
                    # 處理這 10 隻股票
                    for i, ticker in enumerate(current_batch):
                        st.write(f"⏳ 正在掃描 ({i+1}/{len(current_batch)}): **{ticker}**")
                        sector = df[df['商品'] == ticker]['產業'].iloc[0]
                        
                        update_log(f"🔍 {ticker} 啟動三引擎數據採集...")
                        curr_price, dist, rsi, rs_rating = get_dynamic_stats(ticker, spy_data)
                        news_pool = get_triple_engine_news(ticker, fh_api_key, fh_limit=4, g_limit=2, y_limit=2)
                        news_text = "無新聞" if not news_pool else " | ".join(news_pool[:3])
                        
                        mini_prompt = f"分析 {ticker} (價格:{curr_price}, RS:{rs_rating}, 距SMA21:{dist}%)。新聞:{news_text}。請生成詳細雙語報告並按 Tier 1-3 排序。"
                        
                        ai_content = ""
                        ai_success = False
                        
                        # 🛡️ 無敵重試裝甲：允許 3 次死磕
                        for attempt in range(1, 4):
                            try:
                                response = client.models.generate_content(model='gemini-2.5-flash', contents=mini_prompt)
                                ai_content = response.text
                                update_log(f"✅ {ticker} AI 審計完畢。")
                                ai_success = True
                                break 
                            except Exception as e:
                                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                                    update_log(f"🛑 {ticker} 觸發限流，強制深睡 65 秒確保歸零... (重試 {attempt}/3)")
                                    time.sleep(65)
                                else:
                                    update_log(f"⚠️ {ticker} 發生未知錯誤，跳過 AI。")
                                    ai_content = f"⚠️ 發生非限流錯誤: {e}"
                                    break
                                    
                        if not ai_success and ai_content == "":
                            ai_content = "⚠️ 歷經 3 次深睡重試仍遭拒絕，僅保留基礎數據。"
                            
                        # 💾 寫入本地 Json，落袋為安
                        info_str = f"【{ticker}】板塊:{sector} | 距SMA21:{dist:.2f}% | RS:{rs_rating:.0f} | 關鍵摘要:{news_text[:60]}"
                        
                        history[ticker] = {
                            "date": today_date,
                            "content": ai_content,
                            "info_str": info_str
                        }
                        save_history(history)
                        
                        # ⏱️ 物理限速器：每分鐘嚴格限制在 4 次，絕對不超速
                        update_log(f"💾 {ticker} 存檔成功。常規冷卻 15 秒...")
                        time.sleep(15)
                        
                    # ♻️ 批次結束，進入自動重整階段
                    update_log("🎉 本批次處理完成！準備刷新網頁，更新左側清單...")
                    countdown_ph = st.empty()
                    for sec in range(5, 0, -1):
                        countdown_ph.info(f"⏳ {sec} 秒後自動推進下一批次... (這會防範網頁斷線)")
                        time.sleep(1)
                        
                    st.rerun() # 系統自我刷新，進入下一個 10 隻！
                    
        # ================= 階段二：終極宏觀報告 =================
        else:
            # 全部跑完，解除自動掃描狀態
            st.session_state.auto_scan = False
            st.success("✨ 太棒了！127 隻標的已經全數存檔完畢。你可以隨時在左側點擊查看。")
            
            if st.button("📊 生成終極全景戰略報告", type="primary"):
                if not api_key:
                    st.error("請輸入 Gemini API Key！")
                else:
                    client = genai.Client(api_key=api_key)
                    with st.spinner("正在提取這 127 隻股票的雲端精華數據，生成宏觀報告中..."):
                        
                        # 從 history 直接拉資料，不消耗 API 次數！
                        aggregated_data_list = [history[t]['info_str'] for t in target_list if t in history and 'info_str' in history[t]]
                        final_all_data_text = "\n".join(aggregated_data_list)
                        vix_latest = float(vix_data.iloc[-1]) if vix_data is not None else "未知"
                        
                        macro_prompt = f"""
                        # Role: 頂級華爾街宏觀對沖基金經理人 (Alpha Focus - 全景戰略)
                        ## 市場背景
                        - VIX: {vix_latest} | 基準日: {today_date}
                        
                        ## 全量掃描數據 ({total_stocks} 隻)
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
                                macro_res = client.models.generate_content(model='gemini-2.5-flash', contents=macro_prompt)
                                st.success("🎉 全景戰略報告已成功生成！")
                                with st.container(border=True):
                                    st.markdown(macro_res.text)
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


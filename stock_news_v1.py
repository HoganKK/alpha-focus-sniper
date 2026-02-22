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
    
    # 1. Finnhub 專業新聞
    fh_news = get_finnhub_news(ticker, fh_api_key, limit=fh_limit)
    for n in fh_news:
        news_pool.append(f"[Finnhub 機構] {n}")
        
    # 2. Google News 廣泛搜尋
    try:
        query = urllib.parse.quote(f"{ticker} stock news")
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en")
        for entry in feed.entries[:g_limit]:
            news_pool.append(f"[Google 財經] {entry.title}")
    except:
        pass
        
    # 3. Yahoo Finance 實時快訊
    try:
        yf_ticker = ticker
        if str(ticker).isdigit() and len(str(ticker)) == 5:
            yf_ticker = f"{str(ticker)[1:]}.HK"
        y_info = yf.Ticker(yf_ticker)
        for n in y_info.news[:y_limit]:
            title = n.get('title') or n.get('headline') or ''
            if title:
                news_pool.append(f"[Yahoo 快訊] {title}")
    except:
        pass
        
    return news_pool

# --- IBD RS Rating 計算邏輯 (移植自 TradingView Pine Script) ---
@st.cache_data(ttl=3600)
def get_spy_benchmark():
    """快取大盤數據以節省下載時間"""
    spy = yf.download("SPY", period="1y", interval="1d", progress=False)
    if not spy.empty:
        close = spy['Close'].squeeze()
        if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
        return close
    return None

def calculate_rs_rating(stock_close, spy_close):
    """計算 IBD 風格的 1-99 相對強度評級"""
    if stock_close is None or spy_close is None or len(stock_close) < 10 or len(spy_close) < 10:
        return 50  # 數據不足時返回中性 50

    # 對齊 TradingView 計算週期 (63, 126, 189, 252)
    n63 = min(63, len(stock_close)-1, len(spy_close)-1)
    n126 = min(126, len(stock_close)-1, len(spy_close)-1)
    n189 = min(189, len(stock_close)-1, len(spy_close)-1)
    n252 = min(252, len(stock_close)-1, len(spy_close)-1)

    # 標的季度表現
    perf_T63 = stock_close.iloc[-1] / stock_close.iloc[-1 - n63]
    perf_T126 = stock_close.iloc[-1] / stock_close.iloc[-1 - n126]
    perf_T189 = stock_close.iloc[-1] / stock_close.iloc[-1 - n189]
    perf_T252 = stock_close.iloc[-1] / stock_close.iloc[-1 - n252]

    # SPY大盤季度表現
    perf_S63 = spy_close.iloc[-1] / spy_close.iloc[-1 - n63]
    perf_S126 = spy_close.iloc[-1] / spy_close.iloc[-1 - n126]
    perf_S189 = spy_close.iloc[-1] / spy_close.iloc[-1 - n189]
    perf_S252 = spy_close.iloc[-1] / spy_close.iloc[-1 - n252]

    # 加權得分 (近一季權重加倍)
    rs_stock = 0.4 * perf_T63 + 0.2 * perf_T126 + 0.2 * perf_T189 + 0.2 * perf_T252
    rs_ref = 0.4 * perf_S63 + 0.2 * perf_S126 + 0.2 * perf_S189 + 0.2 * perf_S252

    if rs_ref == 0: return 50
    totalRsScore = (rs_stock / rs_ref) * 100

    # 逼近分位數的常數
    first, scnd, thrd, frth, ffth, sxth, svth = 195.93, 117.11, 99.04, 91.66, 80.96, 53.64, 24.86

    def f_attributePercentile(score, tallerPerf, smallerPerf, rangeUp, rangeDn, weight):
        sum_val = score + (score - smallerPerf) * weight
        if sum_val > tallerPerf - 1: sum_val = tallerPerf - 1
        k1 = smallerPerf / rangeDn
        k2 = (tallerPerf - 1) / rangeUp
        k3 = (k1 - k2) / (tallerPerf - 1 - smallerPerf) if (tallerPerf - 1 - smallerPerf) != 0 else 0
        denom = (k1 - k3 * (score - smallerPerf))
        if denom == 0: return rangeDn
        RsRating = sum_val / denom
        if RsRating > rangeUp: RsRating = rangeUp
        if RsRating < rangeDn: RsRating = rangeDn
        return RsRating

    if totalRsScore >= first: return 99
    if totalRsScore <= svth: return 1

    if scnd <= totalRsScore < first: return f_attributePercentile(totalRsScore, first, scnd, 98, 90, 0.33)
    elif thrd <= totalRsScore < scnd: return f_attributePercentile(totalRsScore, scnd, thrd, 89, 70, 2.1)
    elif frth <= totalRsScore < thrd: return f_attributePercentile(totalRsScore, thrd, frth, 69, 50, 0)
    elif ffth <= totalRsScore < frth: return f_attributePercentile(totalRsScore, frth, ffth, 49, 30, 0)
    elif sxth <= totalRsScore < ffth: return f_attributePercentile(totalRsScore, ffth, sxth, 29, 10, 0)
    elif svth <= totalRsScore < sxth: return f_attributePercentile(totalRsScore, sxth, svth, 9, 2, 0)

    return 50

# --- 動態技術數據計算 ---
def get_dynamic_stats(ticker, spy_close):
    yf_ticker = ticker
    if str(ticker).isdigit() and len(str(ticker)) == 5:
        yf_ticker = f"{str(ticker)[1:]}.HK"
        
    # 改為抓取一年期資料以配合 RS Rating 運算
    df = yf.download(yf_ticker, period="1y", interval="1d", progress=False)
    if df.empty:
        return 0, 0, 0, 50
    
    close = df['Close'].squeeze()
    if isinstance(close, pd.DataFrame):
         close = close.iloc[:, 0]
         
    current_price = float(close.iloc[-1])
    sma21 = float(close.rolling(21).mean().iloc[-1])
    dist = ((current_price - sma21) / sma21) * 100
    
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rs = ema_up / ema_down
    rsi = 100 - (100 / (1 + rs)).iloc[-1]
    
    # 計算 IBD RS Rating
    rs_rating = calculate_rs_rating(close, spy_close)
    
    return current_price, dist, float(rsi), float(rs_rating)

if "stock_selector" not in st.session_state:
    st.session_state.stock_selector = None

# ================= 網頁主體 =================
st.set_page_config(layout="wide", page_title="Alpha Focus Trading System")
st.title("🦅 Alpha Focus 三引擎量化交易系統 v7.0")

# ================= 側邊欄 =================
st.sidebar.header("⚙️ 系統配置")

default_gemini = st.secrets.get("GEMINI_API_KEY", "")
default_finnhub = st.secrets.get("FINNHUB_API_KEY", "")

api_key = st.sidebar.text_input("Gemini API Key", value=default_gemini, type="password")
fh_api_key = st.sidebar.text_input("Finnhub API Key", value=default_finnhub, type="password")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📂 數據庫上傳區")
uploaded_file = st.sidebar.file_uploader("1️⃣ 上傳 TradingView CSV (偵察選股)", type="csv")
futu_file = st.sidebar.file_uploader("2️⃣ 上傳 富途持倉 CSV (守護者)", type="csv")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 雲端歷史紀錄 (點擊跳轉)")
if history:
    for ticker, data in history.items():
        if st.sidebar.button(f"🔍 查看 {ticker} ({data['date']})", key=f"hist_{ticker}"):
            st.session_state.stock_selector = ticker
else:
    st.sidebar.caption("目前尚無分析紀錄。")

# ================= 預載入大盤 SPY 資料 =================
spy_data = get_spy_benchmark()

# ================= 雙分頁架構 =================
tab1, tab2 = st.tabs(["🎯 偵察模式 (尋找強勢回踩)", "🛡️ 守護者模式 (富途持倉管理)"])

# ---------------------------------------------------------
# TAB 1: 偵察模式 (Sniper Mode)
# ---------------------------------------------------------
with tab1:
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

        st.dataframe(view_df[['商品', '價格', 'SMA21_Dist', '縮量狀態', '相對強弱指標 (14) 1天', '價格變化 % 1週', '產業']], 
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
                    st.error("請確保已在左側邊欄或 Streamlit Secrets 設定 API Key！")
                else:
                    with st.spinner('正在從 Finnhub、Google 及 Yahoo 聚合情報並由 AI 審計中...'):
                        try:
                            news_pool = get_triple_engine_news(selected_stock, fh_api_key, fh_limit=4, g_limit=3, y_limit=2)
                            
                            if not news_pool:
                                news_text = "過去 14 天內無重大新聞。"
                            else:
                                news_text = "\n".join([f"{i+1}. {text}" for i, text in enumerate(news_pool)])
                            
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
                                n_text = "\n".join([f"{i+1}. {text}" for i, text in enumerate(news_pool)])
                            
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

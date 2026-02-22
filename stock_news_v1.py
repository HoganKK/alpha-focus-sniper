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
    # 處理富途港股代碼邏輯 (如 09988 -> 9988.HK)
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

# --- 動態技術數據計算 (給守護者模式用) ---
def get_dynamic_stats(ticker):
    yf_ticker = ticker
    if str(ticker).isdigit() and len(str(ticker)) == 5:
        yf_ticker = f"{str(ticker)[1:]}.HK"
        
    df = yf.download(yf_ticker, period="3mo", interval="1d", progress=False)
    if df.empty:
        return 0, 0, 0
    
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
    
    return current_price, dist, float(rsi)

if "stock_selector" not in st.session_state:
    st.session_state.stock_selector = None

# ================= 網頁主體 =================
st.set_page_config(layout="wide", page_title="Alpha Focus Trading System")
st.title("🦅 Alpha Focus 三引擎量化交易系統 v6.1")

# ================= 側邊欄 =================
st.sidebar.header("⚙️ 系統配置")

# 自動載入 API Key，若 Streamlit Secrets 有設定則優先讀取，否則使用預設值
default_gemini = st.secrets.get("GEMINI_API_KEY", "AIzaSyCBGNM3YT7ydNha9PMfgUktiAHXWeYDZvk")
default_finnhub = st.secrets.get("FINNHUB_API_KEY", "d6dgqnhr01qm89pjf6fg")

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

# ================= 雙分頁架構 =================
tab1, tab2 = st.tabs(["🎯 偵察模式 (尋找強勢回踩)", "🛡️ 守護者模式 (富途持倉管理)"])

# ---------------------------------------------------------
# TAB 1: 偵察模式 (Sniper Mode)
# ---------------------------------------------------------
with tab1:
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        
        # 精確處理浮點數，解決數量對不上的 Bug
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
            real_price = stock_data['價格']
            real_sma_dist = stock_data['SMA21_Dist_Num']
            real_rsi = display_df[display_df['商品'] == selected_stock]['相對強弱指標 (14) 1天'].iloc[0]
            real_sector = stock_data.get('產業', '未知')
            today_date = datetime.now().strftime("%Y-%m-%d")

            st.write(f"#### 📈 {selected_stock} 交互式 K 線圖")
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
                    st.error("請確保已輸入 Gemini 與 Finnhub API Key！")
                else:
                    with st.spinner('正在從 Finnhub、Google 及 Yahoo 聚合情報並由 AI 審計中...'):
                        try:
                            # 啟動三引擎收集新聞
                            news_pool = get_triple_engine_news(selected_stock, fh_api_key, fh_limit=4, g_limit=3, y_limit=2)
                            
                            if not news_pool:
                                news_text = "過去 14 天內無重大新聞。"
                            else:
                                news_text = "\n".join([f"{i+1}. {text}" for i, text in enumerate(news_pool)])
                            
                            client = genai.Client(api_key=api_key)
                            prompt = f"""
                            # Role: 證據導向的華爾街 Swing Trading 分析師 (Alpha Focus - 偵察模式)
                            
                            ## 0. 數據審計輸入 (Anti-Hallucination)
                            - 標的：{selected_stock} | 實時現價：${real_price:.2f} | 距離 SMA21：{real_sma_dist:.2f}% | RSI (14)：{real_rsi} | 板塊：{real_sector} | 基準日：{today_date}
                            
                            ## 1. 待分析綜合新聞流 (Finnhub + Google + Yahoo)：
                            {news_text}
                            
                            ## 2. 輸出格式要求 (嚴格遵守)
                            
                            ### 第一部分：偵察表格
                            `[偵察基準日: {today_date} | 數據源: 三引擎 API | 基準價: ${real_price:.2f} | 美東時間: 盤後]`
                            | 代碼 | 板塊 | 公司簡介 | 最新狀態 (Price & % vs SMA21) | 核心催化劑(摘要) | 資金邏輯 | 狀態評價 | 評分 |
                            | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
                            | {selected_stock} | {real_sector} | [在此填寫50字內主營業務] | **${real_price:.2f}** ({real_sma_dist:.2f}%) | [一句話總結 Tier 1 或 Risk] | [分析資金湧入或撤出的邏輯] | [超買 / 剛突破 / 健康回踩] | [1-100] |
                            
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
                st.error("請確保已輸入 Gemini 與 Finnhub API Key！")
            else:
                with st.spinner('正在獲取最新技術指標與三引擎新聞，進行持倉審計...'):
                    try:
                        portfolio_data = ""
                        today_date = datetime.now().strftime("%Y-%m-%d")
                        
                        for ticker in selected_holdings:
                            row = futu_df[futu_df['代碼'] == ticker].iloc[0]
                            cost_price = row.get('攤薄成本價', 'N/A')
                            profit_pct = row.get('盈虧比例', 'N/A')
                            
                            curr_price, dist, rsi = get_dynamic_stats(ticker)
                            
                            # 守護者模式的三引擎抓取 (限制每股只抓少量最核心的新聞，避免 AI 負載過重)
                            news_pool = get_triple_engine_news(ticker, fh_api_key, fh_limit=2, g_limit=1, y_limit=1)
                            n_text = "無重大新聞" if not news_pool else " | ".join(news_pool)
                            
                            portfolio_data += f"【{ticker}】券商成本:${cost_price} | 目前盈虧:{profit_pct} | 實時現價:${curr_price:.2f} | 距SMA21:{dist:.2f}% | RSI:{rsi:.0f} | 核心新聞: {n_text}\n"

                        client = genai.Client(api_key=api_key)
                        guardian_prompt = f"""
                        # Role: 證據導向的華爾街 Swing Trading 分析師 (Alpha Focus - 守護者模式)
                        
                        ## 0. 數據審計協議 (Data Integrity Protocol 3.0)
                        以下是我的真實持倉數據，包含三引擎新聞，請根據這些數據給我具體建議：
                        {portfolio_data}
                        基準日：{today_date}
                        
                        ## 1. 核心任務：守護者邏輯
                        判斷趨勢健康度，並給出 Hold(續抱)、Trim(減倉)、Sell(清倉) 或 Add(加倉) 的決策。
                        
                        ## 2. 輸出格式 (嚴格使用此 Markdown 格式)
                        `[數據源: 三引擎 API/Futu | 審計基準日: {today_date} | 美東時間: 盤後]`
                        
                        ### 持倉個股審計表
                        | 代碼 | 持倉成本 / 最新價格 (% vs SMA21) | 趨勢健康度 (RSI與量價) | 消息與風險矩陣 (綜合評估) | 決策建議 | 守護策略 (具體止損位) |
                        | :--- | :--- | :--- | :--- | :--- | :--- |
                        (請為我選擇的每一檔股票生成一行分析)
                        
                        ### 持倉組合總結 (Portfolio Playbook)
                        1. **組合風險警告**：是否有過度曝險的狀況？
                        2. **急迫行動清單**：列出必須在今日內做出決策的股票（例如破位或虧損擴大）。
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

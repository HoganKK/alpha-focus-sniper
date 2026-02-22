import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from google import genai
import feedparser
import urllib.parse
from datetime import datetime
import json
import os

# --- 歷史紀錄系統設定 ---
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

# --- 記憶狀態 (Session State) ---
if "stock_selector" not in st.session_state:
    st.session_state.stock_selector = None
# ------------------------

st.set_page_config(layout="wide", page_title="Alpha Focus Trading System")
st.title("🦅 Alpha Focus 雙核心量化交易系統")

# ================= 側邊欄 =================
st.sidebar.header("⚙️ 系統配置")
api_key = st.sidebar.text_input("Gemini API Key", type="password")

st.sidebar.markdown("---")
uploaded_file = st.sidebar.file_uploader("📂 上傳 TradingView CSV", type="csv")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 雲端歷史紀錄 (點擊跳轉)")
if history:
    for ticker, data in history.items():
        if st.sidebar.button(f"🔍 查看 {ticker} (分析於 {data['date']})", key=f"hist_{ticker}"):
            st.session_state.stock_selector = ticker
else:
    st.sidebar.caption("目前尚無分析紀錄。")

# ================= 主畫面 (雙分頁切換) =================
if uploaded_file:
    # 原始數據讀取
    df = pd.read_csv(uploaded_file)
    df['SMA21_Dist'] = ((df['價格'] - df['簡單移動平均線 (21) 1天']) / df['簡單移動平均線 (21) 1天']) * 100
    df['縮量狀態'] = df['成交量 1天'] < df['平均成交量 10天']
    
    # 建立顯示用的格式化 DataFrame (解決小數點與 % 問題)
    display_df = df.copy()
    display_df['價格變化 % 1週'] = display_df['價格變化 % 1週'].apply(lambda x: f"{x:.2f}%" if pd.notnull(x) else "N/A")
    display_df['相對強弱指標 (14) 1天'] = display_df['相對強弱指標 (14) 1天'].fillna(0).round().astype(int)
    display_df['SMA21_Dist'] = display_df['SMA21_Dist'].apply(lambda x: f"{x:.2f}%")

    # 建立 UI 分頁
    tab1, tab2 = st.tabs(["🎯 偵察模式 (尋找進場點)", "🛡️ 守護者模式 (持倉與風險管理)"])

    # ---------------------------------------------------------
    # TAB 1: 偵察模式 (Sniper Mode)
    # ---------------------------------------------------------
    with tab1:
        st.subheader("📊 強勢股篩選清單")
        
        # 篩選邏輯 (使用原始 df 進行數值運算)
        sniper_mask = (df['SMA21_Dist'] >= 0) & (df['SMA21_Dist'] <= 5)
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
            
            # 獲取計算用的真實數值
            stock_data = df[df['商品'] == selected_stock].iloc[0]
            real_price = stock_data['價格']
            real_sma_dist = stock_data['SMA21_Dist']
            real_rsi = stock_data.get('相對強弱指標 (14) 1天', 'N/A')
            real_sector = stock_data.get('產業', '未知')
            today_date = datetime.now().strftime("%Y-%m-%d")

            # K線圖區塊
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

            # AI 分析區塊
            if selected_stock in history:
                st.info(f"📂 顯示歷史紀錄 ({history[selected_stock]['date']})。閱讀不消耗 API。")
                with st.container(border=True):
                    st.markdown(history[selected_stock]['content'])
                analyze_button = st.button("🔄 重新深度掃描 (消耗 API)")
            else:
                analyze_button = st.button("🚀 啟動數據審計協議 (Data Integrity Protocol)", type="primary")

            if analyze_button:
                if not api_key:
                    st.error("請先輸入 API Key")
                else:
                    with st.spinner('正在從雙重新聞源獲取資料並交叉驗證...'):
                        try:
                            # 1. 雙重新聞源交叉驗證 (Google RSS + Yahoo)
                            query = urllib.parse.quote(f"{selected_stock} stock news")
                            google_news_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
                            feed = feedparser.parse(google_news_url)
                            g_news = [entry.title for entry in feed.entries[:6]]
                            
                            y_info = yf.Ticker(selected_stock)
                            y_news = []
                            for n in y_info.news[:4]:
                                t = n.get('title') or n.get('headline') or ''
                                if t: y_news.append(t)
                                
                            all_news = list(set(g_news + y_news)) # 合併並去重
                            news_text = "\n".join([f"{i+1}. {title}" for i, title in enumerate(all_news[:8])])
                            
                            client = genai.Client(api_key=api_key)
                            prompt = f"""
                            # Role: 證據導向的華爾街 Swing Trading 分析師 (Alpha Focus - 偵察模式)
                            ## 0. 數據審計輸入
                            - 標的：{selected_stock} | 實時現價：${real_price:.2f} | 距離 SMA21：{real_sma_dist:.2f}% | RSI(14)：{real_rsi} | 板塊：{real_sector} | 日期：{today_date}
                            ## 1. 新聞流交叉驗證：\n{news_text}
                            
                            請生成偵察表格，並將新聞嚴格按 🚀 Tier 1 -> ⚡ Tier 2 -> ⚪ Tier 3 -> ⚠️ Risk 排序進行雙語翻譯點評。
                            """ # (為節省長度，這裡使用了你之前的 Prompt 邏輯，你可以將完整的 Prompt 替換進來)
                            
                            # 完整 Prompt 注入
                            full_prompt = prompt + """
                            ### 第一部分：偵察表格
                            `[偵察基準日: """+today_date+""" | 數據源: Google/Yahoo | 基準價: $"""+str(round(real_price,2))+""" | 美東時間: 盤後]`
                            | 代碼 | 板塊 | 公司簡介 | 最新狀態 (Price & % vs SMA21) | 核心催化劑(摘要) | 資金邏輯 | 狀態評價 | 評分 |
                            | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
                            | """+selected_stock+""" | """+str(real_sector)+""" | [50字主營業務] | **$"""+str(round(real_price,2))+"""** ("""+str(round(real_sma_dist,2))+"""%) | [一句話總結] | [分析資金邏輯] | [狀態] | [1-100] |
                            
                            ### 第二部分：消息與風險矩陣明細 (雙語對照)
                            (請依序向下排列所有新聞：🚀 Tier 1 -> ⚡ Tier 2 -> ⚪ Tier 3 -> ⚠️ Risk)
                            - 🚀 **[Tier 1]** (Original English Title Here)
                              - **中文翻譯**：...
                              - **分析點評**：...
                            """
                            response = client.models.generate_content(model='gemini-2.5-flash', contents=full_prompt)
                            history[selected_stock] = {"date": today_date, "content": response.text}
                            save_history(history)
                            st.success("審計完成！")
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"分析時發生錯誤: {e}")

    # ---------------------------------------------------------
    # TAB 2: 守護者模式 (Guardian Mode)
    # ---------------------------------------------------------
    with tab2:
        st.subheader("🛡️ 守護者模式：持倉與風險診斷")
        st.write("請從清單中選擇你目前持有的股票，系統將執行 Data Integrity Protocol 3.0 進行持倉健檢。")
        
        # 多選器讓用戶選擇持倉
        my_holdings = st.multiselect("選擇你的持倉標的 (可多選)：", df['商品'].tolist())
        
        if my_holdings:
            if st.button("🛡️ 執行持倉組合審計 (Portfolio Audit)", type="primary"):
                if not api_key:
                    st.error("請先在側邊欄輸入 API Key")
                else:
                    with st.spinner('正在分析持倉組合與動態止損水位...'):
                        try:
                            # 收集所有持倉的數據與新聞
                            portfolio_data = ""
                            for ticker in my_holdings:
                                s_data = df[df['商品'] == ticker].iloc[0]
                                p_price = s_data['價格']
                                p_dist = s_data['SMA21_Dist']
                                p_rsi = s_data.get('相對強弱指標 (14) 1天', 'N/A')
                                p_sector = s_data.get('產業', '未知')
                                
                                # 抓取新聞
                                query = urllib.parse.quote(f"{ticker} stock news")
                                feed = feedparser.parse(f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en")
                                n_text = "\n".join([entry.title for entry in feed.entries[:3]]) # 守護者模式看重點新聞即可
                                
                                portfolio_data += f"\n【{ticker}】現價:${p_price:.2f} | 距SMA21:{p_dist:.2f}% | RSI:{p_rsi} | 板塊:{p_sector} | 近期新聞: {n_text}\n"

                            client = genai.Client(api_key=api_key)
                            
                            guardian_prompt = f"""
                            # Role: 證據導向的華爾街 Swing Trading 分析師 (Alpha Focus - 守護者模式)
                            
                            ## 0. 數據審計協議 (Data Integrity Protocol 3.0)
                            以下是我的真實持倉數據：
                            {portfolio_data}
                            基準日：{today_date}
                            
                            ## 1. 核心任務：守護者邏輯
                            請根據提供的數據，判斷趨勢健康度，並給出 Hold(續抱)、Trim(減倉)、Sell(清倉) 或 Add(加倉) 的決定。
                            
                            ## 2. 輸出格式 (請嚴格使用此 Markdown 格式輸出)
                            `[數據源: Google/TradingView | 審計基準日: {today_date} | 美東時間: 盤後]`
                            
                            ### 持倉個股審計表
                            | 代碼 | 最新價格 (% vs SMA21) | 趨勢健康度 (RSI與量價) | 消息與風險矩陣 (Tier 1+2+Risk) | 決策建議 | 守護策略 (止盈/止損) | 評分 |
                            | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
                            (請為我選擇的每一檔股票生成一行分析)
                            
                            ### 3. 持倉組合總結 (Portfolio Playbook)
                            1. **組合風險警告**：[分析板塊集中度與大盤曝險]
                            2. **急迫行動清單**：[列出需要立刻 Trim 或 Sell 的標的]
                            3. **動態止損指南**：[整體的移動止損建議]
                            """
                            
                            g_response = client.models.generate_content(model='gemini-2.5-flash', contents=guardian_prompt)
                            st.success("持倉審計完成！")
                            with st.container(border=True):
                                st.markdown(g_response.text)
                                
                        except Exception as e:
                            st.error(f"分析時發生錯誤: {e}")
        else:
            st.info("請先從上方選擇你目前持有的股票代碼。")

else:
    st.info("👈 請先從左側邊欄上傳你的 TradingView CSV 文件以啟動系統。")

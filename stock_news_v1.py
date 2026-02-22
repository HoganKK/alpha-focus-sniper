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
# ------------------------

st.set_page_config(layout="wide", page_title="Alpha Focus Sniper Dashboard")
st.title("🎯 Alpha Focus 狙擊手可視化儀表板")

# ================= 側邊欄 =================
st.sidebar.header("配置中心")
api_key = st.sidebar.text_input("Gemini API Key", type="password")

st.sidebar.markdown("---")
st.sidebar.info("""
💡 **API 使用提示 (免費版)**
- 速率限制：每分鐘 15 次
- 每日配額：每天 1,500 次
*為節省配額，系統已啟用「歷史紀錄快取」，分析過的標的將自動存檔。*
""")

uploaded_file = st.sidebar.file_uploader("上傳 TradingView CSV", type="csv")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 雲端歷史分析紀錄")
if history:
    for ticker, data in history.items():
        st.sidebar.write(f"✅ **{ticker}** *(分析於 {data['date']})*")
else:
    st.sidebar.caption("目前尚無分析紀錄。")

# ================= 主畫面 =================
if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # 計算狙擊距離與縮量
    df['SMA21_Dist'] = ((df['價格'] - df['簡單移動平均線 (21) 1天']) / df['簡單移動平均線 (21) 1天']) * 100
    df['縮量狀態'] = df['成交量 1天'] < df['平均成交量 10天']
    
    st.subheader("📊 強勢股篩選清單")
    
    # 預先計算 0-5% 狙擊區的標的數量
    sniper_df = df[(df['SMA21_Dist'] >= 0) & (df['SMA21_Dist'] <= 5)]
    sniper_count = len(sniper_df)
    
    # 修改 1, 2, 4: 取消預設勾選，改為 0-5%，並動態顯示數量
    only_sniper = st.checkbox(f"只顯示狙擊區標的 (0-5% 距離) - 🎯 目前符合：{sniper_count} 隻", value=False)
    
    if only_sniper:
        display_df = sniper_df
    else:
        display_df = df

    st.dataframe(display_df[['商品', '價格', 'SMA21_Dist', '縮量狀態', '相對強弱指標 (14) 1天', '價格變化 % 1週', '產業']], 
                 use_container_width=True)

    st.markdown("---")
    st.write("### 🔬 標的深度診斷模組")
    
    # 修改 3: 這裡的下拉選單現在會與上面的 checkbox 連動 (只讀取 display_df)
    if not display_df.empty:
        selected_stock = st.selectbox("請選擇要進行 K線圖與 AI 深度分析的標的：", display_df['商品'].tolist())
        
        stock_data = df[df['商品'] == selected_stock].iloc[0]
        real_price = stock_data['價格']
        real_sma_dist = stock_data['SMA21_Dist']
        real_rsi = stock_data.get('相對強弱指標 (14) 1天', 'N/A')
        real_sector = stock_data.get('產業', '未知')
        today_date = datetime.now().strftime("%Y-%m-%d")

        # 1. 滿版顯示 K 線圖
        st.write(f"#### 📈 {selected_stock} 交互式 K 線圖")
        hist_data = yf.download(selected_stock, period="6mo", interval="1d", progress=False)
        
        if not hist_data.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.03, row_width=[0.3, 0.7])

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
            
            # 隱藏週末斷層，讓 K 線圖連續
            fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
            fig.update_layout(xaxis_rangeslider_visible=False, height=600, showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("無法獲取該股票的歷史數據。")

        # 2. 滿版顯示 AI 診斷報告
        st.markdown("---")
        st.write(f"#### 🧠 Alpha Focus 偵察報告")
        
        # === 歷史紀錄判斷邏輯 ===
        if selected_stock in history:
            st.info(f"📂 目前顯示的是雲端歷史紀錄 (最後分析日期: {history[selected_stock]['date']})。閱讀歷史紀錄不消耗 API。")
            with st.container(border=True):
                st.markdown(history[selected_stock]['content'])
            
            # 提供重新掃描按鈕
            analyze_button = st.button("🔄 重新深度掃描 (更新最新新聞並消耗 API)")
            is_history = True
        else:
            analyze_button = st.button("🚀 啟動數據審計協議 (Data Integrity Protocol)", type="primary")
            is_history = False

        if analyze_button:
            if not api_key:
                st.error("請先在側邊欄輸入 API Key")
            else:
                with st.spinner('正在執行強制搜尋與消息雙語分級排序...'):
                    try:
                        query = urllib.parse.quote(f"{selected_stock} stock news")
                        google_news_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
                        feed = feedparser.parse(google_news_url)
                        
                        news_list = [entry.title for entry in feed.entries[:8]] 
                        if not news_list:
                            news_text = "過去 14 天內無重大新聞。"
                        else:
                            news_text = "\n".join([f"{i+1}. {title}" for i, title in enumerate(news_list)])
                        
                        client = genai.Client(api_key=api_key)
                        
                        # 修改 5: 強制 AI 將新聞按照 Tier 級別排序
                        prompt = f"""
                        # Role: 證據導向的華爾街 Swing Trading 分析師 (Alpha Focus - 偵察模式)
                        
                        ## 0. 數據審計輸入 (Anti-Hallucination)
                        - 標的：{selected_stock}
                        - 實時現價：${real_price:.2f}
                        - 距離 SMA21：{real_sma_dist:.2f}%
                        - RSI (14)：{real_rsi}
                        - 板塊：{real_sector}
                        - 基準日：{today_date}
                        
                        ## 1. 待分析新聞流 (共 {len(news_list)} 條)：
                        {news_text}
                        
                        ## 2. 核心任務與輸出格式要求
                        請嚴格按照以下順序和格式輸出，不要有任何多餘的開場白。
                        
                        ### 第一部分：偵察表格
                        `[偵察基準日: {today_date} | 數據源: Google News / TradingView | 基準價: ${real_price:.2f} | 美東時間: 盤後]`
                        
                        | 代碼 | 板塊 | 公司簡介 | 最新狀態 (Price & % vs SMA21) | 核心催化劑(摘要) | 資金邏輯 | 狀態評價 | 評分 |
                        | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
                        | {selected_stock} | {real_sector} | [在此填寫50字內主營業務與核心產品] | **${real_price:.2f}** ({real_sma_dist:.2f}%) | [一句話總結 Tier 1 或 Risk] | [分析資金湧入或撤出的邏輯] | [超買 / 剛突破 / 拋物線 / 健康回踩] | [1-100] |
                        
                        ### 第二部分：消息與風險矩陣明細 (雙語對照)
                        請將上述新聞逐一進行評級，分為 🚀 Tier 1 (估值重構/重大消息)、⚡ Tier 2 (趨勢助推/升評)、⚪ Tier 3 (一般雜訊) 或 ⚠️ Risk (破位/財報風險/負面新聞)。
                        
                        **【重要排序指令】：你必須將分析完的新聞重新排序！將最重要的放在最上面，最危險的放在最下面。順序必須嚴格為：1. 🚀 Tier 1 -> 2. ⚡ Tier 2 -> 3. ⚪ Tier 3 -> 4. ⚠️ Risk。**
                        
                        必須嚴格採用以下排版格式，顯示原始英文與中文翻譯：
                        
                        - 🚀 **[Tier 1]** (Original English Title Here)
                          - **中文翻譯**：[在此輸出準確的繁體中文翻譯]
                          - **分析點評**：[解釋為何給予此評級，利多/利空是否依然有效？]
                          
                        (請依序向下排列所有新聞，不要遺漏)
                        """
                        
                        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                        
                        # 儲存到歷史紀錄
                        history[selected_stock] = {
                            "date": today_date,
                            "content": response.text
                        }
                        save_history(history)
                        
                        st.success("審計完成！已存入歷史紀錄快取中。")
                        with st.container(border=True):
                            st.markdown(response.text)
                            
                    except Exception as e:
                        st.error(f"分析時發生錯誤: {e}")
    else:
        st.info("⚠️ 目前篩選條件下沒有符合的標的。")
else:
    st.info("👈 請先從左側邊欄上傳你的 TradingView CSV 文件以啟動系統。")

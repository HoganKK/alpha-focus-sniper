import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from google import genai
import feedparser
import urllib.parse
from datetime import datetime

st.set_page_config(layout="wide", page_title="Alpha Focus Sniper Dashboard")

st.title("🎯 Alpha Focus 狙擊手可視化儀表板")

st.sidebar.header("配置中心")
api_key = st.sidebar.text_input("Gemini API Key", type="password")
uploaded_file = st.sidebar.file_uploader("上傳 TradingView CSV", type="csv")

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    
    # 計算狙擊距離與縮量
    df['SMA21_Dist'] = ((df['價格'] - df['簡單移動平均線 (21) 1天']) / df['簡單移動平均線 (21) 1天']) * 100
    df['縮量狀態'] = df['成交量 1天'] < df['平均成交量 10天']
    
    st.subheader("📊 強勢股篩選清單")
    only_sniper = st.checkbox("只顯示狙擊區標的 (0-6% 距離)", value=True)
    if only_sniper:
        display_df = df[(df['SMA21_Dist'] >= 0) & (df['SMA21_Dist'] <= 6)]
    else:
        display_df = df

    st.dataframe(display_df[['商品', '價格', 'SMA21_Dist', '縮量狀態', '相對強弱指標 (14) 1天', '價格變化 % 1週', '產業']], 
                 use_container_width=True)

    # ================= UI 調整：滿版圖表與報告區 =================
    st.markdown("---")
    st.write("### 🔬 標的深度診斷模組")
    selected_stock = st.selectbox("請選擇要進行 K線圖與 AI 深度分析的標的：", df['商品'].tolist())
    
    # 提取該標的的真實 CSV 數據，防止 AI 幻覺
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
                            vertical_spacing=0.03,
                            row_width=[0.3, 0.7])

        open_p = hist_data['Open'].squeeze()
        high_p = hist_data['High'].squeeze()
        low_p = hist_data['Low'].squeeze()
        close_p = hist_data['Close'].squeeze()
        volume_p = hist_data['Volume'].squeeze()

        fig.add_trace(go.Candlestick(x=hist_data.index,
                        open=open_p, high=high_p, low=low_p, close=close_p, 
                        name='K線'), row=1, col=1)
        
        sma21 = close_p.rolling(window=21).mean()
        fig.add_trace(go.Scatter(x=hist_data.index, y=sma21, 
                                 line=dict(color='orange', width=2), name='SMA21'), row=1, col=1)
        
        colors = ['green' if c >= o else 'red' for c, o in zip(close_p, open_p)]
        fig.add_trace(go.Bar(x=hist_data.index, y=volume_p, 
                             marker_color=colors, name='成交量'), row=2, col=1)
        
        fig.update_layout(xaxis_rangeslider_visible=False, height=600, showlegend=False, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("無法獲取該股票的歷史數據。")

    # 2. 滿版顯示 AI 診斷報告 (圖表下方)
    st.markdown("---")
    st.write(f"#### 🧠 Alpha Focus 偵察報告")
    
    if st.button("啟動數據審計協議 (Data Integrity Protocol)", type="primary"):
        if not api_key:
            st.error("請先在側邊欄輸入 API Key")
        else:
            with st.spinner('正在執行強制搜尋與消息雙語分級...'):
                try:
                    # 抓取 Google 財經新聞 RSS (最多 8 條)
                    query = urllib.parse.quote(f"{selected_stock} stock news")
                    google_news_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
                    feed = feedparser.parse(google_news_url)
                    
                    news_list = [entry.title for entry in feed.entries[:8]] 
                    
                    if not news_list:
                        news_text = "過去 14 天內無重大新聞。"
                    else:
                        news_text = "\n".join([f"{i+1}. {title}" for i, title in enumerate(news_list)])
                    
                    client = genai.Client(api_key=api_key)
                    
                    # 重新排版 Prompt，分離表格與雙語新聞清單
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
                    
                    | 代碼 | 板塊/定位 | 最新狀態 (Price & % vs SMA21) | 核心催化劑(摘要) | 資金邏輯 | 狀態評價 | 評分 |
                    | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
                    | {selected_stock} | {real_sector} / [50字內定位] | **${real_price:.2f}** ({real_sma_dist:.2f}%) | [用一句話總結最關鍵的 Tier 1 或 Risk] | [分析資金湧入或撤出的邏輯] | [超買 / 剛突破 / 拋物線 / 健康回踩] | [1-100] |
                    
                    ### 第二部分：消息與風險矩陣明細 (雙語對照)
                    請將上述新聞逐一進行評級，分為 🚀 Tier 1 (估值重構)、⚡ Tier 2 (趨勢助推) 或 ⚠️ Risk (破位/財報風險)，若為無關雜訊可標註 ⚪ Tier 3。
                    必須嚴格採用以下排版格式，顯示原始英文與中文翻譯：
                    
                    - 🚀 **[Tier 1]** (Original English Title Here)
                      - **中文翻譯**：[在此輸出準確的繁體中文翻譯]
                      - **分析點評**：[解釋為何給予此評級，利多/利空是否依然有效？]
                      
                    - ⚡ **[Tier 2]** (Original English Title Here)
                      - **中文翻譯**：[在此輸出準確的繁體中文翻譯]
                      - **分析點評**：[解釋為何給予此評級]
                      
                    (請依序列出所有新聞)
                    """
                    
                    response = client.models.generate_content(
                        model='gemini-2.5-flash', 
                        contents=prompt
                    )
                    st.success("審計完成！")
                    
                    # 為了視覺美觀，將報告放在一個稍微突出的區塊內
                    with st.container(border=True):
                        st.markdown(response.text)
                except Exception as e:
                    st.error(f"分析時發生錯誤: {e}")

else:
    st.info("👈 請先從左側邊欄上傳你的 TradingView CSV 文件以啟動系統。")

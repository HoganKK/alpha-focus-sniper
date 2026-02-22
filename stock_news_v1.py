import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
from google import genai
import feedparser
import urllib.parse
import os

# --- 如果你在香港/無法直接連線的地區，請解除下面兩行的註解，並換成你的 Proxy 埠號 ---
# os.environ['http_proxy'] = 'http://127.0.0.1:7890'
# os.environ['https_proxy'] = 'http://127.0.0.1:7890'

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

    st.dataframe(
        display_df[['商品', '價格', 'SMA21_Dist', '縮量狀態', '相對強弱指標 (14) 1天', '價格變化 % 1週', '產業']],
        use_container_width=True)

    col1, col2 = st.columns([2, 1])
    selected_stock = st.selectbox("選擇標的進行深度診斷", df['商品'].tolist())

    with col1:
        st.write(f"### 📈 {selected_stock} 交互式 K 線圖")
        hist_data = yf.download(selected_stock, period="6mo", interval="1d", progress=False)

        if not hist_data.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                vertical_spacing=0.03, subplot_titles=(f'{selected_stock} 價格', '成交量'),
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

            fig.update_layout(xaxis_rangeslider_visible=False, height=650, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("無法獲取該股票的歷史數據。")

    with col2:
        st.write(f"### 🧠 AI 消息面審計")
        if st.button("啟動 Gemini 診斷"):
            if not api_key:
                st.error("請先在側邊欄輸入 API Key")
            else:
                with st.spinner('正在從 Google News 抓取情報並由 Gemini 分析中...'):
                    try:
                        # 1. 抓取 Google 財經新聞 RSS
                        query = urllib.parse.quote(f"{selected_stock} stock news")
                        google_news_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
                        feed = feedparser.parse(google_news_url)

                        news_list = [entry.title for entry in feed.entries[:5]]

                        if not news_list:
                            news_text = "Google News 近期無重大新聞。"
                        else:
                            news_text = "\n".join([f"- {title}" for title in news_list])

                        # 2. Gemini 分析
                        client = genai.Client(api_key=api_key)
                        prompt = f"你是華爾街分析師，評估 {selected_stock} 的最新消息。以下來自 Google News：\n{news_text}\n請給出評分(0-100)、Tier等級(1-3)和一句话策略建議。"

                        response = client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=prompt
                        )
                        st.success("分析完成！")
                        st.info(response.text)
                    except Exception as e:
                        st.error(f"分析時發生錯誤: {e}")
else:
    st.warning("請先從側邊欄上傳你的 TradingView CSV 文件。")
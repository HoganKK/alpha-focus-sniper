import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
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
import re
import numpy as np
from fpdf import FPDF

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

# --- PDF 生成引擎 (V12.6 排版緊湊優化版) ---
class PDF(FPDF):
    def header(self):
        font_path = "font.ttf"
        if os.path.exists(font_path):
            try:
                self.add_font('CustomFont', '', font_path, uni=True)
                self.set_font('CustomFont', '', 14)
            except:
                self.set_font('Arial', 'B', 14)
        else:
            self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Alpha Focus Institutional Report', 0, 1, 'C')
        self.ln(5) # 標題後留一點點空間

def remove_unsupported_chars(text):
    # 保留基本標點與換行，移除特殊繪文字
    return re.sub(r'[^\w\s,.，。：:!！?？()（）\-\[\]%$\n]', '', text)

def generate_pdf_report(content, filename="report.pdf"):
    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    font_path = "font.ttf"
    font_ready = False
    
    if os.path.exists(font_path):
        try:
            pdf.add_font('CustomFont', '', font_path, uni=True) 
            pdf.set_font('CustomFont', '', 10) # 預設字體縮小一點，更像研報
            font_ready = True
        except:
            pdf.set_font('Arial', '', 10)
    else:
        pdf.set_font('Arial', '', 10)
    
    # 智能解析內容
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        clean_line = remove_unsupported_chars(line)
        
        # 1. 處理空行：給一點點間距，不要太大
        if not clean_line:
            pdf.ln(2) 
            continue
            
        # 2. 處理標題 (##)
        if line.startswith('#'):
            clean_text = clean_line.replace('#', '').strip()
            pdf.ln(3) # 標題前加一點空間
            pdf.set_font_size(13) # 字體加大
            try:
                pdf.multi_cell(0, 8, clean_text) # 標題行高略大
            except: pass
            pdf.set_font_size(10) # 回復內文字體大小
            
        # 3. 處理列表 (* 或 -)
        elif line.startswith('* ') or line.startswith('- '):
            clean_text = clean_line[1:].strip() # 去掉符號
            pdf.set_x(15) # 縮排效果
            try:
                pdf.multi_cell(0, 5, f"- {clean_text}") # 列表行高設為 5 (緊湊)
            except: pass
            
        # 4. 處理強調文字 (** 或 數字開頭)
        elif line.startswith('**') or re.match(r'^\d+\.', line):
            clean_text = line.replace('**', '').replace('##', '')
            clean_text = remove_unsupported_chars(clean_text)
            pdf.ln(1) # 小間隔
            try:
                pdf.multi_cell(0, 6, clean_text) # 重點文字行高 6
            except: pass
            
        # 5. 普通內文
        else:
            clean_text = line.replace('**', '')
            clean_text = remove_unsupported_chars(clean_text)
            try:
                pdf.multi_cell(0, 5, clean_text) # 內文行高 5 (最緊湊)
            except: pass

    pdf.output(filename)
    return font_ready

# --- 核心引擎：Finnhub ---
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
                if title: news_list.append(f"【{title}】 {summary}...")
            return news_list
    except: return []
    return []

# --- 三源新聞聚合器 ---
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

# --- 🚀 Rocket Signal (前身 Antman) 計算引擎 ---
def calculate_rocket_signal(hist_data):
    if len(hist_data) < 25: return False, "數據不足"
    recent = hist_data.tail(5)
    if len(recent) < 5: return False, "數據不足"
    
    closes = recent['Close'].values
    days_up = 0
    for i in range(1, 5):
        if closes[i] > closes[i-1]: days_up += 1
    
    start_price = closes[0] if closes[0] != 0 else 0.01
    price_change_4d = (closes[-1] - start_price) / start_price
    momentum_pass = bool((days_up >= 3) and (price_change_4d > 0.06))
    
    vol = hist_data['Volume']
    avg_vol_4d = float(vol.tail(4).mean())
    avg_vol_20d = float(vol.tail(24).iloc[:-4].mean())
    if avg_vol_20d == 0: avg_vol_20d = 1.0
    volume_pass = bool(avg_vol_4d > (avg_vol_20d * 1.15))
    
    opens = recent['Open'].values
    bull_days = 0
    for i in range(1, 5):
        if closes[i] > opens[i]: bull_days += 1
    power_pass = bool(bull_days >= 3)
    
    is_rocket = momentum_pass and volume_pass and power_pass
    signal_text = "🚀 **Rocket 訊號爆發!** (動能+量能確認)" if is_rocket else "⚪ 無特殊訊號"
    return is_rocket, signal_text

# --- 🚀 RRG 核心算法 ---
def calculate_rrg_data(tickers, benchmark_symbol="SPY", period="6mo"):
    all_symbols = tickers + [benchmark_symbol]
    try:
        data = yf.download(all_symbols, period=period, interval="1d", progress=False)['Close']
    except:
        return pd.DataFrame()

    if data.empty or benchmark_symbol not in data.columns:
        return pd.DataFrame()

    rrg_results = []
    benchmark_series = data[benchmark_symbol]
    
    for ticker in tickers:
        if ticker not in data.columns: continue
        
        rs_series = data[ticker] / benchmark_series
        rs_ma = rs_series.rolling(window=10).mean()
        rs_ratio = (rs_series / rs_ma) * 100
        rs_momentum = (rs_ratio / rs_ratio.shift(1)) * 100
        
        if len(rs_ratio) > 0 and not pd.isna(rs_ratio.iloc[-1]):
            latest_ratio = rs_ratio.iloc[-1]
            latest_mom = rs_momentum.iloc[-1]
            
            quadrant = ""
            if latest_ratio > 100 and latest_mom > 100: quadrant = "Leading (領先)" 
            elif latest_ratio > 100 and latest_mom < 100: quadrant = "Weakening (轉弱)"
            elif latest_ratio < 100 and latest_mom < 100: quadrant = "Lagging (落後)"
            elif latest_ratio < 100 and latest_mom > 100: quadrant = "Improving (改善)"
            
            rrg_results.append({
                "Ticker": ticker,
                "RS_Ratio": latest_ratio,
                "RS_Momentum": latest_mom,
                "Quadrant": quadrant
            })
            
    return pd.DataFrame(rrg_results)

# --- IBD RS Rating ---
@st.cache_data(ttl=3600)
def get_macro_benchmark():
    spy = yf.download("SPY", period="1y", interval="1d", progress=False)
    vix = yf.download("^VIX", period="1mo", interval="1d", progress=False)
    spy_close = spy['Close'].squeeze() if not spy.empty else None
    vix_close = vix['Close'].squeeze() if not vix.empty else None
    return spy_close, vix_close

def calculate_rs_rating(stock_close, spy_close):
    if stock_close is None or spy_close is None or len(stock_close) < 10 or len(spy_close) < 10: return 50
    n63 = min(63, len(stock_close)-1, len(spy_close)-1)
    n126 = min(126, len(stock_close)-1, len(spy_close)-1)
    n189 = min(189, len(stock_close)-1, len(spy_close)-1)
    n252 = min(252, len(stock_close)-1, len(spy_close)-1)
    
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
    if df.empty: return 0, 0, 0, 50, None
    close = df['Close'].squeeze()
    
    current_price = float(close.iloc[-1])
    sma21 = float(close.rolling(21).mean().iloc[-1])
    dist = ((current_price - sma21) / sma21) * 100
    
    delta = close.diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
    rsi = 100 - (100 / (1 + rs)).iloc[-1]
    rs_rating = calculate_rs_rating(close, spy_close)
    
    return current_price, dist, float(rsi), float(rs_rating), df 

# ================= 網頁主體 =================
if "stock_selector" not in st.session_state: st.session_state.stock_selector = None

st.set_page_config(layout="wide", page_title="Alpha Focus Trading System")
st.title("🦅 Alpha Focus 三引擎量化交易系統 v12.6 (PDF排版緊湊版)")

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
if st.sidebar.button("🧹 清除失敗快取 (重新掃描)"):
    keys_to_delete = [k for k, v in history.items() if "拒絕" in v.get("content", "") or "保留基礎數據" in v.get("content", "") or "⚠️" in v.get("content", "")]
    if keys_to_delete:
        for k in keys_to_delete: del history[k]
        save_history(history)
        st.sidebar.success(f"✅ 已清除 {len(keys_to_delete)} 筆失敗紀錄！")
        time.sleep(1)
        st.rerun()
    else:
        st.sidebar.info("目前沒有失敗的快取。")

spy_data, vix_data = get_macro_benchmark()
vix_current = float(vix_data.iloc[-1]) if vix_data is not None else 20.0

# ================= 三分頁架構 =================
tab_read, tab1, tab2, tab3 = st.tabs(["📖 沉浸閱讀器", "🎯 單股深度 (Rocket)", "🛡️ 守護者 (交通燈)", "🗺️ 全景戰略 (RRG)"])

# ---------------------------------------------------------
# TAB 0: 📖 沉浸閱讀器
# ---------------------------------------------------------
with tab_read:
    available_tickers = [k for k in history.keys() if not k.startswith("_MACRO_")]
    if not available_tickers:
        st.info("目前無報告，請先至【宏觀與全景戰略】進行掃描。")
    else:
        st.write("### 🧠 機構級報告閱讀區")
        if 'reader_index' not in st.session_state: st.session_state.reader_index = 0
        if st.session_state.reader_index >= len(available_tickers): st.session_state.reader_index = 0

        col_prev, col_sel, col_next = st.columns([1, 4, 1])
        with col_prev:
            if st.button("⬅️ 上一檔", use_container_width=True):
                if st.session_state.reader_index > 0:
                    st.session_state.reader_index -= 1
                    st.rerun()
        with col_next:
            if st.button("下一檔 ➡️", use_container_width=True):
                if st.session_state.reader_index < len(available_tickers) - 1:
                    st.session_state.reader_index += 1
                    st.rerun()
        with col_sel:
            selected_read_ticker = st.selectbox("快速跳轉：", options=available_tickers, index=st.session_state.reader_index, label_visibility="collapsed")
            if selected_read_ticker != available_tickers[st.session_state.reader_index]:
                st.session_state.reader_index = available_tickers.index(selected_read_ticker)
                st.rerun()

        current_ticker = available_tickers[st.session_state.reader_index]
        report_data = history[current_ticker]
        raw_content = report_data['content']
        formatted_content = raw_content.replace("**🏢", "\n\n---\n**🏢").replace("**🛡️", "\n\n**🛡️").replace("**🧠", "\n\n**🧠").replace("**📰", "\n\n---\n**📰")
        clean_content = formatted_content.replace("$", "").replace("{", "").replace("}", "").replace("\%", "%")
        
        try:
            price_match = re.search(r"價格[：:]\s*(\d+\.?\d*)", clean_content)
            dist_match = re.search(r"距SMA21[：:]\s*(-?\d+\.?\d*)", clean_content)
            rs_match = re.search(r"RS評級[：:]\s*(\d+)", clean_content)
            p_val = price_match.group(1) if price_match else "N/A"
            d_val = dist_match.group(1) + "%" if dist_match else "N/A"
            r_val = rs_match.group(1) if rs_match else "N/A"
            st.markdown("---")
            m1, m2, m3 = st.columns(3)
            m1.metric("當前價格", f"${p_val}")
            m2.metric("SMA21 乖離率", d_val)
            m3.metric("IBD RS Rating", r_val, help="99為最強")
        except: pass 

        st.subheader(f"🎯 {current_ticker} 深度報告")
        with st.container(border=True): st.markdown(clean_content)

# ---------------------------------------------------------
# TAB 1: 單股深度偵察 (Rocket Signal)
# ---------------------------------------------------------
with tab1:
    st.info("單股深度 K 線圖與報告區域。")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        df['SMA21_Dist_Num'] = (((df['價格'] - df['簡單移動平均線 (21) 1天']) / df['簡單移動平均線 (21) 1天']) * 100).round(2)
        df['縮量狀態'] = df['成交量 1天'] < df['平均成交量 10天']
        display_df = df.copy()
        display_df['SMA21_Dist'] = display_df['SMA21_Dist_Num'].apply(lambda x: f"{x:.2f}%")
        
        sniper_mask = (df['SMA21_Dist_Num'] >= 0) & (df['SMA21_Dist_Num'] <= 5)
        only_sniper = st.checkbox(f"🎯 只顯示狙擊區標的 (0-5% 距離)", value=False)
        view_df = display_df[sniper_mask] if only_sniper else display_df
        calc_df = df[sniper_mask] if only_sniper else df
        st.dataframe(view_df[['商品', '價格', 'SMA21_Dist', '縮量狀態', '產業']], use_container_width=True, hide_index=True)

        st.markdown("---")
        options = calc_df['商品'].tolist()
        if options:
            if "stock_selector" not in st.session_state or st.session_state.stock_selector not in options:
                st.session_state.stock_selector = options[0]
            selected_stock = st.selectbox("選擇標的：", options, key="stock_selector")
            
            real_price, real_sma_dist, real_rsi, real_rs_rating, stock_hist_df = get_dynamic_stats(selected_stock, spy_data)
            
            # 🚀 計算 Rocket Signal
            if stock_hist_df is not None:
                is_rocket, rocket_text = calculate_rocket_signal(stock_hist_df)
                if is_rocket: st.success(rocket_text)
                else: st.info(rocket_text)
            else:
                rocket_text = "無法獲取歷史數據"

            today_date = datetime.now().strftime("%Y-%m-%d")
            
            hist_data = yf.download(selected_stock, period="6mo", interval="1d", progress=False)
            if not hist_data.empty:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_width=[0.3, 0.7])
                fig.add_trace(go.Candlestick(x=hist_data.index, open=hist_data['Open'].squeeze(), high=hist_data['High'].squeeze(), low=hist_data['Low'].squeeze(), close=hist_data['Close'].squeeze(), name='K線'), row=1, col=1)
                st.plotly_chart(fig, use_container_width=True)

            if st.button("🚀 單股強制更新 (覆蓋快取)", type="primary"):
                if not api_key: st.error("請輸入 API Key")
                else:
                    with st.spinner("分析中..."):
                        try:
                            news_pool = get_triple_engine_news(selected_stock, fh_api_key)
                            news_text = "\n".join(news_pool) if news_pool else "無重大新聞"
                            client = OpenAI(api_key=api_key, base_url="https://xiaoai.plus/v1")
                            prompt = f"""
                            分析 {selected_stock} (現價:{real_price}, RS:{real_rs_rating}, 距SMA21:{real_sma_dist}%)。
                            技術訊號: {rocket_text} (若為 Rocket Signal，請強調動能爆發的可能性)。
                            新聞流: {news_text}
                            請嚴格按 Markdown 格式輸出：
                            1. 公司簡介
                            2. 數據校驗 (包含 Rocket 訊號解讀)
                            3. 動能剖析
                            4. Tier1-3 新聞矩陣 (每則新聞提供 2-3 行詳盡分析)
                            """
                            res = client.chat.completions.create(model='gemini-2.5-flash', messages=[{"role":"user","content":prompt}])
                            history[selected_stock] = {"date": today_date, "content": res.choices[0].message.content, "info_str": f"單股更新"}
                            save_history(history)
                            st.success("更新完成！")
                        except Exception as e: st.error(str(e))
# ---------------------------------------------------------
# TAB 2: 守護者模式 (交通燈風控 + Rocket 監測)
# ---------------------------------------------------------
with tab2:
    st.subheader("🛡️ 守護者模式：持倉健檢與交通燈風控")
    if futu_file:
        futu_df = pd.read_csv(futu_file)
        my_holdings = futu_df['代碼'].astype(str).tolist()
        st.write("已成功載入您的富途持倉。")
        selected_holdings = st.multiselect("選擇持倉進行審計：", my_holdings, default=my_holdings)

        if st.button("🛡️ 執行持倉組合審計 (Portfolio Audit)", type="primary"):
            if not api_key: st.error("請確保已設定 API Key！")
            else:
                with st.spinner('正在進行交通燈風控與 Rocket 訊號運算...'):
                    try:
                        portfolio_data = ""
                        today_date = datetime.now().strftime("%Y-%m-%d")
                        
                        for ticker in selected_holdings:
                            row = futu_df[futu_df['代碼'] == ticker].iloc[0]
                            cost_price = row.get('攤薄成本價', 'N/A')
                            profit_pct = row.get('盈虧比例', 'N/A')
                            
                            # 獲取動態數據與 Rocket 訊號
                            curr_price, dist, rsi, rs_rating, stock_hist = get_dynamic_stats(ticker, spy_data)
                            is_rocket, rocket_txt = calculate_rocket_signal(stock_hist)
                            rocket_status = "🔥 ROCKET TRIGGERED" if is_rocket else "Normal"
                            
                            news_pool = get_triple_engine_news(ticker, fh_api_key, fh_limit=3, g_limit=2, y_limit=2)
                            n_text = "\n".join(news_pool) if news_pool else "無重大新聞"
                            
                            portfolio_data += f"\n====================\n【{ticker}】\n- 成本: ${cost_price} | 盈虧: {profit_pct}\n- 現價: ${curr_price:.2f} | 距SMA21: {dist:.2f}% | RS: {rs_rating:.0f}\n- 技術狀態: {rocket_status}\n- 新聞流:\n{n_text}\n"

                        client = OpenAI(api_key=api_key, base_url="https://xiaoai.plus/v1")
                        
                        guardian_prompt = f"""
                        # Role: 證據導向的華爾街風險控制官 (Risk Manager)
                        
                        ## 1. 市場環境判斷 (Traffic Light System)
                        當前 VIX 指數為: {vix_current:.2f}。
                        請根據 VIX 水平判定當前操作環境：
                        - **🟢 綠燈 (Easy Dollar)**: VIX < 15，建議倉位 75-100%，止損 -3%~-5%。
                        - **🟡 黃燈 (Neutral)**: VIX 15-20，建議倉位 50-75%，止損 -2%~-3%。
                        - **🔴 紅燈 (Hard Penny)**: VIX > 20，建議倉位 0-50%，止損 -1%~-2%，現金為王。
                        
                        ## 2. 持倉審計數據
                        {portfolio_data}
                        基準日：{today_date}
                        
                        ## 3. 輸出要求
                        請先給出 **「🚦 市場交通燈狀態」** 與 **「💰 建議總倉位上限」**。
                        
                        接著輸出持倉表格：
                        | 代碼 | 狀態 (% vs SMA21) | Rocket訊號 | 建議操作 (加倉/減倉/止損) | 具體止損位 |
                        
                        最後提供一段「組合風險總結」，若持有 Rocket 訊號股，請建議如何利用移動止損鎖定利潤。
                        """
                        
                        g_response = client.chat.completions.create(model='gemini-2.5-flash', messages=[{"role": "user", "content": guardian_prompt}])
                        st.success("審計完成！")
                        with st.container(border=True): st.markdown(g_response.choices[0].message.content)
                    
                    except Exception as e: st.error(f"分析錯誤: {e}")
    else: st.info("👈 請上傳您的富途持倉 CSV。")

# ---------------------------------------------------------
# TAB 3: 宏觀與全景戰略 (深度復刻版)
# ---------------------------------------------------------
with tab3:
    st.subheader("🗺️ 宏觀與全景戰略 (Alpha Focus Playbook)")
    
    if 'auto_scan' not in st.session_state: st.session_state.auto_scan = False

    if uploaded_file:
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file)
        df['產業'] = df['產業'].fillna('未知') if '產業' in df.columns else '未知'
        target_list = df['商品'].tolist()
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        uncached_list = [t for t in target_list if t not in history or history[t].get('date') != today_date]
        cached_count = len(target_list) - len(uncached_list)
        
        st.info(f"📊 總進度：{cached_count}/{len(target_list)} 已存檔")
        st.progress(cached_count / len(target_list) if len(target_list) > 0 else 0)
        
        # --- 自動掃描區塊 ---
        if len(uncached_list) > 0:
            batch_size = 5 
            current_batch = uncached_list[:batch_size]
            st.write(f"👉 當前任務: {', '.join(current_batch)}")
            
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
                if not api_key: st.error("無 API Key")
                else:
                    client = OpenAI(api_key=api_key, base_url="https://xiaoai.plus/v1")
                    
                    with st.expander("💻 系統日誌", expanded=True):
                        log_area = st.empty()
                        if 'log_history' not in st.session_state: st.session_state.log_history = []
                        def update_log(msg):
                            time_str = datetime.now().strftime('%H:%M:%S')
                            st.session_state.log_history.insert(0, f"[{time_str}] {msg}")
                            if len(st.session_state.log_history) > 15: st.session_state.log_history.pop()
                            log_area.text_area("Log:", value="\n".join(st.session_state.log_history), height=250, disabled=True, label_visibility="collapsed")
                    
                    update_log(f"📦 正在打包 {len(current_batch)} 隻標的...")
                    all_tickers_data = ""
                    format_instructions = ""
                    
                    for ticker in current_batch:
                        sector = df[df['商品'] == ticker]['產業'].iloc[0]
                        curr_price, dist, rsi, rs_rating, stock_hist = get_dynamic_stats(ticker, spy_data)
                        
                        # 🚀 計算 Rocket 訊號
                        is_rocket, rocket_txt = calculate_rocket_signal(stock_hist)
                        rocket_tag = "[ROCKET!]" if is_rocket else ""
                        
                        news_pool = get_triple_engine_news(ticker, fh_api_key, fh_limit=3, g_limit=1, y_limit=1)
                        news_text = "無重大新聞" if not news_pool else " | ".join(news_pool)
                        
                        all_tickers_data += f"【{ticker}】{rocket_tag}\n價格:{curr_price}, RS:{rs_rating:.0f}, 距SMA21:{dist:.2f}%, 板塊:{sector}\n新聞: {news_text}\n\n"
                        format_instructions += f"---START_REPORT_{ticker}---\n(內容)\n---END_REPORT_{ticker}---\n\n"

                    # 🚀 個股分析 Prompt
                    mega_prompt = f"""
                    # Role: 頂尖波段交易分析師 (Alpha Focus)
                    ## 數據清單：
                    {all_tickers_data}
                    ## ⚠️ 輸出格式要求 (絕對嚴格遵守)：
                    這批次你需要輸出的標籤結構如下：
                    {format_instructions}
                    
                    在每一個專屬標籤內部，請嚴格套用以下 Markdown 模板：
                    **🏢 公司簡介**：[一句話簡述]
                    **🛡️ 數據校驗**：* 價格：${{[填入價格]}} * 距SMA21：{{[填入距離]}}% * RS評級：{{[填入RS]}}
                    **🧠 動能與風險剖析**：[結合數據校驗給出判斷，若有 [ROCKET!] 標籤請特別強調]
                    **📰 核心新聞矩陣**：
                    (必須抄寫新聞來源。每則 Tier 1/2/3 新聞請提供 **2-3 行詳盡分析**，包含具體數據、事件背景與對股價的潛在影響。)
                    * 🚀 **[Tier 1 動能催化]** [來源標籤] [英文標題] - [詳細中文分析]
                    * ⚡ **[Tier 2 潛在影響]** [來源標籤] [英文標題] - [詳細中文分析]
                    * ⚪ **[Tier 3 普遍資訊]** [來源標籤] [英文標題] - [詳細中文分析]
                    * ⚠️ **[Risk 風險警告]** [來源標籤] [英文標題] - [詳細中文分析]
                    """

                    mega_success = False
                    full_response_text = ""
                    for attempt in range(1, 4):
                        try:
                            response = client.chat.completions.create(model='gemini-2.5-flash', messages=[{"role": "user", "content": mega_prompt}])
                            full_response_text = response.choices[0].message.content
                            update_log("✅ 批次 AI 審計完畢，開始解析...")
                            mega_success = True
                            break 
                        except Exception as e:
                            if "429" in str(e):
                                update_log(f"🛑 觸發限流，強制深睡 65 秒... (重試 {attempt}/3)")
                                time.sleep(65)
                            else:
                                update_log(f"⚠️ 發生未知錯誤: {e}")
                                break
                    
                    if mega_success:
                        for ticker in current_batch:
                            start_marker = f"---START_REPORT_{ticker}---"
                            end_marker = f"---END_REPORT_{ticker}---"
                            parsed_content = ""
                            if start_marker in full_response_text and end_marker in full_response_text:
                                try: parsed_content = full_response_text.split(start_marker)[1].split(end_marker)[0].strip()
                                except: parsed_content = "⚠️ 解析失敗"
                            else:
                                pattern = rf"---\s*START_REPORT_{ticker}\s*---(.*?)---\s*END_REPORT_{ticker}\s*---"
                                match = re.search(pattern, full_response_text, re.IGNORECASE | re.DOTALL)
                                if match: parsed_content = match.group(1).strip()
                                else: parsed_content = "⚠️ AI 無視標籤"

                            # 重新計算一次 Rocket Tag 以確保 info_str 正確 (帶入大報告)
                            sector = df[df['商品'] == ticker]['產業'].iloc[0]
                            curr_price, dist, rsi, rs_rating, stock_hist = get_dynamic_stats(ticker, spy_data)
                            is_rocket, _ = calculate_rocket_signal(stock_hist)
                            rocket_str = "🚀" if is_rocket else ""
                            
                            history[ticker] = {
                                "date": today_date,
                                "content": parsed_content,
                                "info_str": f"【{ticker}】{rocket_str} 板塊:{sector} | 距SMA21:{dist:.2f}% | RS:{rs_rating:.0f}"
                            }
                        save_history(history)
                        update_log(f"💾 存檔成功！冷卻 15 秒...")
                        time.sleep(15) 
                        st.rerun()
                    else:
                        st.session_state.auto_scan = False
                        st.rerun()

        # --- 全景報告區塊 (深度復刻版) ---
        else:
            st.success("✨ 所有標的已掃描完畢！")
            
            # RRG 圖表區塊
            st.markdown("### 🔄 資金輪動雷達 (RRG 象限圖)")
            if st.button("📈 生成 RRG 動態圖表"):
                with st.spinner("正在計算 RRG 相對強度輪動..."):
                    rrg_df = calculate_rrg_data(target_list)
                    if not rrg_df.empty:
                        fig_rrg = px.scatter(
                            rrg_df, x="RS_Ratio", y="RS_Momentum", 
                            color="Quadrant", hover_name="Ticker",
                            title="Relative Rotation Graph (vs SPY)",
                            color_discrete_map={"Leading (領先)": "green", "Weakening (轉弱)": "orange", "Lagging (落後)": "red", "Improving (改善)": "blue"}
                        )
                        fig_rrg.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
                        fig_rrg.add_vline(x=100, line_dash="dash", line_color="gray", opacity=0.5)
                        st.plotly_chart(fig_rrg, use_container_width=True)
                    else: st.error("數據不足無法生成 RRG。")

            # 強制重掃按鈕
            if st.button("🔄 強制重新掃描今日清單 (清除當前名單快取)", type="secondary"):
                for ticker in target_list:
                    if ticker in history: del history[ticker]
                macro_key = f"_MACRO_REPORT_{today_date}"
                if macro_key in history: del history[macro_key]
                save_history(history)
                st.rerun()
            
            st.markdown("---")
            macro_cache_key = f"_MACRO_REPORT_{today_date}"
            st.markdown(f"### 🗺️ 終極全景戰略大報告 ({today_date})") 
            
            col_report_1, col_report_2 = st.columns([1, 1])
            report_placeholder = st.empty()
            
            report_content = ""
            if macro_cache_key in history:
                report_content = history[macro_cache_key]['content']
                report_placeholder.success("🎉 已載入今日報告 (快取)")
                with report_placeholder.container(): st.markdown(report_content)
                
                with col_report_2:
                    pdf_file_name = f"Alpha_Focus_Report_{today_date}.pdf"
                    st.download_button("📥 下載 Markdown", report_content, file_name=f"Report_{today_date}.md")
                    if st.button("📄 生成 PDF"):
                        font_ready = generate_pdf_report(report_content, pdf_file_name)
                        if font_ready: 
                            with open(pdf_file_name, "rb") as f: st.download_button("下載 PDF", f, file_name=pdf_file_name)
                        else: st.warning("⚠️ 未檢測到中文字體檔 (font.ttf)。")
            
            with col_report_1:
                force_regen = st.button("🔄 生成/更新 全景報告 (消耗 API)")

            if force_regen:
                if not api_key: st.error("請輸入 API Key！")
                else:
                    client = OpenAI(api_key=api_key, base_url="https://xiaoai.plus/v1")
                    with st.spinner("正在生成機構級戰略報告 (深度復刻版)..."):
                        aggregated_data_list = [history[t]['info_str'] for t in target_list if t in history and 'info_str' in history[t]]
                        final_all_data_text = "\n".join(aggregated_data_list)
                        
                        # 🚀 終極 Macro Prompt (完全依照您的要求定製)
                        macro_prompt = f"""
                        # Role: 頂級華爾街宏觀對沖基金經理人 (Alpha Focus)
                        ## 報告日期: {today_date} | VIX: {vix_current:.2f}
                        ## 全量掃描數據 ({len(target_list)} 隻)
                        {final_all_data_text}
                        
                        ## 任務：請嚴格依照以下結構產出機構級戰略報告
                        
                        ### 市場背景分析：審慎樂觀的「震盪上行」格局
                        請基於 VIX ({vix_current:.2f}) 與上述個股 RS 分佈，分析當前市場是否處於「選股為王」的環境。即使 VIX 偏高，若動能股強勢，請強調結構性機會。
                        
                        ### 1. 最強板塊排行 (Top 5)
                        請列出前五大板塊，並附上代表標的。
                        
                        ### 2. Alpha Focus Top Picks
                        #### 🔥 核心強勢突破名單 (Core Strong Breakout List)
                        請從名單中精選 5 檔 **RS > 95 且 距SMA21 > 15%** 的動能強勢股。
                        **必須嚴格使用以下格式：**
                        1. **代碼 (板塊)**
                           * RS: [數值] | 距SMA21: [數值]%
                           * **點評:** [深度分析其動能慣性與入場策略，例如：適合順勢而為，但需嚴格止損]
                        
                        #### 🎯 狙擊手潛伏名單 (SMA21 乖離率 0-6% 完美打擊區)
                        請從名單中精選 5 檔 **RS > 90 且 距SMA21 介於 0% 至 6%** 的股票。
                        (格式同上，但點評需強調「盈虧比吸引」與「蓄勢待發」)
                        
                        ### 3. 宏觀環境分析 (Macro Environment Analysis)
                        請分析當前 通脹預期、利率政策、科技週期 (AI/半導體) 對上述強勢板塊的驅動邏輯。
                        
                        ### 4. 戰略建議 (The Swing Playbook)
                        - **核心持倉配置 (Core Allocation)**: 建議重倉哪些板塊？
                        - **動能交易策略**: 對於「突破股」與「潛伏股」分別該如何操作？
                        
                        ### 5. 關鍵風險提醒 (Key Risk Reminders)
                        1. **宏觀經濟逆風**: (如通脹、地緣政治)
                        2. **個股層面風險**: (如財報地雷、過度延伸的回調風險)
                        3. **流動性風險**: (針對中小型股的警示)
                        """
                        try:
                            macro_res = client.chat.completions.create(model='gemini-2.5-flash', messages=[{"role": "user", "content": macro_prompt}])
                            macro_text = macro_res.choices[0].message.content
                            history[macro_cache_key] = {"date": today_date, "content": macro_text}
                            save_history(history)
                            st.rerun()
                        except Exception as e: st.error(f"錯誤: {e}")

    else:
        st.info("👈 請先上傳 TradingView CSV 以啟動全景模式。")

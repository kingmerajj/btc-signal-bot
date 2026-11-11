import os
import requests
import pandas as pd
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from backtesting import Backtest, Strategy

# ============ تنظیمات ============
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

SYMBOL = "BTCIRT"
RESOLUTION = "D"
CANDLE_COUNT = 250 
MEMORY_FILE = "last_signal.txt" # فایل حافظه ربات

# ============ تابع RSI ============
def rsi_func(series, period=14):
    series = pd.Series(series)
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# ============ توابع خواندن و نوشتن حافظه ============
def read_last_signal():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "None"

def save_last_signal(signal):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(signal)

# ============ دریافت داده‌های نوبیتکس ============
def fetch_nobitex_candles(symbol, resolution, countback):
    url = "https://apiv2.nobitex.ir/market/udf/history"
    params = {"symbol": symbol, "resolution": resolution, "to": int(time.time()), "countback": countback}
    headers = {"User-Agent": "TraderBot/1.0.0"}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        data = response.json()
        if data.get("s") != "ok": return None
        df = pd.DataFrame({
            "timestamp": data["t"], "open": data["o"], "high": data["h"],
            "low": data["l"], "close": data["c"], "volume": data["v"]
        })
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        return df
    except Exception as e:
        print(f"خطا در نوبیتکس: {e}")
        return None

# ============ دریافت داده‌های تاریخی از CoinGecko ============
def fetch_coingecko_historical_data():
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": "365", "interval": "daily"}
    try:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
        df = pd.DataFrame(data['prices'], columns=['timestamp', 'Close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df['Open'] = df['Close']
        df['High'] = df['Close']
        df['Low'] = df['Close']
        df['Volume'] = 1 
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except Exception as e:
        print(f"خطا در CoinGecko: {e}")
        return None

# ============ استراتژی بک‌تست ============
class BacktestStrategy(Strategy):
    def init(self):
        self.ma50 = self.I(lambda x: pd.Series(x).rolling(50).mean(), self.data.Close)
        self.rsi = self.I(rsi_func, self.data.Close)
    def next(self):
        if not self.position:
            if self.data.Close[-1] > self.ma50[-1] and 50 < self.rsi[-1] < 70:
                self.buy()
        else:
            if self.data.Close[-1] < self.ma50[-1] or self.rsi[-1] >= 70:
                self.position.close()

# ============ محاسبه اندیکاتورها ============
def calculate_indicators(df):
    df["ma50"] = df["close"].rolling(window=50).mean()
    df["ma200"] = df["close"].rolling(window=200).mean()
    df["vol_ma20"] = df["volume"].rolling(window=20).mean()
    df["rsi"] = rsi_func(df["close"])
    return df

def generate_signal(df):
    df_clean = df.dropna(subset=["ma50", "ma200", "rsi", "vol_ma20"])
    if len(df_clean) < 2: return "خنثی", ""
    
    last = df_clean.iloc[-1]
    prev = df_clean.iloc[-2]
    price, ma50, ma200, rsi = last["close"], last["ma50"], last["ma200"], last["rsi"]
    volume, vol_ma20 = last["volume"], last["vol_ma20"]
    
    signal, reason = "خنثی", ""
    
    if price > ma50 and price > ma200 and volume > vol_ma20 and 50 < rsi < 70:
        if prev["close"] > prev["ma50"]:
            signal = "🟢 خرید (Buy)"
            reason = f"قیمت ({price:,.0f}) بالای MA50 و MA200 | RSI ({rsi:.1f}) | حجم بالا"
    elif price < ma50 or rsi >= 70:
        signal = "🔴 فروش / خروج (Sell)"
        reason = f"قیمت زیر MA50" if price < ma50 else f"RSI اشباع خرید ({rsi:.1f})"
        
    return signal, reason

# ============ ارسال ایمیل ============
def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, EMAIL_SENDER, EMAIL_RECEIVER
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print("ایمیل ارسال شد.")
    except Exception as e:
        print(f"خطا در ایمیل: {e}")

# ============ اجرای اصلی ============
def main():
    print(f"[{datetime.now()}] شروع تحلیل...")
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("خطا: Secrets تنظیم نشده‌اند.")
        return

    # ۱. خواندن حافظه
    last_signal_sent = read_last_signal()
    print(f"آخرین سیگنال ارسال شده: {last_signal_sent}")

    # ۲. بک‌تست
    hist_df = fetch_coingecko_historical_data()
    if hist_df is None or hist_df.empty:
        total_return, win_rate, max_dd = 0, 0, 0
    else:
        bt = Backtest(hist_df, BacktestStrategy, cash=100_000_000, commission=.002, exclusive_orders=True)
        stats = bt.run()
        win_rate, total_return, max_dd = stats['Win Rate [%]'], stats['Return [%]'], stats['Max. Drawdown [%]']

    # ۳. سیگنال زنده
    df = fetch_nobitex_candles(SYMBOL, RESOLUTION, CANDLE_COUNT)
    if df is None: return
    df = calculate_indicators(df)
    signal, reason = generate_signal(df)

    print(f"سیگنال جدید: {signal}")

    # ۴. منطق حافظه (بررسی تکراری بودن)
    if "خنثی" in signal:
        print("سیگنال خنثی است. ایمیلی ارسال نشد.")
        return

    if signal == last_signal_sent:
        print(f"سیگنال ({signal}) تکراری است و قبلاً ارسال شده. ایمیلی ارسال نشد.")
        return

    # ۵. ارسال ایمیل و ذخیره در حافظه
    subject = f"سیگنال {SYMBOL} | {signal}"
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Tahoma, sans-serif; background: #f5f5f5; padding: 20px; }}
            .card {{ background: #fff; border-radius: 12px; padding: 24px; max-width: 500px; margin: auto; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
            .header {{ text-align: center; border-bottom: 2px solid #eee; padding-bottom: 12px; }}
            .signal {{ font-size: 22px; font-weight: bold; text-align: center; margin: 16px 0; }}
            .buy {{ color: #0a8f3c; }} .sell {{ color: #c0392b; }}
            .row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }}
            .label {{ color: #666; }} .value {{ font-weight: bold; direction: ltr; }}
            .backtest-box {{ background: #f9f9f9; border-radius: 8px; padding: 12px; margin-top: 16px; border: 1px dashed #ccc; }}
            .backtest-title {{ font-size: 14px; color: #444; margin-bottom: 8px; text-align: center; font-weight: bold; }}
            .footer {{ margin-top: 20px; font-size: 12px; color: #999; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">
                <h2>📊 سیگنال روزانه نوبیتکس</h2>
                <p style="color:#666; margin:0;">{SYMBOL} — تایم‌فریم روزانه</p>
            </div>
            <div class="signal {('buy' if 'خرید' in signal else 'sell')}">
                {signal}
            </div>
            <div class="row"><span class="label">قیمت لحظه‌ای</span><span class="value">{df.iloc[-1]['close']:,.0f} تومان</span></div>
            <div class="row"><span class="label">دلیل سیگنال</span><span class="value" style="direction:rtl; font-weight:normal;">{reason}</span></div>
            
            <div class="backtest-box">
                <div class="backtest-title">🧪 نتایج بک‌تست (استراتژی پایه)</div>
                <div class="row"><span class="label">سود کل استراتژی</span><span class="value">{total_return:.1f}%</span></div>
                <div class="row"><span class="label">درصد معاملات سودده</span><span class="value">{win_rate:.1f}%</span></div>
                <div class="row"><span class="label">حداکثر افت سرمایه</span><span class="value">{max_dd:.1f}%</span></div>
            </div>

            <div class="footer">
                زمان تحلیل: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                این پیام خودکار است و توصیه مالی نیست.
            </div>
        </div>
    </body>
    </html>
    """
    send_email(subject, html)
    
    # ذخیره سیگنال جدید در حافظه
    save_last_signal(signal)
    print("سیگنال در حافظه ذخیره شد.")

if __name__ == "__main__":
    main()

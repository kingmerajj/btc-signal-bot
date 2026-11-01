import os
import requests
import pandas as pd
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ============ تنظیمات (از GitHub Secrets خوانده می‌شود) ============
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

SYMBOL = "BTCIRT"          # بیت‌کوین به تومان
RESOLUTION = "D"           # تایم‌فریم یک روزه
CANDLE_COUNT = 200         # تعداد کندل برای تحلیل

# ============ دریافت داده از نوبیتکس ============
def fetch_nobitex_candles(symbol, resolution, countback):
    url = "https://apiv2.nobitex.ir/market/udf/history"
    params = {
        "symbol": symbol,
        "resolution": resolution,
        "to": int(time.time()),
        "countback": countback
    }
    headers = {"User-Agent": "TraderBot/1.0.0"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get("s") != "ok":
            print(f"خطا در دریافت داده: {data}")
            return None

        df = pd.DataFrame({
            "timestamp": data["t"],
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"],
            "volume": data["v"]
        })
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        return df
    except Exception as e:
        print(f"خطا در اتصال به نوبیتکس: {e}")
        return None

# ============ محاسبه اندیکاتورها ============
def calculate_indicators(df):
    df["ma50"] = df["close"].rolling(window=50).mean()

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    return df

# ============ تولید سیگنال ============
def generate_signal(df):
    df_clean = df.dropna(subset=["ma50", "rsi"])
    if len(df_clean) < 2:
        return "داده کافی برای تحلیل وجود ندارد.", None

    last = df_clean.iloc[-1]
    prev = df_clean.iloc[-2]

    price = last["close"]
    ma50 = last["ma50"]
    rsi = last["rsi"]

    signal = "خنثی (بدون سیگنال)"
    reason = ""

    # خرید کم‌ریسک: قیمت بالای MA50، RSI بین 50 و 70، تاییدیه کندل قبلی
    if price > ma50 and 50 < rsi < 70:
        if prev["close"] > prev["ma50"]:
            signal = "🟢 خرید (Buy)"
            reason = f"قیمت ({price:,.0f}) بالای MA50 ({ma50:,.0f}) و RSI در محدوده سالم ({rsi:.1f})"

    # فروش / خروج: قیمت زیر MA50 یا RSI در اشباع خرید
    elif price < ma50 or rsi >= 70:
        signal = "🔴 فروش / خروج (Sell)"
        if price < ma50:
            reason = f"قیمت ({price:,.0f}) زیر MA50 ({ma50:,.0f})"
        else:
            reason = f"RSI وارد اشباع خرید شده ({rsi:.1f})"

    return signal, reason

# ============ ارسال ایمیل ============
def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print("ایمیل با موفقیت ارسال شد.")
    except Exception as e:
        print(f"خطا در ارسال ایمیل: {e}")

# ============ اجرای اصلی ============
def main():
    print(f"[{datetime.now()}] دریافت داده‌های {SYMBOL} با تایم‌فریم روزانه...")

    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("خطا: متغیرهای محیطی ایمیل تنظیم نشده‌اند.")
        return

    df = fetch_nobitex_candles(SYMBOL, RESOLUTION, CANDLE_COUNT)
    if df is None:
        print("دریافت داده ناموفق بود.")
        return

    print(f"تعداد کندل دریافتی: {len(df)}")

    df = calculate_indicators(df)
    signal, reason = generate_signal(df)

    last = df.iloc[-1]
    price = last["close"]
    ma50 = last["ma50"]
    rsi = last["rsi"]

    print(f"سیگنال: {signal}")
    print(f"قیمت: {price:,.0f} | MA50: {ma50:,.0f} | RSI: {rsi:.1f}")

    subject = f"سیگنال روزانه {SYMBOL} | {signal}"

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Tahoma, Arial, sans-serif; background: #f5f5f5; padding: 20px; }}
            .card {{ background: #fff; border-radius: 12px; padding: 24px; max-width: 500px;
                     margin: auto; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
            .header {{ text-align: center; border-bottom: 2px solid #eee; padding-bottom: 12px; }}
            .signal {{ font-size: 22px; font-weight: bold; text-align: center; margin: 16px 0; }}
            .buy {{ color: #0a8f3c; }}
            .sell {{ color: #c0392b; }}
            .neutral {{ color: #888; }}
            .row {{ display: flex; justify-content: space-between; padding: 8px 0;
                    border-bottom: 1px solid #f0f0f0; }}
            .label {{ color: #666; }}
            .value {{ font-weight: bold; direction: ltr; }}
            .footer {{ margin-top: 20px; font-size: 12px; color: #999; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">
                <h2>📊 سیگنال روزانه نوبیتکس</h2>
                <p style="color:#666; margin:0;">{SYMBOL} — تایم‌فریم روزانه</p>
            </div>
            <div class="signal {('buy' if 'خرید' in signal else 'sell' if 'فروش' in signal else 'neutral')}">
                {signal}
            </div>
            <div class="row"><span class="label">قیمت لحظه‌ای</span><span class="value">{price:,.0f} تومان</span></div>
            <div class="row"><span class="label">میانگین متحرک ۵۰ (MA50)</span><span class="value">{ma50:,.0f}</span></div>
            <div class="row"><span class="label">شاخص RSI (۱۴)</span><span class="value">{rsi:.1f}</span></div>
            <div class="row"><span class="label">دلیل سیگنال</span><span class="value" style="direction:rtl; font-weight:normal;">{reason if reason else '—'}</span></div>
            <div class="footer">
                زمان تحلیل: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                این پیام به صورت خودکار تولید شده و توصیه مالی نیست.
            </div>
        </div>
    </body>
    </html>
    """

    send_email(subject, html)

if __name__ == "__main__":
    main()

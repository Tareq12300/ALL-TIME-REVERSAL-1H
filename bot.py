import os
import time
import json
import math
import threading
from datetime import datetime

import requests
import ccxt
import pytz
from flask import Flask
from telegram import Bot


# =========================
# ENV HELPERS
# =========================

def env_str(name, default=""):
    return os.getenv(name, default).strip()


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


def env_bool(name, default=True):
    value = os.getenv(name, str(default)).lower().strip()
    return value in ["true", "1", "yes", "y", "on"]


# =========================
# VARIABLES
# =========================

TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = env_str("TELEGRAM_CHANNEL_ID")
CMC_API_KEY = env_str("CMC_API_KEY")

CMC_TOP_N = env_int("CMC_TOP_N", 1000)
CHECK_INTERVAL = env_int("CHECK_INTERVAL", 3600)

TREND_TIMEFRAME = env_str("TREND_TIMEFRAME", "1d")
ENTRY_TIMEFRAME = env_str("ENTRY_TIMEFRAME", "4h")

EMA_PERIOD = env_int("EMA_PERIOD", 50)
RSI_PERIOD = env_int("RSI_PERIOD", 14)
STOCH_RSI_PERIOD = env_int("STOCH_RSI_PERIOD", 14)

MAX_STOCH_RSI = env_float("MAX_STOCH_RSI", 40)

MIN_VOLUME_RATIO = env_float("MIN_VOLUME_RATIO", 1.0)
MIN_CANDLE_VOLUME_USD = env_float("MIN_CANDLE_VOLUME_USD", 8000)
MIN_24H_VOLUME_USD = env_float("MIN_24H_VOLUME_USD", 500000)

REQUIRE_TREND_CLOSE_ABOVE_EMA = env_bool("REQUIRE_TREND_CLOSE_ABOVE_EMA", True)
REQUIRE_TREND_MACD_POSITIVE = env_bool("REQUIRE_TREND_MACD_POSITIVE", True)

REQUIRE_ENTRY_CLOSE_ABOVE_EMA = env_bool("REQUIRE_ENTRY_CLOSE_ABOVE_EMA", True)
REQUIRE_ENTRY_STOCH_K_ABOVE_D = env_bool("REQUIRE_ENTRY_STOCH_K_ABOVE_D", True)
REQUIRE_ENTRY_MACD_POSITIVE = env_bool("REQUIRE_ENTRY_MACD_POSITIVE", True)
REQUIRE_ENTRY_MACD_RISING = env_bool("REQUIRE_ENTRY_MACD_RISING", True)

TP1_PERCENT = env_float("TP1_PERCENT", 3)
TP2_PERCENT = env_float("TP2_PERCENT", 6)
TP3_PERCENT = env_float("TP3_PERCENT", 10)
SL_PERCENT = env_float("SL_PERCENT", 6)

ENABLE_GATE = env_bool("ENABLE_GATE", True)
ENABLE_KUCOIN = env_bool("ENABLE_KUCOIN", True)
ENABLE_OKX = env_bool("ENABLE_OKX", True)
ENABLE_BYBIT = env_bool("ENABLE_BYBIT", True)
ENABLE_BITGET = env_bool("ENABLE_BITGET", True)

TIMEZONE = pytz.timezone("Asia/Riyadh")

SIGNALS_FILE = "active_signals.json"
SENT_FILE = "sent_signals.json"


# =========================
# FLASK FOR RAILWAY
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Multi-Timeframe Trend Bot is running ✅"


# =========================
# TELEGRAM
# =========================

bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None


def send_telegram(message):
    if not bot or not TELEGRAM_CHANNEL_ID:
        print("Telegram not configured")
        return

    try:
        bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Telegram Error: {e}")


# =========================
# FILE STORAGE
# =========================

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Save Error {path}: {e}")


active_signals = load_json(SIGNALS_FILE, {})
sent_signals = load_json(SENT_FILE, {})


# =========================
# EXCHANGES
# =========================

def build_exchanges():
    exchanges = []

    if ENABLE_GATE:
        exchanges.append(("Gate", ccxt.gateio({"enableRateLimit": True})))

    if ENABLE_KUCOIN:
        exchanges.append(("KuCoin", ccxt.kucoin({"enableRateLimit": True})))

    if ENABLE_OKX:
        exchanges.append(("OKX", ccxt.okx({"enableRateLimit": True})))

    if ENABLE_BYBIT:
        exchanges.append(("Bybit", ccxt.bybit({"enableRateLimit": True})))

    if ENABLE_BITGET:
        exchanges.append(("Bitget", ccxt.bitget({"enableRateLimit": True})))

    return exchanges


EXCHANGES = build_exchanges()


# =========================
# FILTERS
# =========================

STABLES = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDD",
    "FRAX", "USDP", "PYUSD", "GUSD", "LUSD", "USTC"
}

BAD_KEYWORDS = [
    "3L", "3S", "5L", "5S", "UP", "DOWN", "BULL", "BEAR",
    "USDC", "BUSD", "DAI", "TUSD", "FDUSD",
    "ONDO3", "BTC3", "ETH3"
]


def is_bad_symbol(symbol):
    base = symbol.split("/")[0].upper()

    if base in STABLES:
        return True

    for word in BAD_KEYWORDS:
        if base.endswith(word):
            return True

    return False


# =========================
# CMC TOP COINS
# =========================

def get_cmc_top_symbols():
    if not CMC_API_KEY:
        print("CMC_API_KEY missing")
        return []

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

    params = {
        "start": 1,
        "limit": CMC_TOP_N,
        "convert": "USD"
    }

    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])

        symbols = []
        for coin in data:
            symbol = coin.get("symbol", "").upper()
            quote = coin.get("quote", {}).get("USD", {})
            volume_24h = quote.get("volume_24h", 0)

            if symbol and volume_24h >= MIN_24H_VOLUME_USD and symbol not in STABLES:
                symbols.append(symbol)

        return symbols

    except Exception as e:
        print(f"CMC Error: {e}")
        return []


# =========================
# INDICATORS
# =========================

def ema(values, period):
    if len(values) < period:
        return []

    k = 2 / (period + 1)
    ema_values = [sum(values[:period]) / period]

    for price in values[period:]:
        ema_values.append(price * k + ema_values[-1] * (1 - k))

    padding = [None] * (period - 1)
    return padding + ema_values


def rsi(values, period=14):
    if len(values) < period + 1:
        return []

    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi_values = [None] * period

    if avg_loss == 0:
        rsi_values.append(100)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - (100 / (1 + rs)))

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    return rsi_values


def sma(values, period):
    result = []

    for i in range(len(values)):
        if i + 1 < period:
            result.append(None)
        else:
            window = values[i + 1 - period:i + 1]
            if any(v is None for v in window):
                result.append(None)
            else:
                result.append(sum(window) / period)

    return result


def stoch_rsi(values, rsi_period=14, stoch_period=14):
    rsi_values = rsi(values, rsi_period)

    if len(rsi_values) < stoch_period:
        return [], []

    stoch_values = []

    for i in range(len(rsi_values)):
        if i + 1 < stoch_period or rsi_values[i] is None:
            stoch_values.append(None)
            continue

        window = rsi_values[i + 1 - stoch_period:i + 1]
        window = [v for v in window if v is not None]

        if len(window) < stoch_period:
            stoch_values.append(None)
            continue

        lowest = min(window)
        highest = max(window)

        if highest - lowest == 0:
            stoch_values.append(0)
        else:
            stoch_values.append(((rsi_values[i] - lowest) / (highest - lowest)) * 100)

    k_values = sma(stoch_values, 3)
    d_values = sma(k_values, 3)

    return k_values, d_values


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        return [], [], []

    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)

    macd_line = []

    for f, s in zip(ema_fast, ema_slow):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)

    valid_macd = [v for v in macd_line if v is not None]
    signal_valid = ema(valid_macd, signal)

    signal_line = []
    j = 0

    for v in macd_line:
        if v is None:
            signal_line.append(None)
        else:
            signal_line.append(signal_valid[j])
            j += 1

    histogram = []

    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)

    return macd_line, signal_line, histogram


# =========================
# DATA
# =========================

def fetch_ohlcv(exchange, symbol, timeframe, limit=150):
    try:
        return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    except Exception:
        return None


def fetch_price(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("close") or 0)
    except Exception:
        return 0


def candle_volume_usd(candle):
    close_price = float(candle[4])
    volume = float(candle[5])
    return close_price * volume


# =========================
# ANALYSIS
# =========================

def analyze_trend(ohlcv):
    closes = [float(c[4]) for c in ohlcv]

    ema_values = ema(closes, EMA_PERIOD)
    _, _, hist = macd(closes)

    close = closes[-1]
    ema_now = ema_values[-1]
    hist_now = hist[-1]
    hist_prev = hist[-2]

    if ema_now is None or hist_now is None or hist_prev is None:
        return None

    close_above_ema = close > ema_now
    macd_positive = hist_now > 0
    macd_rising = hist_now > hist_prev

    passed = True

    if REQUIRE_TREND_CLOSE_ABOVE_EMA and not close_above_ema:
        passed = False

    if REQUIRE_TREND_MACD_POSITIVE and not macd_positive:
        passed = False

    return {
        "passed": passed,
        "close": close,
        "ema": ema_now,
        "macd_hist": hist_now,
        "macd_prev": hist_prev,
        "close_above_ema": close_above_ema,
        "macd_positive": macd_positive,
        "macd_rising": macd_rising
    }


def analyze_entry(ohlcv):
    closes = [float(c[4]) for c in ohlcv]

    ema_values = ema(closes, EMA_PERIOD)
    k_values, d_values = stoch_rsi(closes, RSI_PERIOD, STOCH_RSI_PERIOD)
    _, _, hist = macd(closes)

    close = closes[-1]
    ema_now = ema_values[-1]

    k_now = k_values[-1]
    d_now = d_values[-1]

    hist_now = hist[-1]
    hist_prev = hist[-2]

    current_volume_usd = candle_volume_usd(ohlcv[-1])

    last_20 = ohlcv[-21:-1]
    avg_volume_usd = sum(candle_volume_usd(c) for c in last_20) / len(last_20)
    volume_ratio = current_volume_usd / avg_volume_usd if avg_volume_usd > 0 else 0

    if None in [ema_now, k_now, d_now, hist_now, hist_prev]:
        return None

    close_above_ema = close > ema_now
    stoch_cross = k_now > d_now
    stoch_under_limit = k_now < MAX_STOCH_RSI
    macd_positive = hist_now > 0
    macd_rising = hist_now > hist_prev
    volume_ok = volume_ratio >= MIN_VOLUME_RATIO and current_volume_usd >= MIN_CANDLE_VOLUME_USD

    passed = True

    if REQUIRE_ENTRY_CLOSE_ABOVE_EMA and not close_above_ema:
        passed = False

    if REQUIRE_ENTRY_STOCH_K_ABOVE_D and not stoch_cross:
        passed = False

    if not stoch_under_limit:
        passed = False

    if REQUIRE_ENTRY_MACD_POSITIVE and not macd_positive:
        passed = False

    if REQUIRE_ENTRY_MACD_RISING and not macd_rising:
        passed = False

    if not volume_ok:
        passed = False

    return {
        "passed": passed,
        "close": close,
        "ema": ema_now,
        "k": k_now,
        "d": d_now,
        "stoch_cross": stoch_cross,
        "stoch_under_limit": stoch_under_limit,
        "macd_hist": hist_now,
        "macd_prev": hist_prev,
        "macd_positive": macd_positive,
        "macd_rising": macd_rising,
        "current_volume_usd": current_volume_usd,
        "avg_volume_usd": avg_volume_usd,
        "volume_ratio": volume_ratio,
        "close_above_ema": close_above_ema,
    }


# =========================
# MESSAGE
# =========================

def fmt_money(value):
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:.2f}"


def build_signal_message(exchange_name, symbol, price, trend, entry):
    tp1 = price * (1 + TP1_PERCENT / 100)
    tp2 = price * (1 + TP2_PERCENT / 100)
    tp3 = price * (1 + TP3_PERCENT / 100)
    sl = price * (1 - SL_PERCENT / 100)

    now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M")

    return f"""
🟢 *MULTI-TIMEFRAME TREND ALERT*
━━━━━━━━━━━━━━
⏰ الوقت: `{now}`
🏦 المنصة: *{exchange_name}*
🪙 العملة: *{symbol}*
💰 سعر الدخول: `{price:.8f}`

📈 *فريم الاتجاه:* `{TREND_TIMEFRAME}`
✅ الاتجاه العام: صاعد
• السعر فوق EMA{EMA_PERIOD}: `{trend["close_above_ema"]}`
• MACD Histogram: `{trend["macd_hist"]:.8f}`

📊 *فريم الدخول:* `{ENTRY_TIMEFRAME}`
✅ اتجاه الدخول: صاعد
• Stoch RSI K: `{entry["k"]:.2f}`
• Stoch RSI D: `{entry["d"]:.2f}`
• K أعلى من D: `{entry["stoch_cross"]}`
• Stoch RSI أقل من {MAX_STOCH_RSI}: `{entry["stoch_under_limit"]}`

📈 *MACD*
• الحالي: `{entry["macd_hist"]:.8f}`
• السابق: `{entry["macd_prev"]:.8f}`
• موجب: `{entry["macd_positive"]}`
• يتحسن: `{entry["macd_rising"]}`

💧 *Volume*
• حجم الشمعة الحالية: `{fmt_money(entry["current_volume_usd"])}`
• متوسط آخر 20 شمعة: `{fmt_money(entry["avg_volume_usd"])}`
• Volume Ratio: `{entry["volume_ratio"]:.2f}x`

🎯 *الأهداف*
• TP1: `{tp1:.8f}` (+{TP1_PERCENT}%)
• TP2: `{tp2:.8f}` (+{TP2_PERCENT}%)
• TP3: `{tp3:.8f}` (+{TP3_PERCENT}%)

🛑 Stop Loss: `{sl:.8f}` (-{SL_PERCENT}%)

✅ سيتم إرسال تنبيه عند تحقق كل هدف.
⚠️ تحليل آلي وليس نصيحة مالية.
"""


def build_startup_message():
    return f"""
🤖 *بوت توافق الاتجاه اشتغل بنجاح ✅*
━━━━━━━━━━━━━━
📈 فريم الاتجاه: `{TREND_TIMEFRAME}`
🎯 فريم الدخول: `{ENTRY_TIMEFRAME}`
⏱️ الفحص كل: `{CHECK_INTERVAL}` ثانية

🌐 CoinMarketCap:
• Top N: `{CMC_TOP_N}`
• Min 24H Volume: `{fmt_money(MIN_24H_VOLUME_USD)}`

🎯 شروط الدخول:
• الاتجاه اليومي/الترند صاعد
• اتجاه فريم الدخول صاعد
• Stoch RSI K أعلى من D
• Stoch RSI أقل من `{MAX_STOCH_RSI}`
• MACD موجب ويتحسن
• Volume Ratio أعلى من `{MIN_VOLUME_RATIO}x`
• حجم الشمعة أعلى من `{fmt_money(MIN_CANDLE_VOLUME_USD)}`

🎯 متابعة الأهداف:
• TP1 +{TP1_PERCENT}%
• TP2 +{TP2_PERCENT}%
• TP3 +{TP3_PERCENT}%
• SL -{SL_PERCENT}%

✅ سيتم إرسال تنبيه عند تحقق كل هدف.
"""


# =========================
# TARGET MONITOR
# =========================

def register_signal(exchange_name, symbol, price):
    key = f"{exchange_name}:{symbol}"

    active_signals[key] = {
        "exchange": exchange_name,
        "symbol": symbol,
        "entry": price,
        "tp1": price * (1 + TP1_PERCENT / 100),
        "tp2": price * (1 + TP2_PERCENT / 100),
        "tp3": price * (1 + TP3_PERCENT / 100),
        "sl": price * (1 - SL_PERCENT / 100),
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "sl_hit": False,
        "created_at": datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    }

    save_json(SIGNALS_FILE, active_signals)


def monitor_targets():
    global active_signals

    while True:
        try:
            for key, signal in list(active_signals.items()):
                exchange_name = signal["exchange"]
                symbol = signal["symbol"]

                exchange = None
                for name, ex in EXCHANGES:
                    if name == exchange_name:
                        exchange = ex
                        break

                if exchange is None:
                    continue

                price = fetch_price(exchange, symbol)

                if price <= 0:
                    continue

                entry = signal["entry"]

                if not signal["tp1_hit"] and price >= signal["tp1"]:
                    signal["tp1_hit"] = True
                    send_telegram(f"""
🎯 *TP1 تحقق ✅*
━━━━━━━━━━━━━━
🏦 المنصة: *{exchange_name}*
🪙 العملة: *{symbol}*
💰 الدخول: `{entry:.8f}`
📈 السعر الحالي: `{price:.8f}`
✅ الربح: `+{TP1_PERCENT}%`
""")

                if not signal["tp2_hit"] and price >= signal["tp2"]:
                    signal["tp2_hit"] = True
                    send_telegram(f"""
🎯 *TP2 تحقق ✅*
━━━━━━━━━━━━━━
🏦 المنصة: *{exchange_name}*
🪙 العملة: *{symbol}*
💰 الدخول: `{entry:.8f}`
📈 السعر الحالي: `{price:.8f}`
✅ الربح: `+{TP2_PERCENT}%`
""")

                if not signal["tp3_hit"] and price >= signal["tp3"]:
                    signal["tp3_hit"] = True
                    send_telegram(f"""
🎯 *TP3 تحقق ✅*
━━━━━━━━━━━━━━
🏦 المنصة: *{exchange_name}*
🪙 العملة: *{symbol}*
💰 الدخول: `{entry:.8f}`
📈 السعر الحالي: `{price:.8f}`
✅ الربح: `+{TP3_PERCENT}%`
""")

                if not signal["sl_hit"] and price <= signal["sl"]:
                    signal["sl_hit"] = True
                    send_telegram(f"""
🛑 *Stop Loss تحقق*
━━━━━━━━━━━━━━
🏦 المنصة: *{exchange_name}*
🪙 العملة: *{symbol}*
💰 الدخول: `{entry:.8f}`
📉 السعر الحالي: `{price:.8f}`
❌ الخسارة: `-{SL_PERCENT}%`
""")

                if signal["tp3_hit"] or signal["sl_hit"]:
                    active_signals.pop(key, None)

            save_json(SIGNALS_FILE, active_signals)

        except Exception as e:
            print(f"Target Monitor Error: {e}")

        time.sleep(60)


# =========================
# SCANNER
# =========================

def scanner_loop():
    send_telegram(build_startup_message())

    while True:
        print("Scanning CoinMarketCap...")

        cmc_symbols = get_cmc_top_symbols()

        if not cmc_symbols:
            print("No CMC symbols found")
            time.sleep(CHECK_INTERVAL)
            continue

        signals_found = 0

        for exchange_name, exchange in EXCHANGES:
            try:
                exchange.load_markets()
            except Exception as e:
                print(f"{exchange_name} load markets error: {e}")
                continue

            for base in cmc_symbols:
                symbol = f"{base}/USDT"

                if symbol not in exchange.markets:
                    continue

                if is_bad_symbol(symbol):
                    continue

                signal_key = f"{exchange_name}:{symbol}:{TREND_TIMEFRAME}:{ENTRY_TIMEFRAME}"

                if signal_key in sent_signals:
                    continue

                try:
                    trend_ohlcv = fetch_ohlcv(exchange, symbol, TREND_TIMEFRAME, 150)
                    entry_ohlcv = fetch_ohlcv(exchange, symbol, ENTRY_TIMEFRAME, 150)

                    if not trend_ohlcv or not entry_ohlcv:
                        continue

                    if len(trend_ohlcv) < 80 or len(entry_ohlcv) < 80:
                        continue

                    trend = analyze_trend(trend_ohlcv)
                    entry = analyze_entry(entry_ohlcv)

                    if not trend or not entry:
                        continue

                    if trend["passed"] and entry["passed"]:
                        price = entry["close"]

                        message = build_signal_message(
                            exchange_name=exchange_name,
                            symbol=symbol,
                            price=price,
                            trend=trend,
                            entry=entry
                        )

                        send_telegram(message)
                        register_signal(exchange_name, symbol, price)

                        sent_signals[signal_key] = {
                            "sent_at": datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"),
                            "price": price
                        }

                        save_json(SENT_FILE, sent_signals)

                        signals_found += 1
                        time.sleep(2)

                except Exception as e:
                    print(f"Scan error {exchange_name} {symbol}: {e}")
                    continue

        print(f"Signals Found: {signals_found}")
        time.sleep(CHECK_INTERVAL)


# =========================
# RUN
# =========================

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=monitor_targets, daemon=True).start()

    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

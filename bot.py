import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask

# =========================
# FLASK KEEP ALIVE
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Volume Hunter Bot is running ✅"

def run_flask():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_flask, daemon=True).start()


# =========================
# ENV HELPERS
# =========================

def env_str(name, default=""):
    return os.getenv(name, default).strip()

def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except:
        return default

def env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except:
        return default

def env_bool(name, default=True):
    return os.getenv(name, str(default)).lower() == "true"


# =========================
# VARIABLES
# =========================

TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env_str("TELEGRAM_CHAT_ID")

USE_CMC_FILTER = env_bool("USE_CMC_FILTER", True)
CMC_API_KEY = env_str("CMC_API_KEY")
CMC_TOP_N = env_int("CMC_TOP_N", 3000)

MIN_MARKET_CAP = env_float("MIN_MARKET_CAP", 10000000)
MAX_MARKET_CAP = env_float("MAX_MARKET_CAP", 1000000000)

CHECK_INTERVAL = env_int("CHECK_INTERVAL", 900)
MAX_COINS = env_int("MAX_COINS", 3000)
QUOTE_CURRENCY = env_str("QUOTE_CURRENCY", "USDT")

MAX_24H_CHANGE = env_float("MAX_24H_CHANGE", 25)
SIGNAL_COOLDOWN_MINUTES = env_int("SIGNAL_COOLDOWN_MINUTES", 240)
ENABLE_WELCOME_MESSAGE = env_bool("ENABLE_WELCOME_MESSAGE", True)

ENABLE_1H = env_bool("ENABLE_1H", True)
ENABLE_4H = env_bool("ENABLE_4H", True)

TIMEFRAME_1H = env_str("TIMEFRAME_1H", "1h")
TIMEFRAME_4H = env_str("TIMEFRAME_4H", "4h")

MIN_VOLUME_RATIO_1H = env_float("MIN_VOLUME_RATIO_1H", 2)
MIN_CURRENT_VOLUME_USD_1H = env_float("MIN_CURRENT_VOLUME_USD_1H", 300000)
VOLUME_LOOKBACK_1H = env_int("VOLUME_LOOKBACK_1H", 20)

MIN_VOLUME_RATIO_4H = env_float("MIN_VOLUME_RATIO_4H", 2)
MIN_CURRENT_VOLUME_USD_4H = env_float("MIN_CURRENT_VOLUME_USD_4H", 1000000)
VOLUME_LOOKBACK_4H = env_int("VOLUME_LOOKBACK_4H", 20)

REQUIRE_BOTH_TIMEFRAMES = env_bool("REQUIRE_BOTH_TIMEFRAMES", False)
SEND_ONLY_STRONG_ALERTS = env_bool("SEND_ONLY_STRONG_ALERTS", False)

ENABLE_STABLECOIN_FILTER = env_bool("ENABLE_STABLECOIN_FILTER", True)
ENABLE_MEME_FILTER = env_bool("ENABLE_MEME_FILTER", True)
ENABLE_GAMBLING_FILTER = env_bool("ENABLE_GAMBLING_FILTER", True)
ENABLE_GAMING_FILTER = env_bool("ENABLE_GAMING_FILTER", True)
ENABLE_PREDICTION_MARKET_FILTER = env_bool("ENABLE_PREDICTION_MARKET_FILTER", True)

GATE_BASE_URL = "https://api.gateio.ws/api/v4"
CMC_BASE_URL = "https://pro-api.coinmarketcap.com"


# =========================
# MEMORY
# =========================

last_alert_time = {}


# =========================
# EXCLUSION LISTS
# =========================

STABLECOINS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDD", "BUSD",
    "PYUSD", "USD1", "EUR", "EURS", "USTC"
}

MEME_KEYWORDS = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME",
    "TURBO", "BABYDOGE", "ELON", "CAT", "MOG", "BRETT"
}

GAMBLING_KEYWORDS = {
    "BET", "CASINO", "GAMBLE", "LOTTO", "POKER"
}

GAMING_KEYWORDS = {
    "GAME", "GAMING", "PLAY", "AXS", "SAND", "MANA", "GALA",
    "ILV", "YGG", "ALICE", "ENJ"
}

PREDICTION_KEYWORDS = {
    "PRED", "POLYMARKET", "FORECAST", "BET"
}

LEVERAGED_KEYWORDS = {
    "3L", "3S", "5L", "5S", "BULL", "BEAR", "UP", "DOWN"
}


# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram variables missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code != 200:
            print("Telegram Error:", r.text)
    except Exception as e:
        print("Telegram Exception:", e)


# =========================
# FORMAT HELPERS
# =========================

def fmt_usd(value):
    try:
        return f"${value:,.0f}"
    except:
        return "$0"

def fmt_num(value):
    try:
        return f"{value:,.2f}"
    except:
        return "0"

def now_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================
# FILTERS
# =========================

def is_excluded_symbol(symbol):
    s = symbol.upper()

    if any(k in s for k in LEVERAGED_KEYWORDS):
        return True

    if ENABLE_STABLECOIN_FILTER and s in STABLECOINS:
        return True

    if ENABLE_MEME_FILTER and any(k in s for k in MEME_KEYWORDS):
        return True

    if ENABLE_GAMBLING_FILTER and any(k in s for k in GAMBLING_KEYWORDS):
        return True

    if ENABLE_GAMING_FILTER and any(k in s for k in GAMING_KEYWORDS):
        return True

    if ENABLE_PREDICTION_MARKET_FILTER and any(k in s for k in PREDICTION_KEYWORDS):
        return True

    return False


# =========================
# COINMARKETCAP
# =========================

def get_cmc_coins():
    if not USE_CMC_FILTER:
        return {}

    if not CMC_API_KEY:
        print("CMC_API_KEY missing")
        return {}

    url = f"{CMC_BASE_URL}/v1/cryptocurrency/listings/latest"

    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accept": "application/json"
    }

    all_coins = {}
    start = 1
    limit = 500

    while len(all_coins) < CMC_TOP_N:
        params = {
            "start": start,
            "limit": min(limit, CMC_TOP_N - len(all_coins)),
            "convert": "USD"
        }

        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)

            if r.status_code != 200:
                print("CMC Error:", r.status_code, r.text)
                break

            data = r.json().get("data", [])

            if not data:
                break

            for coin in data:
                symbol = coin.get("symbol", "").upper()
                name = coin.get("name", "")
                rank = coin.get("cmc_rank", 0)

                quote = coin.get("quote", {}).get("USD", {})
                market_cap = float(quote.get("market_cap") or 0)
                volume_24h = float(quote.get("volume_24h") or 0)
                percent_change_24h = float(quote.get("percent_change_24h") or 0)

                if is_excluded_symbol(symbol):
                    continue

                if market_cap < MIN_MARKET_CAP:
                    continue

                if market_cap > MAX_MARKET_CAP:
                    continue

                if abs(percent_change_24h) > MAX_24H_CHANGE:
                    continue

                all_coins[symbol] = {
                    "symbol": symbol,
                    "name": name,
                    "rank": rank,
                    "market_cap": market_cap,
                    "cmc_volume_24h": volume_24h,
                    "cmc_change_24h": percent_change_24h
                }

            start += limit
            time.sleep(1)

        except Exception as e:
            print("CMC Exception:", e)
            break

    print(f"CMC coins loaded: {len(all_coins)}")
    return all_coins


# =========================
# GATE API
# =========================

def get_gate_tickers():
    url = f"{GATE_BASE_URL}/spot/tickers"

    try:
        data = requests.get(url, timeout=30).json()
    except Exception as e:
        print("Gate tickers error:", e)
        return {}

    tickers = {}

    for item in data:
        pair = item.get("currency_pair", "")

        if not pair.endswith(f"_{QUOTE_CURRENCY}"):
            continue

        base = pair.replace(f"_{QUOTE_CURRENCY}", "").upper()

        if is_excluded_symbol(base):
            continue

        try:
            change_24h = abs(float(item.get("change_percentage", 0)))
            quote_volume = float(item.get("quote_volume", 0))
            last_price = float(item.get("last", 0))
        except:
            continue

        if change_24h > MAX_24H_CHANGE:
            continue

        tickers[base] = {
            "base": base,
            "pair": pair,
            "symbol": pair.replace("_", "/"),
            "gate_change_24h": change_24h,
            "gate_volume_24h": quote_volume,
            "last_price": last_price
        }

    return tickers


def get_candles(pair, timeframe, lookback):
    url = f"{GATE_BASE_URL}/spot/candlesticks"

    params = {
        "currency_pair": pair,
        "interval": timeframe,
        "limit": lookback + 5
    }

    try:
        data = requests.get(url, params=params, timeout=30).json()
    except Exception as e:
        print("Candles error:", pair, timeframe, e)
        return None

    if not isinstance(data, list) or len(data) < lookback + 1:
        return None

    rows = []

    for c in data:
        try:
            rows.append({
                "time": int(c[0]),
                "volume_quote": float(c[1]),
                "close": float(c[2]),
                "high": float(c[3]),
                "low": float(c[4]),
                "open": float(c[5]),
                "volume_base": float(c[6])
            })
        except:
            continue

    df = pd.DataFrame(rows)

    if df.empty:
        return None

    df = df.sort_values("time").reset_index(drop=True)
    return df


# =========================
# VOLUME ANALYSIS
# =========================

def rate_volume(ratio):
    if ratio >= 5:
        return "انفجاري 💥"
    if ratio >= 3:
        return "قوي جداً 🚀"
    if ratio >= 2:
        return "قوي 🔥"
    if ratio >= 1:
        return "متوسط 🟡"
    return "ضعيف ⚪"


def analyze_timeframe(pair, timeframe, lookback, min_ratio, min_volume_usd):
    df = get_candles(pair, timeframe, lookback)

    if df is None or len(df) < lookback + 1:
        return None

    current = df.iloc[-1]
    current_volume_usd = float(current["volume_quote"])

    avg_volume_usd = float(
        df["volume_quote"].iloc[-lookback-1:-1].mean()
    )

    if avg_volume_usd <= 0:
        return None

    ratio = current_volume_usd / avg_volume_usd

    passed = (
        current_volume_usd >= min_volume_usd
        and ratio >= min_ratio
    )

    return {
        "timeframe": timeframe,
        "price": float(current["close"]),
        "current_volume_usd": current_volume_usd,
        "avg_volume_usd": avg_volume_usd,
        "volume_ratio": ratio,
        "rating": rate_volume(ratio),
        "passed": passed,
        "min_ratio": min_ratio,
        "min_volume_usd": min_volume_usd
    }


def analyze_coin(gate_info, cmc_info):
    pair = gate_info["pair"]

    result_1h = None
    result_4h = None

    if ENABLE_1H:
        result_1h = analyze_timeframe(
            pair=pair,
            timeframe=TIMEFRAME_1H,
            lookback=VOLUME_LOOKBACK_1H,
            min_ratio=MIN_VOLUME_RATIO_1H,
            min_volume_usd=MIN_CURRENT_VOLUME_USD_1H
        )

    if ENABLE_4H:
        result_4h = analyze_timeframe(
            pair=pair,
            timeframe=TIMEFRAME_4H,
            lookback=VOLUME_LOOKBACK_4H,
            min_ratio=MIN_VOLUME_RATIO_4H,
            min_volume_usd=MIN_CURRENT_VOLUME_USD_4H
        )

    pass_1h = result_1h["passed"] if result_1h else False
    pass_4h = result_4h["passed"] if result_4h else False

    if REQUIRE_BOTH_TIMEFRAMES and not (pass_1h and pass_4h):
        return None

    if not REQUIRE_BOTH_TIMEFRAMES and not (pass_1h or pass_4h):
        return None

    if SEND_ONLY_STRONG_ALERTS:
        strongest_ratio = max(
            result_1h["volume_ratio"] if result_1h else 0,
            result_4h["volume_ratio"] if result_4h else 0
        )
        if strongest_ratio < 3:
            return None

    return {
        "gate": gate_info,
        "cmc": cmc_info,
        "tf_1h": result_1h,
        "tf_4h": result_4h,
        "pass_1h": pass_1h,
        "pass_4h": pass_4h
    }


# =========================
# SIGNAL LOGIC
# =========================

def can_send_alert(symbol, source):
    key = f"{symbol}_{source}"
    now = datetime.now()

    if key not in last_alert_time:
        last_alert_time[key] = now
        return True

    diff = now - last_alert_time[key]

    if diff >= timedelta(minutes=SIGNAL_COOLDOWN_MINUTES):
        last_alert_time[key] = now
        return True

    return False


def signal_source(pass_1h, pass_4h):
    if pass_1h and pass_4h:
        return "1H + 4H"
    if pass_1h:
        return "1H فقط"
    if pass_4h:
        return "4H فقط"
    return "لا يوجد"


def best_entry_timeframe(pass_1h, pass_4h):
    if pass_1h and pass_4h:
        return "4H — تأكيد أقوى مع بداية زخم من 1H"
    if pass_1h:
        return "1H — دخول مبكر، يفضل انتظار تأكيد 4H"
    if pass_4h:
        return "4H — إشارة أقوى وأهدأ من 1H"
    return "لا يوجد"


def signal_score(pass_1h, pass_4h):
    if pass_1h and pass_4h:
        return "10/10"
    if pass_4h:
        return "8/10"
    if pass_1h:
        return "6/10"
    return "0/10"


def timeframe_line(label, result):
    if not result:
        return f"❌ {label}\n• لا توجد بيانات كافية\n"

    status = "✅" if result["passed"] else "❌"

    return f"""
{status} <b>{label}</b>
• Volume Ratio: {fmt_num(result['volume_ratio'])}x
• Current Volume: {fmt_usd(result['current_volume_usd'])}
• Avg Volume: {fmt_usd(result['avg_volume_usd'])}
• التقييم: {result['rating']}
"""


# =========================
# MESSAGES
# =========================

def send_welcome():
    message = f"""
🤖 <b>Volume Hunter Bot Started ✅</b>

━━━━━━━━━━━━━━

🏦 المنصة: Gate
🌐 المصدر: CoinMarketCap + Gate

📊 <b>الفريمات المفعلة:</b>
• 1H: {"✅" if ENABLE_1H else "❌"}
• 4H: {"✅" if ENABLE_4H else "❌"}

🌐 <b>CoinMarketCap:</b>
• Top N: {CMC_TOP_N}
• Market Cap Min: {fmt_usd(MIN_MARKET_CAP)}
• Market Cap Max: {fmt_usd(MAX_MARKET_CAP)}

🎯 <b>شروط 1H:</b>
• Volume Ratio ≥ {MIN_VOLUME_RATIO_1H}x
• Candle Volume ≥ {fmt_usd(MIN_CURRENT_VOLUME_USD_1H)}
• Lookback: {VOLUME_LOOKBACK_1H}

🎯 <b>شروط 4H:</b>
• Volume Ratio ≥ {MIN_VOLUME_RATIO_4H}x
• Candle Volume ≥ {fmt_usd(MIN_CURRENT_VOLUME_USD_4H)}
• Lookback: {VOLUME_LOOKBACK_4H}

⚙️ <b>الإعدادات:</b>
• الفحص كل: {CHECK_INTERVAL} ثانية
• أقصى تغير 24H: {MAX_24H_CHANGE}%
• Cooldown: {SIGNAL_COOLDOWN_MINUTES} دقيقة
• Require Both TF: {REQUIRE_BOTH_TIMEFRAMES}

✅ البوت الآن يراقب الفوليوم ويرسل التنبيهات.
"""
    send_telegram(message)


def build_alert(result):
    gate = result["gate"]
    cmc = result["cmc"]

    pass_1h = result["pass_1h"]
    pass_4h = result["pass_4h"]

    source = signal_source(pass_1h, pass_4h)
    entry_tf = best_entry_timeframe(pass_1h, pass_4h)
    score = signal_score(pass_1h, pass_4h)

    name = cmc.get("name", gate["base"]) if cmc else gate["base"]
    rank = cmc.get("rank", "N/A") if cmc else "N/A"
    market_cap = cmc.get("market_cap", 0) if cmc else 0
    cmc_volume_24h = cmc.get("cmc_volume_24h", 0) if cmc else 0
    cmc_change_24h = cmc.get("cmc_change_24h", 0) if cmc else 0

    message = f"""
🚀 <b>VOLUME SPIKE ALERT</b>

🪙 <b>{gate['symbol']}</b>
📛 الاسم: {name}
🏦 المنصة: Gate
🕒 الوقت: {now_time()}

━━━━━━━━━━━━━━

📊 <b>الفريمات:</b>

{timeframe_line("1H", result["tf_1h"])}
{timeframe_line("4H", result["tf_4h"])}

━━━━━━━━━━━━━━

🎯 <b>مصدر الإشارة:</b>
{source}

📈 <b>أفضل فريم للدخول:</b>
{entry_tf}

⭐ <b>تقييم الإشارة:</b>
{score}

━━━━━━━━━━━━━━

💰 <b>معلومات السوق:</b>
• السعر: {gate['last_price']}
• CMC Rank: {rank}
• Market Cap: {fmt_usd(market_cap)}
• CMC 24H Volume: {fmt_usd(cmc_volume_24h)}
• CMC 24H Change: {fmt_num(cmc_change_24h)}%
• Gate 24H Volume: {fmt_usd(gate['gate_volume_24h'])}

⚠️ تحليل فقط وليس نصيحة مالية.
"""
    return message


# =========================
# MAIN LOOP
# =========================

def main():
    print("Volume Hunter Bot started ✅")

    if ENABLE_WELCOME_MESSAGE:
        send_welcome()

    while True:
        try:
            print("Starting scan...")

            cmc_coins = get_cmc_coins()
            gate_tickers = get_gate_tickers()

            if USE_CMC_FILTER:
                symbols_to_scan = [
                    symbol for symbol in cmc_coins.keys()
                    if symbol in gate_tickers
                ]
            else:
                symbols_to_scan = list(gate_tickers.keys())

            symbols_to_scan = symbols_to_scan[:MAX_COINS]

            print(f"Symbols to scan: {len(symbols_to_scan)}")

            alerts_sent = 0

            for symbol in symbols_to_scan:
                try:
                    gate_info = gate_tickers.get(symbol)
                    cmc_info = cmc_coins.get(symbol, {})

                    if not gate_info:
                        continue

                    result = analyze_coin(gate_info, cmc_info)

                    if not result:
                        continue

                    source = signal_source(result["pass_1h"], result["pass_4h"])

                    if not can_send_alert(symbol, source):
                        continue

                    alert = build_alert(result)
                    send_telegram(alert)

                    alerts_sent += 1
                    time.sleep(1)

                except Exception as e:
                    print("Coin analyze error:", symbol, e)

            print(f"Scan done. Alerts sent: {alerts_sent}")

        except Exception as e:
            print("Main loop error:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()

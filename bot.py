import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask

# =========================
# KEEP ALIVE
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Multi Exchange Volume Hunter Bot is running ✅"

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

CMC_API_KEY = env_str("CMC_API_KEY")
USE_CMC_FILTER = env_bool("USE_CMC_FILTER", True)
CMC_TOP_N = env_int("CMC_TOP_N", 3000)

MIN_MARKET_CAP = env_float("MIN_MARKET_CAP", 10000000)
MAX_MARKET_CAP = env_float("MAX_MARKET_CAP", 1000000000)

CHECK_INTERVAL = env_int("CHECK_INTERVAL", 900)
MAX_COINS = env_int("MAX_COINS", 3000)
QUOTE_CURRENCY = env_str("QUOTE_CURRENCY", "USDT")

MAX_24H_CHANGE = env_float("MAX_24H_CHANGE", 25)
SIGNAL_COOLDOWN_MINUTES = env_int("SIGNAL_COOLDOWN_MINUTES", 60)

ENABLE_WELCOME_MESSAGE = env_bool("ENABLE_WELCOME_MESSAGE", True)

ENABLE_GATE = env_bool("ENABLE_GATE", True)
ENABLE_KUCOIN = env_bool("ENABLE_KUCOIN", True)
ENABLE_MEXC = env_bool("ENABLE_MEXC", True)
ENABLE_BYBIT = env_bool("ENABLE_BYBIT", True)
ENABLE_BITGET = env_bool("ENABLE_BITGET", True)
ENABLE_OKX = env_bool("ENABLE_OKX", True)

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
MIN_EXCHANGE_CONFIRMATIONS = env_int("MIN_EXCHANGE_CONFIRMATIONS", 1)

ENABLE_STABLECOIN_FILTER = env_bool("ENABLE_STABLECOIN_FILTER", True)
ENABLE_MEME_FILTER = env_bool("ENABLE_MEME_FILTER", True)
ENABLE_GAMING_FILTER = env_bool("ENABLE_GAMING_FILTER", True)
ENABLE_GAMBLING_FILTER = env_bool("ENABLE_GAMBLING_FILTER", True)
ENABLE_PREDICTION_MARKET_FILTER = env_bool("ENABLE_PREDICTION_MARKET_FILTER", True)


# =========================
# MEMORY
# =========================

last_alert_time = {}


# =========================
# FILTERS
# =========================

STABLECOINS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDD", "BUSD",
    "PYUSD", "USD1", "EUR", "EURS", "USTC"
}

MEME_KEYWORDS = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME",
    "TURBO", "BABYDOGE", "ELON", "MOG", "BRETT"
}

GAMING_KEYWORDS = {
    "GAME", "GAMING", "PLAY", "AXS", "SAND", "MANA", "GALA",
    "ILV", "YGG", "ALICE", "ENJ"
}

GAMBLING_KEYWORDS = {
    "BET", "CASINO", "GAMBLE", "LOTTO", "POKER"
}

PREDICTION_KEYWORDS = {
    "PRED", "POLYMARKET", "FORECAST"
}

LEVERAGED_KEYWORDS = {
    "3L", "3S", "5L", "5S", "BULL", "BEAR", "UP", "DOWN"
}


def is_excluded(symbol):
    s = symbol.upper()

    if any(k in s for k in LEVERAGED_KEYWORDS):
        return True

    if ENABLE_STABLECOIN_FILTER and s in STABLECOINS:
        return True

    if ENABLE_MEME_FILTER and any(k in s for k in MEME_KEYWORDS):
        return True

    if ENABLE_GAMING_FILTER and any(k in s for k in GAMING_KEYWORDS):
        return True

    if ENABLE_GAMBLING_FILTER and any(k in s for k in GAMBLING_KEYWORDS):
        return True

    if ENABLE_PREDICTION_MARKET_FILTER and any(k in s for k in PREDICTION_KEYWORDS):
        return True

    return False


# =========================
# FORMAT
# =========================

def fmt_usd(v):
    try:
        return f"${float(v):,.0f}"
    except:
        return "$0"

def fmt_num(v):
    try:
        return f"{float(v):,.2f}"
    except:
        return "0"

def now_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================
# TELEGRAM
# =========================

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram variables missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.status_code != 200:
            print("Telegram error:", r.text)
    except Exception as e:
        print("Telegram exception:", e)


# =========================
# CMC
# =========================

def get_cmc_coins():
    if not USE_CMC_FILTER:
        return {}

    if not CMC_API_KEY:
        print("CMC_API_KEY missing")
        return {}

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accept": "application/json"
    }

    coins = {}
    start = 1
    limit = 500

    while len(coins) < CMC_TOP_N:
        params = {
            "start": start,
            "limit": min(limit, CMC_TOP_N - len(coins)),
            "convert": "USD"
        }

        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)

            if r.status_code != 200:
                print("CMC error:", r.status_code, r.text)
                break

            data = r.json().get("data", [])

            if not data:
                break

            for coin in data:
                symbol = str(coin.get("symbol", "")).upper()
                name = coin.get("name", "")
                rank = coin.get("cmc_rank", 0)

                quote = coin.get("quote", {}).get("USD", {})
                market_cap = float(quote.get("market_cap") or 0)
                volume_24h = float(quote.get("volume_24h") or 0)
                change_24h = float(quote.get("percent_change_24h") or 0)

                if is_excluded(symbol):
                    continue

                if market_cap < MIN_MARKET_CAP:
                    continue

                if market_cap > MAX_MARKET_CAP:
                    continue

                if abs(change_24h) > MAX_24H_CHANGE:
                    continue

                coins[symbol] = {
                    "symbol": symbol,
                    "name": name,
                    "rank": rank,
                    "market_cap": market_cap,
                    "cmc_volume_24h": volume_24h,
                    "cmc_change_24h": change_24h
                }

            start += limit
            time.sleep(1)

        except Exception as e:
            print("CMC exception:", e)
            break

    print(f"CMC loaded: {len(coins)}")
    return coins


# =========================
# EXCHANGE HELPERS
# =========================

def safe_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=25)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None


def normalize_tf_for_exchange(exchange, tf):
    mapping = {
        "gate": {"1h": "1h", "4h": "4h"},
        "kucoin": {"1h": "1hour", "4h": "4hour"},
        "mexc": {"1h": "60m", "4h": "4h"},
        "bybit": {"1h": "60", "4h": "240"},
        "bitget": {"1h": "1H", "4h": "4H"},
        "okx": {"1h": "1H", "4h": "4H"}
    }
    return mapping.get(exchange, {}).get(tf, tf)


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


def analyze_rows(rows, lookback, min_ratio, min_volume_usd):
    if not rows or len(rows) < lookback + 1:
        return None

    df = pd.DataFrame(rows)
    df = df.sort_values("time").reset_index(drop=True)

    current = df.iloc[-1]
    current_volume_usd = float(current["quote_volume"])

    avg_volume_usd = float(
        df["quote_volume"].iloc[-lookback-1:-1].mean()
    )

    if avg_volume_usd <= 0:
        return None

    ratio = current_volume_usd / avg_volume_usd

    passed = (
        current_volume_usd >= min_volume_usd
        and ratio >= min_ratio
    )

    return {
        "price": float(current["close"]),
        "current_volume_usd": current_volume_usd,
        "avg_volume_usd": avg_volume_usd,
        "volume_ratio": ratio,
        "rating": rate_volume(ratio),
        "passed": passed
    }


# =========================
# GATE
# =========================

def gate_symbol(symbol):
    return f"{symbol}_{QUOTE_CURRENCY}"

def gate_tickers():
    data = safe_get("https://api.gateio.ws/api/v4/spot/tickers")
    result = {}

    if not isinstance(data, list):
        return result

    for item in data:
        pair = item.get("currency_pair", "")
        if not pair.endswith(f"_{QUOTE_CURRENCY}"):
            continue

        base = pair.replace(f"_{QUOTE_CURRENCY}", "").upper()

        if is_excluded(base):
            continue

        try:
            result[base] = {
                "exchange": "Gate",
                "symbol": base,
                "pair": pair,
                "display": pair.replace("_", "/"),
                "last": float(item.get("last", 0)),
                "volume_24h": float(item.get("quote_volume", 0)),
                "change_24h": float(item.get("change_percentage", 0))
            }
        except:
            continue

    return result


def gate_candles(pair, tf, limit):
    interval = normalize_tf_for_exchange("gate", tf)
    data = safe_get(
        "https://api.gateio.ws/api/v4/spot/candlesticks",
        {"currency_pair": pair, "interval": interval, "limit": limit}
    )

    rows = []
    if not isinstance(data, list):
        return rows

    for c in data:
        try:
            rows.append({
                "time": int(c[0]),
                "quote_volume": float(c[1]),
                "close": float(c[2])
            })
        except:
            continue

    return rows


# =========================
# KUCOIN
# =========================

def kucoin_tickers():
    data = safe_get("https://api.kucoin.com/api/v1/market/allTickers")
    result = {}

    tickers = data.get("data", {}).get("ticker", []) if isinstance(data, dict) else []

    for item in tickers:
        pair = item.get("symbol", "")
        suffix = f"-{QUOTE_CURRENCY}"

        if not pair.endswith(suffix):
            continue

        base = pair.replace(suffix, "").upper()

        if is_excluded(base):
            continue

        try:
            result[base] = {
                "exchange": "KuCoin",
                "symbol": base,
                "pair": pair,
                "display": pair.replace("-", "/"),
                "last": float(item.get("last", 0)),
                "volume_24h": float(item.get("volValue", 0)),
                "change_24h": float(item.get("changeRate", 0)) * 100
            }
        except:
            continue

    return result


def kucoin_candles(pair, tf, limit):
    interval = normalize_tf_for_exchange("kucoin", tf)
    data = safe_get(
        "https://api.kucoin.com/api/v1/market/candles",
        {"symbol": pair, "type": interval}
    )

    rows = []
    candles = data.get("data", []) if isinstance(data, dict) else []

    for c in candles[:limit]:
        try:
            close = float(c[2])
            quote_volume = float(c[6])
            rows.append({
                "time": int(c[0]),
                "quote_volume": quote_volume,
                "close": close
            })
        except:
            continue

    return rows


# =========================
# MEXC
# =========================

def mexc_pair(symbol):
    return f"{symbol}{QUOTE_CURRENCY}"

def mexc_tickers():
    data = safe_get("https://api.mexc.com/api/v3/ticker/24hr")
    result = {}

    if not isinstance(data, list):
        return result

    for item in data:
        pair = item.get("symbol", "")

        if not pair.endswith(QUOTE_CURRENCY):
            continue

        base = pair.replace(QUOTE_CURRENCY, "").upper()

        if is_excluded(base):
            continue

        try:
            result[base] = {
                "exchange": "MEXC",
                "symbol": base,
                "pair": pair,
                "display": f"{base}/{QUOTE_CURRENCY}",
                "last": float(item.get("lastPrice", 0)),
                "volume_24h": float(item.get("quoteVolume", 0)),
                "change_24h": float(item.get("priceChangePercent", 0))
            }
        except:
            continue

    return result


def mexc_candles(pair, tf, limit):
    interval = normalize_tf_for_exchange("mexc", tf)
    data = safe_get(
        "https://api.mexc.com/api/v3/klines",
        {"symbol": pair, "interval": interval, "limit": limit}
    )

    rows = []
    if not isinstance(data, list):
        return rows

    for c in data:
        try:
            rows.append({
                "time": int(c[0]) // 1000,
                "quote_volume": float(c[7]),
                "close": float(c[4])
            })
        except:
            continue

    return rows


# =========================
# BYBIT
# =========================

def bybit_tickers():
    data = safe_get(
        "https://api.bybit.com/v5/market/tickers",
        {"category": "spot"}
    )

    result = {}
    tickers = data.get("result", {}).get("list", []) if isinstance(data, dict) else []

    for item in tickers:
        pair = item.get("symbol", "")

        if not pair.endswith(QUOTE_CURRENCY):
            continue

        base = pair.replace(QUOTE_CURRENCY, "").upper()

        if is_excluded(base):
            continue

        try:
            result[base] = {
                "exchange": "Bybit",
                "symbol": base,
                "pair": pair,
                "display": f"{base}/{QUOTE_CURRENCY}",
                "last": float(item.get("lastPrice", 0)),
                "volume_24h": float(item.get("turnover24h", 0)),
                "change_24h": float(item.get("price24hPcnt", 0)) * 100
            }
        except:
            continue

    return result


def bybit_candles(pair, tf, limit):
    interval = normalize_tf_for_exchange("bybit", tf)
    data = safe_get(
        "https://api.bybit.com/v5/market/kline",
        {
            "category": "spot",
            "symbol": pair,
            "interval": interval,
            "limit": limit
        }
    )

    rows = []
    candles = data.get("result", {}).get("list", []) if isinstance(data, dict) else []

    for c in candles:
        try:
            rows.append({
                "time": int(c[0]) // 1000,
                "quote_volume": float(c[6]),
                "close": float(c[4])
            })
        except:
            continue

    return rows


# =========================
# BITGET
# =========================

def bitget_tickers():
    data = safe_get(
        "https://api.bitget.com/api/v2/spot/market/tickers"
    )

    result = {}
    tickers = data.get("data", []) if isinstance(data, dict) else []

    for item in tickers:
        pair = item.get("symbol", "")

        if not pair.endswith(QUOTE_CURRENCY):
            continue

        base = pair.replace(QUOTE_CURRENCY, "").upper()

        if is_excluded(base):
            continue

        try:
            result[base] = {
                "exchange": "Bitget",
                "symbol": base,
                "pair": pair,
                "display": f"{base}/{QUOTE_CURRENCY}",
                "last": float(item.get("lastPr", 0)),
                "volume_24h": float(item.get("quoteVolume", 0)),
                "change_24h": float(item.get("changeUtc24h", 0)) * 100
            }
        except:
            continue

    return result


def bitget_candles(pair, tf, limit):
    granularity = normalize_tf_for_exchange("bitget", tf)
    data = safe_get(
        "https://api.bitget.com/api/v2/spot/market/candles",
        {
            "symbol": pair,
            "granularity": granularity,
            "limit": str(limit)
        }
    )

    rows = []
    candles = data.get("data", []) if isinstance(data, dict) else []

    for c in candles:
        try:
            open_price = float(c[1])
            close = float(c[4])
            base_volume = float(c[5])
            quote_volume = float(c[6]) if len(c) > 6 else base_volume * close

            rows.append({
                "time": int(c[0]) // 1000,
                "quote_volume": quote_volume,
                "close": close
            })
        except:
            continue

    return rows


# =========================
# OKX
# =========================

def okx_tickers():
    data = safe_get(
        "https://www.okx.com/api/v5/market/tickers",
        {"instType": "SPOT"}
    )

    result = {}
    tickers = data.get("data", []) if isinstance(data, dict) else []

    for item in tickers:
        inst = item.get("instId", "")
        suffix = f"-{QUOTE_CURRENCY}"

        if not inst.endswith(suffix):
            continue

        base = inst.replace(suffix, "").upper()

        if is_excluded(base):
            continue

        try:
            last = float(item.get("last", 0))
            open24h = float(item.get("open24h", 0))
            change = ((last - open24h) / open24h * 100) if open24h > 0 else 0

            result[base] = {
                "exchange": "OKX",
                "symbol": base,
                "pair": inst,
                "display": inst.replace("-", "/"),
                "last": last,
                "volume_24h": float(item.get("volCcy24h", 0)),
                "change_24h": change
            }
        except:
            continue

    return result


def okx_candles(pair, tf, limit):
    bar = normalize_tf_for_exchange("okx", tf)
    data = safe_get(
        "https://www.okx.com/api/v5/market/candles",
        {
            "instId": pair,
            "bar": bar,
            "limit": str(limit)
        }
    )

    rows = []
    candles = data.get("data", []) if isinstance(data, dict) else []

    for c in candles:
        try:
            close = float(c[4])
            quote_volume = float(c[7])
            rows.append({
                "time": int(c[0]) // 1000,
                "quote_volume": quote_volume,
                "close": close
            })
        except:
            continue

    return rows


# =========================
# EXCHANGE REGISTRY
# =========================

EXCHANGES = []

if ENABLE_GATE:
    EXCHANGES.append({
        "name": "Gate",
        "ticker_func": gate_tickers,
        "candle_func": gate_candles
    })

if ENABLE_KUCOIN:
    EXCHANGES.append({
        "name": "KuCoin",
        "ticker_func": kucoin_tickers,
        "candle_func": kucoin_candles
    })

if ENABLE_MEXC:
    EXCHANGES.append({
        "name": "MEXC",
        "ticker_func": mexc_tickers,
        "candle_func": mexc_candles
    })

if ENABLE_BYBIT:
    EXCHANGES.append({
        "name": "Bybit",
        "ticker_func": bybit_tickers,
        "candle_func": bybit_candles
    })

if ENABLE_BITGET:
    EXCHANGES.append({
        "name": "Bitget",
        "ticker_func": bitget_tickers,
        "candle_func": bitget_candles
    })

if ENABLE_OKX:
    EXCHANGES.append({
        "name": "OKX",
        "ticker_func": okx_tickers,
        "candle_func": okx_candles
    })


# =========================
# ANALYSIS
# =========================

def analyze_timeframes(exchange, ticker):
    candle_func = exchange["candle_func"]
    pair = ticker["pair"]

    result_1h = None
    result_4h = None

    if ENABLE_1H:
        rows = candle_func(pair, TIMEFRAME_1H, VOLUME_LOOKBACK_1H + 5)
        result_1h = analyze_rows(
            rows,
            VOLUME_LOOKBACK_1H,
            MIN_VOLUME_RATIO_1H,
            MIN_CURRENT_VOLUME_USD_1H
        )

    if ENABLE_4H:
        rows = candle_func(pair, TIMEFRAME_4H, VOLUME_LOOKBACK_4H + 5)
        result_4h = analyze_rows(
            rows,
            VOLUME_LOOKBACK_4H,
            MIN_VOLUME_RATIO_4H,
            MIN_CURRENT_VOLUME_USD_4H
        )

    pass_1h = result_1h["passed"] if result_1h else False
    pass_4h = result_4h["passed"] if result_4h else False

    if REQUIRE_BOTH_TIMEFRAMES:
        passed = pass_1h and pass_4h
    else:
        passed = pass_1h or pass_4h

    return {
        "exchange": ticker["exchange"],
        "display": ticker["display"],
        "last": ticker["last"],
        "volume_24h": ticker["volume_24h"],
        "change_24h": ticker["change_24h"],
        "tf_1h": result_1h,
        "tf_4h": result_4h,
        "pass_1h": pass_1h,
        "pass_4h": pass_4h,
        "passed": passed
    }


def signal_source(pass_1h, pass_4h):
    if pass_1h and pass_4h:
        return "1H + 4H"
    if pass_1h:
        return "1H فقط"
    if pass_4h:
        return "4H فقط"
    return "لا يوجد"


def best_entry_tf(pass_1h, pass_4h):
    if pass_1h and pass_4h:
        return "4H — تأكيد أقوى"
    if pass_1h:
        return "1H — دخول مبكر"
    if pass_4h:
        return "4H — إشارة أهدأ وأقوى"
    return "لا يوجد"


def score_by_confirmations(confirmations, pass_both_any):
    if confirmations >= 4:
        return "10/10"
    if confirmations == 3:
        return "9/10"
    if confirmations == 2:
        return "8/10"
    if pass_both_any:
        return "7/10"
    return "6/10"


def can_send_alert(symbol):
    now = datetime.now()

    if symbol not in last_alert_time:
        last_alert_time[symbol] = now
        return True

    diff = now - last_alert_time[symbol]

    if diff >= timedelta(minutes=SIGNAL_COOLDOWN_MINUTES):
        last_alert_time[symbol] = now
        return True

    return False


# =========================
# MESSAGE
# =========================

def tf_text(label, data):
    if not data:
        return f"❌ {label}: لا توجد بيانات"

    icon = "✅" if data["passed"] else "❌"

    return (
        f"{icon} {label} | "
        f"Ratio {fmt_num(data['volume_ratio'])}x | "
        f"Vol {fmt_usd(data['current_volume_usd'])} | "
        f"{data['rating']}"
    )


def build_alert(symbol, cmc, exchange_results):
    confirmations = len(exchange_results)

    pass_1h_any = any(r["pass_1h"] for r in exchange_results)
    pass_4h_any = any(r["pass_4h"] for r in exchange_results)
    pass_both_any = any(r["pass_1h"] and r["pass_4h"] for r in exchange_results)

    source = signal_source(pass_1h_any, pass_4h_any)
    best_tf = best_entry_tf(pass_1h_any, pass_4h_any)
    score = score_by_confirmations(confirmations, pass_both_any)

    name = cmc.get("name", symbol)
    rank = cmc.get("rank", "N/A")
    market_cap = cmc.get("market_cap", 0)
    cmc_volume_24h = cmc.get("cmc_volume_24h", 0)
    cmc_change_24h = cmc.get("cmc_change_24h", 0)

    lines = []

    for r in exchange_results:
        lines.append(
            f"""
🏦 <b>{r['exchange']}</b> — {r['display']}
• السعر: {r['last']}
• {tf_text("1H", r['tf_1h'])}
• {tf_text("4H", r['tf_4h'])}
• مصدر الإشارة: {signal_source(r['pass_1h'], r['pass_4h'])}
"""
        )

    exchanges_block = "\n".join(lines)

    return f"""
🚀 <b>MULTI-EXCHANGE VOLUME ALERT</b>

🪙 <b>{symbol}/{QUOTE_CURRENCY}</b>
📛 الاسم: {name}
🕒 الوقت: {now_time()}

━━━━━━━━━━━━━━

{exchanges_block}

━━━━━━━━━━━━━━

📊 <b>عدد المنصات المؤكدة:</b>
{confirmations}

🎯 <b>مصدر الإشارة العام:</b>
{source}

📈 <b>أفضل فريم للدخول:</b>
{best_tf}

⭐ <b>تقييم الإشارة:</b>
{score}

━━━━━━━━━━━━━━

🌐 <b>CoinMarketCap</b>
• Rank: {rank}
• Market Cap: {fmt_usd(market_cap)}
• 24H Volume: {fmt_usd(cmc_volume_24h)}
• 24H Change: {fmt_num(cmc_change_24h)}%

⚠️ تحليل فقط وليس نصيحة مالية.
"""


def send_welcome():
    enabled = [e["name"] for e in EXCHANGES]

    msg = f"""
🤖 <b>Multi Exchange Volume Hunter Started ✅</b>

━━━━━━━━━━━━━━

🏦 <b>المنصات المفعلة:</b>
{", ".join(enabled)}

🌐 <b>CoinMarketCap:</b>
• Top N: {CMC_TOP_N}
• Market Cap Min: {fmt_usd(MIN_MARKET_CAP)}
• Market Cap Max: {fmt_usd(MAX_MARKET_CAP)}

📊 <b>الفريمات:</b>
• 1H: {"✅" if ENABLE_1H else "❌"}
• 4H: {"✅" if ENABLE_4H else "❌"}

🎯 <b>شروط 1H:</b>
• Ratio ≥ {MIN_VOLUME_RATIO_1H}x
• Volume ≥ {fmt_usd(MIN_CURRENT_VOLUME_USD_1H)}

🎯 <b>شروط 4H:</b>
• Ratio ≥ {MIN_VOLUME_RATIO_4H}x
• Volume ≥ {fmt_usd(MIN_CURRENT_VOLUME_USD_4H)}

⚙️ <b>الإعدادات:</b>
• الفحص كل: {CHECK_INTERVAL} ثانية
• Cooldown: {SIGNAL_COOLDOWN_MINUTES} دقيقة
• Require Both TF: {REQUIRE_BOTH_TIMEFRAMES}
• Min Exchange Confirmations: {MIN_EXCHANGE_CONFIRMATIONS}

✅ البوت الآن يراقب الفوليوم في أكثر من منصة.
"""
    send_telegram(msg)


# =========================
# MAIN
# =========================

def main():
    print("Multi Exchange Volume Hunter started ✅")

    if ENABLE_WELCOME_MESSAGE:
        send_welcome()

    while True:
        try:
            cmc_coins = get_cmc_coins()

            all_tickers = {}

            for ex in EXCHANGES:
                try:
                    print(f"Loading tickers: {ex['name']}")
                    all_tickers[ex["name"]] = ex["ticker_func"]()
                    print(f"{ex['name']} tickers: {len(all_tickers[ex['name']])}")
                    time.sleep(1)
                except Exception as e:
                    print(f"Ticker error {ex['name']}:", e)
                    all_tickers[ex["name"]] = {}

            if USE_CMC_FILTER:
                symbols = list(cmc_coins.keys())[:MAX_COINS]
            else:
                symbols_set = set()
                for tickers in all_tickers.values():
                    symbols_set.update(tickers.keys())
                symbols = list(symbols_set)[:MAX_COINS]

            alerts_sent = 0

            for symbol in symbols:
                try:
                    if is_excluded(symbol):
                        continue

                    cmc = cmc_coins.get(symbol, {})

                    exchange_results = []

                    for ex in EXCHANGES:
                        tickers = all_tickers.get(ex["name"], {})
                        ticker = tickers.get(symbol)

                        if not ticker:
                            continue

                        if abs(ticker.get("change_24h", 0)) > MAX_24H_CHANGE:
                            continue

                        result = analyze_timeframes(ex, ticker)

                        if result and result["passed"]:
                            exchange_results.append(result)

                        time.sleep(0.15)

                    if len(exchange_results) < MIN_EXCHANGE_CONFIRMATIONS:
                        continue

                    if not can_send_alert(symbol):
                        continue

                    alert = build_alert(symbol, cmc, exchange_results)
                    send_telegram(alert)

                    alerts_sent += 1
                    time.sleep(1)

                except Exception as e:
                    print("Symbol error:", symbol, e)

            print(f"Cycle done. Alerts sent: {alerts_sent}")

        except Exception as e:
            print("Main loop error:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()

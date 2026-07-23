import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import requests
import pandas as pd
import time
from datetime import datetime

# --- SERVIDOR WEB DUMMY ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot EMA Activo")

    def log_message(self, format, *args):
        return

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# --- CONFIGURACIÓN ---
SYMBOL = 'BTCUSDT'
TIMEFRAMES = ['5m', '15m', '1h']
EMA_PAIRS = [(9, 21), (21, 50), (50, 200)]
NTFY_TOPIC = 'BITCOIN-btc-EMA'
NTFY_URL = f'https://ntfy.sh/{NTFY_TOPIC}'

ema_states = {}

def get_binance_klines(symbol, interval, limit=300):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            df = pd.DataFrame(res.json(), columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
            ])
            df['close'] = df['close'].astype(float)
            return df
        return None
    except Exception as e:
        print(f"Error Binance ({interval}): {e}", flush=True)
        return None

def calculate_ema(df, period):
    return df['close'].ewm(span=period, adjust=False).mean()

def send_ntfy_alert(title, message, tags="chart_with_upwards_trend"):
    headers = {
        "Title": title.strip(),
        "Tags": tags,
        "Priority": "high"
    }
    try:
        requests.post(NTFY_URL, data=message.encode('utf-8'), headers=headers, timeout=10)
        print(f"🔔 ALERTA ENVIADA: {title}", flush=True)
    except Exception as e:
        print(f"Error ntfy: {e}", flush=True)

def check_crosses():
    global ema_states
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"--- [{now}] Chequeo de EMAs ---", flush=True)

    for tf in TIMEFRAMES:
        df = get_binance_klines(SYMBOL, tf)
        if df is None or len(df) < 200:
            continue

        for fast, slow in EMA_PAIRS:
            ema_fast = calculate_ema(df, fast).iloc[-1]
            ema_slow = calculate_ema(df, slow).iloc[-1]
            price = df['close'].iloc[-1]

            pair_key = f"{tf}_{fast}_{slow}"
            current_state = 'BULLISH' if ema_fast > ema_slow else 'BEARISH'

            # Muestra exactamente lo que está calculando para cada par
            print(f"[{tf}] EMA {fast}: {ema_fast:.2f} | EMA {slow}: {ema_slow:.2f} -> {current_state}", flush=True)

            if pair_key not in ema_states:
                ema_states[pair_key] = current_state
                continue

            if current_state != ema_states[pair_key]:
                if current_state == 'BULLISH':
                    title = f"🚀 CRUCE ALCISTA BTC ({tf})"
                    msg = f"EMA {fast} cruzó por ENCIMA de EMA {slow}.\nPrecio: ${price:,.2f}"
                    send_ntfy_alert(title, msg, tags="rocket,chart_with_upwards_trend")
                else:
                    title = f"⚠️ CRUCE BAJISTA BTC ({tf})"
                    msg = f"EMA {fast} cruzó por DEBAJO de EMA {slow}.\nPrecio: ${price:,.2f}"
                    send_ntfy_alert(title, msg, tags="warning,chart_with_downwards_trend")

                ema_states[pair_key] = current_state

def bot_loop():
    send_ntfy_alert("Bot Diagnóstico V2.1", "Log de valores activo.", tags="gear")
    while True:
        try:
            check_crosses()
        except Exception as e:
            print(f"Error loop: {e}", flush=True)
        time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    bot_loop()

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import requests
import pandas as pd
import json
import time
from datetime import datetime

# --- SERVIDOR WEB DUMMY PARA RENDER ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# Iniciar servidor web en segundo plano
threading.Thread(target=run_dummy_server, daemon=True).start()

# --- CONFIGURACIÓN DEL BOT ---
SYMBOL = 'BTCUSDT'
TIMEFRAMES = ['5m', '15m', '1h']
EMA_PAIRS = [(9, 21), (21, 50), (50, 200)]
NTFY_TOPIC = 'BITCOIN-btc-EMA'
NTFY_URL = f'https://ntfy.sh/{NTFY_TOPIC}'

last_signals = {}

def get_binance_klines(symbol, interval, limit=250):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        print(f"Error obteniendo datos ({interval}): {e}")
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
        print(f"Notificación enviada: {title}")
    except Exception as e:
        print(f"Error al enviar a ntfy: {e}")

def check_crosses():
    global last_signals
    print(f"--- Chequeando mercado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")

    for tf in TIMEFRAMES:
        df = get_binance_klines(SYMBOL, tf)
        if df is None or len(df) < 200:
            continue

        for fast, slow in EMA_PAIRS:
            ema_fast_col = f'EMA_{fast}'
            ema_slow_col = f'EMA_{slow}'

            df[ema_fast_col] = calculate_ema(df, fast)
            df[ema_slow_col] = calculate_ema(df, slow)

            # EVALUACIÓN EN TIEMPO REAL:
            # -2 es la vela anterior cerrada
            # -1 es la vela actual en movimiento
            prev_fast = df[ema_fast_col].iloc[-2]
            prev_slow = df[ema_slow_col].iloc[-2]
            curr_fast = df[ema_fast_col].iloc[-1]
            curr_slow = df[ema_slow_col].iloc[-1]

            signal_key = f"{tf}_{fast}_{slow}"

            if prev_fast <= prev_slow and curr_fast > curr_slow:
                if last_signals.get(signal_key) != 'BULLISH':
                    title = f"CRUCE ALCISTA BTC/USDT ({tf})"
                    msg = f"EMA {fast} cruzó por ENCIMA de EMA {slow} en {tf}.\nPrecio actual: ${df['close'].iloc[-1]:,.2f}"
                    send_ntfy_alert(title, msg, tags="rocket,chart_with_upwards_trend")
                    last_signals[signal_key] = 'BULLISH'

            elif prev_fast >= prev_slow and curr_fast < curr_slow:
                if last_signals.get(signal_key) != 'BEARISH':
                    title = f"CRUCE BAJISTA BTC/USDT ({tf})"
                    msg = f"EMA {fast} cruzó por DEBAJO de EMA {slow} en {tf}.\nPrecio actual: ${df['close'].iloc[-1]:,.2f}"
                    send_ntfy_alert(title, msg, tags="warning,chart_with_downwards_trend")
                    last_signals[signal_key] = 'BEARISH'

if __name__ == "__main__":
    send_ntfy_alert("Bot Actualizado: Modo Tiempo Real", "Alertas ajustadas para notificar al instante exacto del cruce.", tags="zap")
    while True:
        try:
            check_crosses()
        except Exception as e:
            print(f"Error en el bucle principal: {e}")
        time.sleep(60)

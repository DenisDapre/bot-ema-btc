import time
import requests
import pandas as pd
from flask import Flask
from threading import Thread
import traceback

app = Flask(__name__)

# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================
SYMBOL = "BTCUSDT"
NTFY_URL_BASE = "https://ntfy.sh/"
TOPIC_SWING = "BITCOIN-btc-EMA-SWING"
TOPIC_SCALP = "BITCOIN-btc-EMA-SCALP"

# Variables globales para evitar spam de alertas repetidas
last_alert_scalp = None
last_alert_swing = None

# ==========================================
# FUNCIONES DE UTILIDAD
# ==========================================
def send_ntfy_alert(topic, prefix, message):
    """
    Envía la notificación push vía ntfy.sh usando UTF-8 en el body para soportar emojis.
    """
    url = f"{NTFY_URL_BASE}{topic}"
    # Formateamos el mensaje final asegurando que el body vaya en UTF-8
    full_message = f"{prefix}\n\n{message}"
    
    try:
        response = requests.post(
            url,
            data=full_message.encode('utf-8'),
            headers={
                "Title": "Alerta Bot EMA BTC" # Header limpio en ASCII
            }
        )
        print(f"[{prefix}] Notificación enviada. Status: {response.status_code}")
    except Exception as e:
        print(f"Error al enviar notificación {prefix}: {e}")

def get_klines_df(interval, limit=100):
    """
    Descarga las velas de Binance y descarta la última (vela abierta).
    Calcula máximos, mínimos y cierres.
    """
    url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={interval}&limit={limit+1}"
    try:
        res = requests.get(url).json()
        # Descartamos la última vela (res[:-1]) porque aún no ha cerrado
        df = pd.DataFrame(res[:-1], columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
        ])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        return df
    except Exception as e:
        print(f"Error obteniendo datos de Binance para {interval}: {e}")
        return None

def calculate_ema(df, periods):
    """Calcula las EMAs especificadas en el DataFrame."""
    for period in periods:
        df[f'EMA_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
    return df

# ==========================================
# LÓGICA DE TRADING (SCALP & SWING)
# ==========================================
def check_scalp(df_1m, df_15m):
    """
    Modo SCALP:
    - Timeframe: 1m
    - EMAs: 9 y 21
    - Confluencia: Tendencia de 15m (EMA 9 > EMA 21)
    - Stop Loss: 8 velas atrás
    - R:B: 1.2
    """
    global last_alert_scalp
    
    df_1m = calculate_ema(df_1m, [9, 21])
    df_15m = calculate_ema(df_15m, [9, 21])
    
    # Condición de confluencia en 15m
    last_15m = df_15m.iloc[-1]
    trend_15m_bullish = last_15m['EMA_9'] > last_15m['EMA_21']
    trend_15m_bearish = last_15m['EMA_9'] < last_15m['EMA_21']

    # Condición de cruce en 1m
    last_1m = df_1m.iloc[-1]
    prev_1m = df_1m.iloc[-2]
    
    cross_up = (prev_1m['EMA_9'] <= prev_1m['EMA_21']) and (last_1m['EMA_9'] > last_1m['EMA_21'])
    cross_down = (prev_1m['EMA_9'] >= prev_1m['EMA_21']) and (last_1m['EMA_9'] < last_1m['EMA_21'])

    current_price = last_1m['close']
    timestamp = df_1m.iloc[-1]['timestamp']

    if cross_up and trend_15m_bullish and timestamp != last_alert_scalp:
        # Calcular Stop Loss (mínimo de 8 velas)
        sl = df_1m['low'].tail(8).min()
        risk = current_price - sl
        tp = current_price + (risk * 1.2)
        
        msg = (f"🟢 CRUCE ALCISTA (1m)\n"
               f"Precio: {current_price}\n"
               f"Stop Loss (8v): {sl:.2f}\n"
               f"Take Profit (1.2): {tp:.2f}\n"
               f"Confluencia 15m: OK ✅")
        send_ntfy_alert(TOPIC_SCALP, "🚀 [SCALP]", msg)
        last_alert_scalp = timestamp

    elif cross_down and trend_15m_bearish and timestamp != last_alert_scalp:
        sl = df_1m['high'].tail(8).max()
        risk = sl - current_price
        tp = current_price - (risk * 1.2)
        
        msg = (f"🔴 CRUCE BAJISTA (1m)\n"
               f"Precio: {current_price}\n"
               f"Stop Loss (8v): {sl:.2f}\n"
               f"Take Profit (1.2): {tp:.2f}\n"
               f"Confluencia 15m: OK ✅")
        send_ntfy_alert(TOPIC_SCALP, "⚠️ [SCALP]", msg)
        last_alert_scalp = timestamp

def check_swing(df_5m, df_1h):
    """
    Modo SWING:
    - Timeframe: 5m
    - EMAs: 9, 21, 50, 200 (Evaluamos 9/21 para entrada inicial)
    - Confluencia: Tendencia de 1h (EMA 9 > EMA 21)
    - Stop Loss: 20 velas atrás
    - R:B: 2.0
    """
    global last_alert_swing
    
    df_5m = calculate_ema(df_5m, [9, 21, 50, 200])
    df_1h = calculate_ema(df_1h, [9, 21])
    
    # Confluencia en 1h
    last_1h = df_1h.iloc[-1]
    trend_1h_bullish = last_1h['EMA_9'] > last_1h['EMA_21']
    trend_1h_bearish = last_1h['EMA_9'] < last_1h['EMA_21']

    # Cruce en 5m
    last_5m = df_5m.iloc[-1]
    prev_5m = df_5m.iloc[-2]
    
    cross_up = (prev_5m['EMA_9'] <= prev_5m['EMA_21']) and (last_5m['EMA_9'] > last_5m['EMA_21'])
    cross_down = (prev_5m['EMA_9'] >= prev_5m['EMA_21']) and (last_5m['EMA_9'] < last_5m['EMA_21'])

    current_price = last_5m['close']
    timestamp = df_5m.iloc[-1]['timestamp']

    if cross_up and trend_1h_bullish and timestamp != last_alert_swing:
        sl = df_5m['low'].tail(20).min()
        risk = current_price - sl
        tp = current_price + (risk * 2.0)
        
        msg = (f"🟢 CRUCE ALCISTA (5m)\n"
               f"Precio: {current_price}\n"
               f"Stop Loss (20v): {sl:.2f}\n"
               f"Take Profit (2.0): {tp:.2f}\n"
               f"Confluencia 1h: OK ✅")
        send_ntfy_alert(TOPIC_SWING, "🚀 [SWING]", msg)
        last_alert_swing = timestamp

    elif cross_down and trend_1h_bearish and timestamp != last_alert_swing:
        sl = df_5m['high'].tail(20).max()
        risk = sl - current_price
        tp = current_price - (risk * 2.0)
        
        msg = (f"🔴 CRUCE BAJISTA (5m)\n"
               f"Precio: {current_price}\n"
               f"Stop Loss (20v): {sl:.2f}\n"
               f"Take Profit (2.0): {tp:.2f}\n"
               f"Confluencia 1h: OK ✅")
        send_ntfy_alert(TOPIC_SWING, "⚠️ [SWING]", msg)
        last_alert_swing = timestamp


# ==========================================
# LOOP PRINCIPAL DEL BOT
# ==========================================
def bot_loop():
    print("Iniciando Bot EMA BTC - Modos: SCALP & SWING")
    while True:
        try:
            print(f"--- [{time.strftime('%Y-%m-%d %H:%M:%S')}] Chequeo de mercado ---")
            
            # 1. Descarga centralizada de datos (Ahorra llamadas a la API)
            df_1m = get_klines_df("1m")
            df_5m = get_klines_df("5m")
            df_15m = get_klines_df("15m")
            df_1h = get_klines_df("1h")
            
            # 2. Si las llamadas fueron exitosas, corremos las lógicas
            if all(v is not None for v in [df_1m, df_5m, df_15m, df_1h]):
                check_scalp(df_1m, df_15m)
                check_swing(df_5m, df_1h)
            
        except Exception as e:
            print(f"Error crítico en el loop: {e}")
            traceback.print_exc()
            
        # Esperar 30 segundos antes de volver a consultar
        time.sleep(30)

# ==========================================
# SERVIDOR FLASK (Para Render & Cron-job)
# ==========================================
@app.route('/')
def home():
    return "Bot EMA BTC funcionando. Modos: SCALP y SWING activos."

@app.route('/test-alert')
def test_alert():
    send_ntfy_alert(TOPIC_SWING, "[TEST-SWING]", "🧪 Prueba manual modo SWING")
    send_ntfy_alert(TOPIC_SCALP, "[TEST-SCALP]", "🧪 Prueba manual modo SCALP")
    return "Alertas de prueba enviadas a ambos topics."

def start_flask():
    app.run(host='0.0.0.0', port=10000)

if __name__ == '__main__':
    # Iniciamos el servidor web en un hilo secundario
    server = Thread(target=start_flask)
    server.start()
    
    # Iniciamos el loop del bot en el hilo principal
    bot_loop()

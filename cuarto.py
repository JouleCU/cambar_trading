import ccxt
import time
import logging
import os
import threading
from dotenv import load_dotenv
from message import enviar_alerta_telegram

load_dotenv()

# Cargar credenciales de variables de entorno
BINANCE_API_KEY = os.getenv('API_KEY')
BINANCE_SECRET_KEY = os.getenv('API_SECRET')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_ID')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Configuración del bot
binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET_KEY,
    'options': {'defaultType': 'spot'}
})

# Configuración de activos y estrategias
assets = {
    'FLOKI/USDT': {'tp': 0.02, 'sl': 0.01},  # Scalping
    'DOGE/USDT': {'tp': 0.02, 'sl': 0.01},  # Scalping
    'BTC/USDT': {'tp': 0.04, 'sl': 0.02},   # Swing
    'DOT/USDT': {'tp': 0.03, 'sl': 0.015}   # Swing
}

# Umbrales de capital y retiros
UMBRAL_CAPITAL = 5000  # Se reutiliza todo el capital hasta llegar a $5000
RETIRO_SEMANAL = 700  # Se retira $700 semanalmente una vez superado el umbral
PROFIT_SEMANAL_OBJETIVO = (850, 1000)  # Rango de profit entre $850 y $1000 después de los $5000

# Función para obtener el precio actual
def get_price(symbol):
    try:
        ticker = binance.fetch_ticker(symbol)
        return ticker['last']
    except Exception as e:
        logging.error(f'Error al obtener precio de {symbol}: {e}')
        enviar_alerta_telegram(f'⚠️ Error al obtener precio de {symbol}: {e}')
        return None

# Función para obtener balance y distribuir capital dinámicamente
def get_dynamic_capital():
    try:
        balance = binance.fetch_balance()
        usdt_balance = balance['total'].get('USDT', 0)
        
        if usdt_balance >= UMBRAL_CAPITAL:
            withdraw_amount = min(RETIRO_SEMANAL, usdt_balance - UMBRAL_CAPITAL)
            enviar_alerta_telegram(f'🔄 Retirando {withdraw_amount} USDT. Resto será reutilizado como capital.')
            usdt_balance -= withdraw_amount
        
        if usdt_balance <= 0:
            return {}
        
        num_activos = len(assets)
        capital_por_activo = usdt_balance / num_activos
        for symbol in assets:
            assets[symbol]['capital'] = capital_por_activo
        return assets
    except Exception as e:
        logging.error(f'Error al obtener balance: {e}')
        enviar_alerta_telegram(f'⚠️ Error al obtener balance: {e}')
        return {}

# Función de trading para cada activo
def trade(symbol, params):
    while True:
        price = get_price(symbol)
        if price is None:
            continue
        
        try:
            trade_amount = params['capital'] / price
            if params['capital'] > 0:
                if str.upper(os.getenv('BUY')) == "YES":
                    order = binance.create_market_buy_order(symbol, trade_amount)
                entry_price = price
                tp_price = entry_price * (1 + params['tp'])
                sl_price = entry_price * (1 - params['sl'])
                enviar_alerta_telegram(f'🚀 Compra en {symbol} a {entry_price}\nTP: {tp_price} | SL: {sl_price}')
        except Exception as e:
            logging.error(f'Error en la compra de {symbol}: {e}')
            enviar_alerta_telegram(f'⚠️ Error en la compra de {symbol}: {e}')
            continue
        
        while True:
            price = get_price(symbol)
            print(f'Precio actual {symbol}: {price}')
            if price is None:
                continue
            try:
                if price >= tp_price or price <= sl_price:
                    if str.upper(os.getenv('SELL')) == "YES":
                        binance.create_market_sell_order(symbol, trade_amount)
                    enviar_alerta_telegram(f'✅ Venta realizada para {symbol} a {price}')
                    break
            except Exception as e:
                logging.error(f'Error en la venta de {symbol}: {e}')
                enviar_alerta_telegram(f'⚠️ Error en la venta de {symbol}: {e}')
                break
        
        time.sleep(10)  # Ajuste para mayor rapidez en toma de decisiones

# Función principal para iniciar múltiples hilos
def start_trading():
    assets_con_capital = get_dynamic_capital()
    if not assets_con_capital:
        enviar_alerta_telegram('⚠️ No hay capital disponible para operar.')
        return
    
    threads = []
    for symbol, params in assets_con_capital.items():
        thread = threading.Thread(target=trade, args=(symbol, params))
        thread.start()
        threads.append(thread)
    
    for thread in threads:
        thread.join()

# Iniciar el bot de trading en paralelo
if __name__ == '__main__':
    try:
        enviar_alerta_telegram('🤖 Bot de trading optimizado iniciado.')
        start_trading()
    except Exception as e:
        logging.error(f'Error en el bot: {e}')
        enviar_alerta_telegram(f'⚠️ Error en el bot: {e}')
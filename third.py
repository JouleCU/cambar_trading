import ccxt
import time
import logging
import os
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

# Umbral para realizar retiros
RETIRO_SEMANAL = 350  # Monto a retirar semanalmente
UMBRAL_CAPITAL = 3000  # Una vez superado este capital, se retira el excedente


# Función para obtener el precio actual
def get_price(symbol):
    try:
        ticker = binance.fetch_ticker(symbol)
        return ticker['last']
    except Exception as e:
        logging.error(f'Error al obtener precio de {symbol}: {e}')
        enviar_alerta_telegram(f'⚠️ Error al obtener precio de {symbol}: {e}')
        return None

# Función para analizar RSI y MACD para evitar falsas señales
def check_market_conditions(symbol):
    try:
        ohlcv = binance.fetch_ohlcv(symbol, timeframe='15m', limit=50)
        close_prices = [x[4] for x in ohlcv]
        rsi = calculate_rsi(close_prices)
        macd = calculate_macd(close_prices)
        volume = sum([x[5] for x in ohlcv[-5:]])  # Volumen de las últimas 5 velas

        # Condiciones para operar
        if rsi < 30 and macd > 0 and volume > 1000000:
            return 'COMPRA'
        elif rsi > 70 and macd < 0 and volume > 1000000:
            return 'VENTA'
        else:
            return 'ESPERA'
    except Exception as e:
        logging.error(f'Error en análisis de mercado: {e}')
        return 'ESPERA'

# Función para calcular RSI
def calculate_rsi(prices, period=14):
    gains = [prices[i] - prices[i-1] for i in range(1, len(prices)) if prices[i] > prices[i-1]]
    losses = [prices[i-1] - prices[i] for i in range(1, len(prices)) if prices[i] < prices[i-1]]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    return 100 - (100 / (1 + rs))

# Función para calcular MACD
def calculate_macd(prices, short_period=12, long_period=26, signal_period=9):
    short_ema = sum(prices[-short_period:]) / short_period
    long_ema = sum(prices[-long_period:]) / long_period
    macd_line = short_ema - long_ema
    signal_line = sum(prices[-signal_period:]) / signal_period
    return macd_line - signal_line

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

# Función de trading automatizado
def trade():
    while True:
        assets_con_capital = get_dynamic_capital()
        if not assets_con_capital:
            enviar_alerta_telegram('⚠️ No hay capital disponible para operar.')
            time.sleep(60)
            continue
        
        for symbol, params in assets_con_capital.items():
            market_condition = check_market_conditions(symbol)
            if market_condition != 'COMPRA':
                continue
            
            price = get_price(symbol)
            if price is None:
                continue

            try:
                trade_amount = params['capital'] / price
                order = binance.create_market_buy_order(symbol, trade_amount)
                entry_price = price
                tp_price = entry_price * (1 + params['tp'])
                sl_price = entry_price * (1 - params['sl'])
                enviar_alerta_telegram(f'🚀 Compra en {symbol} a {entry_price}\nTP: {tp_price} | SL: {sl_price}')
            except Exception as e:
                logging.error(f'Error en la compra de {symbol}: {e}')
                enviar_alerta_telegram(f'⚠️ Error en la compra de {symbol}: {e}')
                continue
        
        time.sleep(60)

# Iniciar el bot de trading
if __name__ == '__main__':
    balance = binance.fetch_balance()
    print(balance)
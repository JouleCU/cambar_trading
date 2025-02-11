import ccxt
import time
from loguru import logger
import os
from telegram import Bot
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
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN)

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
        logger.info("Got price")
        return ticker['last']
    except Exception as e:
        logger.error(f'Error al obtener precio de {symbol}: {e}')
        enviar_alerta_telegram(f'⚠️ Error al obtener precio de {symbol}: {e}')
        return None

# Función para obtener balance y distribuir capital dinámicamente
def get_dynamic_capital():
    try:
        balance = binance.fetch_balance()
        usdt_balance = balance['total'].get('USDT', 0)
        logger.info(f"USDT balance: {usdt_balance} / General balance {balance}")
        if usdt_balance >= UMBRAL_CAPITAL:
            withdraw_amount = min(RETIRO_SEMANAL, usdt_balance - UMBRAL_CAPITAL)
            enviar_alerta_telegram(f'🔄 Retirando {withdraw_amount} USDT. Resto será reutilizado como capital.')
            # Aquí puedes agregar la lógica para realizar el retiro automático si lo deseas
            usdt_balance -= withdraw_amount
        
        
        if usdt_balance <= 0:
            return {}
        
        num_activos = len(assets)
        capital_por_activo = usdt_balance / num_activos
        for symbol in assets:
            assets[symbol]['capital'] = capital_por_activo
        return assets
    except Exception as e:
        logger.error(f'Error al obtener balance: {e}')
        enviar_alerta_telegram(f'⚠️ Error al obtener balance: {e}')
        return {}

# Función de trading automatizado
def trade():
    while True:
        assets_con_capital = get_dynamic_capital()
        logger.info(f"Assets with capital {assets_con_capital}")
        if not assets_con_capital:
            enviar_alerta_telegram('⚠️ No hay capital disponible para operar.')
            time.sleep(60)
            continue
        
        for symbol, params in assets_con_capital.items():
            price = get_price(symbol)
            if price is None:
                continue

            try:
                trade_amount = params['capital'] / price
                
                # Comprar si hay capital suficiente
                if params['capital'] > 0:
                    order = binance.create_market_buy_order(symbol, trade_amount)
                    entry_price = price
                    tp_price = entry_price * (1 + params['tp'])
                    sl_price = entry_price * (1 - params['sl'])
                    enviar_alerta_telegram(f'🚀 Compra realizada en {symbol} a {entry_price}\nTP: {tp_price} | SL: {sl_price}')
            except Exception as e:
                logger.error(f'Error en la compra de {symbol}: {e}')
                enviar_alerta_telegram(f'⚠️ Error en la compra de {symbol}: {e}')
                continue
            
            # Verificar si alcanza TP o SL
            price = get_price(symbol)
            if price is None:
                continue

            try:
                if price >= tp_price:
                    binance.create_market_sell_order(symbol, trade_amount)
                    enviar_alerta_telegram(f'✅ Venta en TP alcanzada para {symbol} a {price}')
                elif price <= sl_price:
                    binance.create_market_sell_order(symbol, trade_amount)
                    enviar_alerta_telegram(f'⛔ Venta en SL alcanzada para {symbol} a {price}')
            except Exception as e:
                logger.error(f'Error en la venta de {symbol}: {e}')
                enviar_alerta_telegram(f'⚠️ Error en la venta de {symbol}: {e}')
        
        time.sleep(60)  # Esperar 1 minuto antes de la próxima verificación

# Iniciar el bot de trading
if __name__ == '__main__':
    try:
        enviar_alerta_telegram('🤖 Bot de trading iniciado.')
        trade()
    except Exception as e:
        logger.error(f'Error en el bot: {e}')
        enviar_alerta_telegram(f'⚠️ Error en el bot: {e}')
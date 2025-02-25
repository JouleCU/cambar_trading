import ccxt
import asyncio
import logging
import os
import ta
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from message import enviar_alerta_telegram
from datetime import datetime
from scipy.signal import find_peaks

# Cargar credenciales de variables de entorno
load_dotenv()
BINANCE_API_KEY = os.getenv('API_KEY')
BINANCE_SECRET_KEY = os.getenv('API_SECRET')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_ID')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Configuración del bot
binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET_KEY,
    'options': {'defaultType': 'spot'},
    'rateLimit': 1200  # Optimización para evitar sobrecarga de llamadas
})

# Configuración de activos y estrategias (optimizadas)
assets = {
    'FLOKI/USDT': {'strategy': 'scalping', 'tp': 0.035, 'sl': 0.009},  # Scalping optimizado para FLOKI
    'DOGE/USDT': {'strategy': 'scalping', 'tp': 0.03, 'sl': 0.01},     # Scalping optimizado
    'BTC/USDT': {'strategy': 'swing', 'tp': 0.04, 'sl': 0.01},         # Swing optimizado
    'SOL/USDT': {'strategy': 'swing', 'tp': 0.035, 'sl': 0.01}         # Swing optimizado
}

# Umbrales de capital y retiros
UMBRAL_CAPITAL = 5000  # Capital objetivo antes de activar retiros
RETIRO_SEMANAL = 700   # Retiro semanal una vez alcanzado UMBRAL_CAPITAL
PROFIT_SEMANAL_MIENTRAS_SUBE = 450  # Profit semanal hasta llegar a $5000
PROFIT_SEMANAL_OBJETIVO = (850, 1000)  # Rango de profit semanal después de $5000
CAPITAL_INICIAL = 2400  # Capital inicial ajustado a $2400

# Estado global del bot
capital_actual = CAPITAL_INICIAL
capital_por_moneda = {
    'FLOKI/USDT': 400, 'DOGE/USDT': 400,  # Más volatile, menos capital
    'BTC/USDT': 800, 'SOL/USDT': 800      # Menos volatile, más capital
}
profits_semanales = 0
ultimo_retiro = pd.Timestamp.now()

# Comisión de Binance por operación (0.1% spot)
COMMISSION_RATE = 0.001  # 0.1%



# Función para ejecutar trades con órdenes optimizadas, manejo de errores, comisiones, slippage y stop loss dinámico
def ejecutar_trade(symbol, params):
    global capital_actual, capital_por_moneda, profits_semanales, ultimo_retiro
    
    df = get_market_data(symbol)
    if df is None or (symbol in ['FLOKI/USDT', 'DOGE/USDT'] and df['volume'].iloc[-1] * df['close'].iloc[-1] < (800000 if symbol == 'FLOKI/USDT' else 2000000)):
        return
    
    current_time = datetime.now(datetime.timezone.utc).hour
    if 0 <= current_time < 6:
        logging.info(f"Horas de baja volatilidad en {symbol}, operación pospuesta.")
        return
    
    current_price = df['close'].iloc[-1]
    volume_mean = df['volume'].rolling(window=20).mean().iloc[-1]
    atr = df['atr'].iloc[-1]
    trade_amount = round(capital_por_moneda[symbol] / (current_price * (1 + COMMISSION_RATE)), 6)  # Ajuste para comisiones
    
    # Validación de monto mínimo de Binance
    if trade_amount < binance.markets[symbol]['limits']['amount']['min']:
        logging.warning(f"⚠️ Monto de trade demasiado bajo en {symbol}, evitando orden.")
        enviar_alerta_telegram(f'⚠️ Monto de trade demasiado bajo en {symbol}.')
        return
    
    # Verificar capital antes de operar
    if capital_por_moneda[symbol] < 50:  # Mínimo para operar por moneda
        logging.warning(f'Capital insuficiente para {symbol}: {capital_por_moneda[symbol]}')
        enviar_alerta_telegram(f'⚠️ Capital insuficiente para {symbol}: {capital_por_moneda[symbol]}')
        return
    
    # Filtro de tendencia con ADX ajustado
    adx_threshold = 20 if assets[symbol]['strategy'] == 'scalping' else 25
    if df['adx'].iloc[-1] < adx_threshold:  # ADX bajo indica rango, evita operaciones
        return
    
    # Ajuste dinámico de umbral de volumen por volatilidad
    volume_threshold = volume_mean * (1.05 + 0.1 * (df['atr'].iloc[-1] / df['atr'].mean()))
    
    # Estrategia de compra (optimizada para maximizar ganancias, sin depender de Ondas de Elliott)
    if (df['smc_zone'].iloc[-1] in ['Potential_Accumulation', 'Fair_Value_Gap']) \
       and df['rsi'].iloc[-1] < 55 and df['close'].iloc[-1] > df['ema_20'].iloc[-1] * 0.98 \
       and df['volume'].iloc[-1] > volume_threshold \
       and (df['stoch_k'].iloc[-1] < 20 or df['stoch_d'].iloc[-1] < 20):
        # Stop Loss dinámico para scalping (FLOKI/DOGE), fijo para swing (BTC/SOL)
        dynamic_sl = min(0.015, 1.5 * df['atr'].iloc[-1] / current_price) if assets[symbol]['strategy'] == 'scalping' else params['sl']
        sl_price = current_price - (current_price * dynamic_sl)
        tp_price = current_price * (1 + params['tp'])
        try:
            if assets[symbol]['strategy'] == 'scalping':  # Orden limitada para FLOKI/DOGE
                order = binance.create_limit_buy_order(symbol, trade_amount, current_price * 0.995)  # 0.5% por debajo para evitar slippage
            else:  # Orden de mercado para BTC/SOL
                order = binance.create_market_buy_order(symbol, trade_amount)
            # Verificar slippage para órdenes limitadas
            if assets[symbol]['strategy'] == 'scalping':
                time.sleep(5)  # Esperar 5 segundos para verificar ejecución
                order_status = binance.fetch_order(order['id'], symbol)
                executed_price = order_status['average'] if order_status['average'] else current_price
                slippage = abs((executed_price - (current_price * 0.995)) / (current_price * 0.995))
                if slippage > 0.005:  # Slippage > 0.5%
                    logging.warning(f"⚠️ Slippage alto en {symbol}: {slippage*100:.2f}%")
                    enviar_alerta_telegram(f'⚠️ Slippage alto en {symbol}: {slippage*100:.2f}%')
            # Verificar estado de la orden después de 30 segundos (opcional, comentar si no es necesario)
            time.sleep(30)  # Usar await para asyncio
            order_status = binance.fetch_order(order['id'], symbol)
            if order_status['status'] != 'closed':
                binance.cancel_order(order['id'], symbol)
                logging.warning(f"Orden limitada no ejecutada para {symbol}, cancelada.")
                enviar_alerta_telegram(f'⚠️ Orden limitada no ejecutada para {symbol}, cancelada.')
        except ccxt.BaseError as e:
            logging.error(f"Error en la orden de compra en {symbol}: {e}")
            enviar_alerta_telegram(f'⚠️ Error en la orden de compra en {symbol}: {e}')
            return
        profit_potential = trade_amount * (tp_price - current_price) * (1 - 2 * COMMISSION_RATE)  # Ajuste por comisiones de compra/venta
        capital_por_moneda[symbol] += profit_potential
        capital_actual += profit_potential
        profits_semanales += profit_potential
        enviar_alerta_telegram(f'🚀 Compra en {symbol} a {current_price}, cantidad: {trade_amount}, SL: {sl_price:.6f}, TP: {tp_price:.6f}')
    
    # Estrategia de venta (optimizada para maximizar ganancias, sin depender de Ondas de Elliott)
    if (df['smc_zone'].iloc[-1] == 'Potential_Distribution') \
       and df['rsi'].iloc[-1] > 55 and df['close'].iloc[-1] < df['ema_20'].iloc[-1] * 1.02 \
       and df['volume'].iloc[-1] > volume_threshold \
       and (df['stoch_k'].iloc[-1] > 80 or df['stoch_d'].iloc[-1] > 80):
        # Stop Loss dinámico para scalping (FLOKI/DOGE), fijo para swing (BTC/SOL)
        dynamic_sl = min(0.015, 1.5 * df['atr'].iloc[-1] / current_price) if assets[symbol]['strategy'] == 'scalping' else params['sl']
        sl_price = current_price + (current_price * dynamic_sl)
        tp_price = current_price * (1 - params['tp'])
        try:
            if assets[symbol]['strategy'] == 'scalping':  # Orden limitada para FLOKI/DOGE
                order = binance.create_limit_sell_order(symbol, trade_amount, current_price * 1.005)  # 0.5% por encima para evitar slippage
            else:  # Orden de mercado para BTC/SOL
                order = binance.create_market_sell_order(symbol, trade_amount)
            '''
            # Verificar slippage para órdenes limitadas
            if assets[symbol]['strategy'] == 'scalping':
                time.sleep(5)  # Esperar 5 segundos para verificar ejecución
                order_status = binance.fetch_order(order['id'], symbol)
                executed_price = order_status['average'] if order_status['average'] else current_price
                slippage = abs((executed_price - (current_price * 1.005)) / (current_price * 1.005))
                if slippage > 0.005:  # Slippage > 0.5%
                    logging.warning(f"⚠️ Slippage alto en {symbol}: {slippage*100:.2f}%")
                    enviar_alerta_telegram(f'⚠️ Slippage alto en {symbol}: {slippage*100:.2f}%')
            
            # Verificar estado de la orden después de 30 segundos (opcional, comentar si no es necesario)
            time.sleep(30)
            order_status = binance.fetch_order(order['id'], symbol)
            if order_status['status'] != 'closed':
                binance.cancel_order(order['id'], symbol)
                logging.warning(f"Orden limitada no ejecutada para {symbol}, cancelada.")
                enviar_alerta_telegram(f'⚠️ Orden limitada no ejecutada para {symbol}, cancelada.')
            '''
        except ccxt.BaseError as e:
            logging.error(f"Error en la orden de venta en {symbol}: {e}")
            enviar_alerta_telegram(f'⚠️ Error en la orden de venta en {symbol}: {e}')
            return
        profit_potential = trade_amount * (current_price - tp_price) * (1 - 2 * COMMISSION_RATE)  # Ajuste por comisiones de compra/venta
        capital_por_moneda[symbol] += profit_potential
        capital_actual += profit_potential
        profits_semanales += profit_potential
        enviar_alerta_telegram(f'✅ Venta en {symbol} a {current_price}, cantidad: {trade_amount}, SL: {sl_price:.6f}, TP: {tp_price:.6f}')
    
    redistribuir()

# Iniciar bot con intervalo optimizado por activo
async def iniciar_bot():
    while True:
        for symbol, params in assets.items():
            await ejecutar_trade_async(symbol, params)
            atr = get_market_data(symbol)['atr'].iloc[-1] if get_market_data(symbol) is not None else 0.01
            volatility_factor = min(1.5, max(0.5, atr / get_market_data(symbol)['atr'].mean()))  # Factor de volatilidad (0.5-1.5)
            intervalo = int(300 * volatility_factor) if params['strategy'] == 'scalping' else int(600 * volatility_factor)
            await asyncio.sleep(intervalo)

async def ejecutar_trade_async(symbol, params):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: ejecutar_trade(symbol, params))

if _name_ == '_main_':
    try:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        enviar_alerta_telegram('🤖 Bot de trading optimizado iniciado para maximizar ganancias y minimizar pérdidas (versión final ajustada para FLOKI, DOGE, BTC, SOL, con Ondas de Elliott como indicador complementario).')
        asyncio.run(iniciar_bot())
    except Exception as e:
        logging.error(f'Error en el bot: {e}')
        enviar_alerta_telegram(f'⚠️ Error en el bot: {e}')
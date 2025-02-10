import ccxt
import time
import requests
import pandas as pd
import numpy as np
import os
from dotenv import load_dotenv
from loguru import logger

from message import enviar_alerta_telegram

load_dotenv() 

# Configuración de la API del exchange
api_key = os.getenv('API_KEY')
api_secret = os.getenv('API_SECRET')
exchange_id = 'binance'

exchange = getattr(ccxt, exchange_id)({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
})

# Configuración de Telegram
telegram_bot_token = os.getenv('TELEGRAM_BOT_ID')
telegram_chat_id =  os.getenv('TELEGRAM_CHAT_ID')


# Pares de trading y configuración de indicadores
symbol = 'FLOKI/USDT'
interval = '15m'
porcentaje_anticipacion = 0.02  # 2% de anticipación para alertas
meta_rentabilidad_semanal = 500  # Meta de ganancia semanal en USDT
porcentaje_proteccion = 0.75  # Mantener al menos 75% de las ganancias semanales
stop_loss_fibonacci = 0.786  # Nivel de Stop-Loss dinámico en retroceso de Fibonacci


def calcular_niveles_fibonacci(data):
    max_price = data['high'].max()
    min_price = data['low'].min()
    diff = max_price - min_price
    
    niveles_fibonacci = {
        '38.2%': max_price - diff * 0.382,
        '50.0%': max_price - diff * 0.5,
        '61.8%': max_price - diff * 0.618,
        '78.6%': max_price - diff * stop_loss_fibonacci,  # Stop-Loss dinámico
        '1.272': max_price + diff * 1.272,
        '1.618': max_price + diff * 1.618
    }
    logger.info("Niveles Fibonacci calculados")
    return niveles_fibonacci

# Función para calcular EMA
def calcular_ema(data, periodo=50):
    return data['close'].ewm(span=periodo, adjust=False).mean()

# Función para calcular ATR (para Stop-Loss dinámico)
def calcular_atr(data, periodo=14):
    high_low = data['high'] - data['low']
    high_close = abs(data['high'] - data['close'].shift())
    low_close = abs(data['low'] - data['close'].shift())
    atr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return atr.rolling(window=periodo).mean()

# Obtener saldo
def obtener_saldo():
    balance = exchange.fetch_balance()
    usdt_disponible = balance['total']['USDT']
    floki_disponible = balance['total']['FLOKI']
    logger.info(f"Saldo obtenido FLOKI: {floki_disponible}, USDT: {usdt_disponible}",)
    return usdt_disponible, floki_disponible

# Calcular rentabilidad acumulada semanal
def calcular_ganancia_semanal():
    historial = exchange.fetch_my_trades(symbol, limit=100)
    ganancia = sum(trade['cost'] for trade in historial if trade['side'] == 'sell') - sum(trade['cost'] for trade in historial if trade['side'] == 'buy')
    logger.info("Ganancia semanal calculada")
    return ganancia

# Ejecutar orden de compra o venta
def colocar_orden(tipo, precio):
    try:
        usdt_disponible, floki_disponible = obtener_saldo()
        if tipo == 'buy':
            cantidad = usdt_disponible / precio
        else:
            cantidad = floki_disponible * 0.5  # Take-Profit parcial: vender solo el 50%

        order = exchange.create_order(symbol, 'limit', tipo, cantidad, precio)
        mensaje = f"✅ ORDEN {tipo.upper()} EJECUTADA: {cantidad:.2f} FLOKI a {precio} USDT"
        logger.info(mensaje)
        enviar_alerta_telegram(mensaje)
        
    except Exception as e:
        mensaje = f"❌ ERROR en orden {tipo.upper()}: {e}"
        logger.error(mensaje)
        enviar_alerta_telegram(mensaje)
        

# Monitorear mercado y ejecutar órdenes
def monitorear_mercado():
    while True:
        try:
            logger.info("Inicio iterarion")
            ganancia_actual = calcular_ganancia_semanal()
            proteccion_minima = meta_rentabilidad_semanal * porcentaje_proteccion
            logger.info(f'Ganancia actual: {ganancia_actual}')
            if ganancia_actual >= meta_rentabilidad_semanal:
                mensaje = f"🎯 Meta de ganancia semanal alcanzada: {ganancia_actual:.2f} USDT. Siguiendo operaciones pero protegiendo al menos {proteccion_minima:.2f} USDT."
                enviar_alerta_telegram(mensaje)
                logger.error(mensaje)
                
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=interval, limit=100)
            data = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            data['ema50'] = calcular_ema(data, 50)
            data['ema200'] = calcular_ema(data, 200)
            data['atr'] = calcular_atr(data)
            niveles_fibonacci = calcular_niveles_fibonacci(data)

            ultimo_precio = data['close'].iloc[-1]
            tendencia_alcista = ultimo_precio > data['ema50'].iloc[-1] and data['ema50'].iloc[-1] > data['ema200'].iloc[-1]

            compra_realizada = False
            venta_realizada = False
            logger.info(f'Ultimo precio: {ultimo_precio}')

            if ultimo_precio <= niveles_fibonacci['78.6%']:  # Stop-Loss dinámico con ATR
                colocar_orden('sell', ultimo_precio)
                venta_realizada = True

            if tendencia_alcista and (ultimo_precio <= niveles_fibonacci['38.2%'] or 
                ultimo_precio <= niveles_fibonacci['50.0%'] or 
                ultimo_precio <= niveles_fibonacci['61.8%']):
                colocar_orden('buy', ultimo_precio)
                compra_realizada = True

            if (ultimo_precio >= niveles_fibonacci['1.272'] and not venta_realizada):
                colocar_orden('sell', ultimo_precio)
                venta_realizada = True

            if (ultimo_precio >= niveles_fibonacci['1.618'] and not venta_realizada):
                colocar_orden('sell', ultimo_precio)
                venta_realizada = True
            logger.info("Esperar 1 minuto")
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    monitorear_mercado()
import ccxt
import asyncio
from loguru import logger
import os
import threading
import time

import concurrent.futures

import ta
import pandas as pd
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
    'options': {'defaultType': 'spot'},
    'rateLimit': 1200  # Optimización para evitar sobrecarga de llamadas
})

# Configuración de activos y estrategias
assets = {
    'FLOKI/USDT': {'tp': 0.02, 'sl': 0.01},  # Scalping
    'DOGE/USDT': {'tp': 0.02, 'sl': 0.01},  # Scalping
    'BTC/USDT': {'tp': 0.04, 'sl': 0.02},   # Swing
    'DOT/USDT': {'tp': 0.03, 'sl': 0.015}   # Swing
}

# Umbrales de capital y retiros
UMBRAL_CAPITAL = 5000  # Confirma que este valor refleja correctamente la meta antes de habilitar retiros
RETIRO_SEMANAL = 700  # Ajustar si es necesario para alinearse con la estrategia planificada
PROFIT_SEMANAL_MIENTRAS_SUBE = 450  # Profit semanal hasta llegar a $5000
PROFIT_SEMANAL_OBJETIVO = (850, 1000)  # Rango de profit entre $850 y $1000 después de los $5000

# Función para detectar Ondas de Elliott automáticamente
def detectar_onda_elliott(df):
    df['wave'] = [''] * len(df)  # Inicializar columna de ondas con valores vacíos
    max_high = df['high'].max()
    min_low = df['low'].min()
    
    for i in range(2, len(df) - 2):
        if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[i+1]:
            if df['high'].iloc[i] >= max_high * 0.9:
                df.at[i, 'wave'] = 'Elliott_Wave_3' if 'Elliott_Wave_3' not in df['wave'].values else 'Elliott_Wave_5'
        elif df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[i+1]:
            if df['low'].iloc[i] <= min_low * 1.1:
                df.at[i, 'wave'] = 'Elliott_Wave_A' if 'Elliott_Wave_A' not in df['wave'].values else 'Elliott_Wave_C'
    
    return df

# Función optimizada para obtener datos del mercado
def get_market_data(symbol):
    try:
        ohlcv = binance.fetch_ohlcv(symbol, timeframe='1h', limit=50)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        df['macd'] = ta.trend.MACD(df['close']).macd()
        df['ema_7'] = ta.trend.EMAIndicator(df['close'], window=7).ema_indicator()
        df['ema_25'] = ta.trend.EMAIndicator(df['close'], window=25).ema_indicator()
        df['ema_200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
        df['bollinger_high'] = ta.volatility.BollingerBands(df['close']).bollinger_hband()
        df['bollinger_low'] = ta.volatility.BollingerBands(df['close']).bollinger_lband()
        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx()
        df['plus_di'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx_pos()
        df['minus_di'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx_neg()
        df['volume_ma'] = df['volume'].rolling(window=10).mean()
        
        df = detectar_onda_elliott(df)
        
        return df
    except Exception as e:
        logger.error(f'Error al obtener datos de {symbol}: {e}')
        return None

# Función para ejecutar estrategias de compra y venta
def ejecutar_trade(symbol, params):
    logger.info(params)
    df = get_market_data(symbol)
    if df is None:
        return
    price = df['close'].iloc[-1]
    rsi = df['rsi'].iloc[-1]
    macd = df['macd'].iloc[-1]
    ema_7 = df['ema_7'].iloc[-1]
    ema_25 = df['ema_25'].iloc[-1]
    adx = df['adx'].iloc[-1]
    volume = df['volume'].iloc[-1]
    volume_ma = df['volume_ma'].iloc[-1]
    
    trade_amount = params['capital'] / price
    
    # Estrategia de compra
    if ('Elliott_Wave_2' in df['wave'].values or 'Elliott_Wave_4' in df['wave'].values or 'Elliott_Wave_A' in df['wave'].values or 'Elliott_Wave_C' in df['wave'].values) and rsi < 40 and macd > 0 and ema_7 > ema_25 and adx > 25 and volume > volume_ma:
        #if str.upper(os.getenv('BUY')) == "YES":
            #order = binance.create_market_buy_order(symbol, trade_amount)
        enviar_alerta_telegram(f'🚀 Compra en {symbol} a {price}')
    
    # Estrategia de venta
    if ('Elliott_Wave_B' in df['wave'].values or 'Elliott_Wave_3' in df['wave'].values or 'Elliott_Wave_5' in df['wave'].values or rsi > 70 or macd < 0 or ema_7 < ema_25):
        #if str.upper(os.getenv('SELL')) == "YES":
            #binance.create_market_sell_order(symbol, trade_amount)
        enviar_alerta_telegram(f'✅ Venta en {symbol} a {price}')

# Función para obtener balance y distribuir capital dinámicamente
def get_dynamic_capital():
    try:
        balance = binance.fetch_balance()
        usdt_balance = balance['total'].get('USDT', 0)
        logger.info(usdt_balance)
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
        logger.info("Se obtuvo el capital")
        return assets
    except Exception as e:
        logger.error(f'Error al obtener balance: {e}')
        enviar_alerta_telegram(f'⚠️ Error al obtener balance: {e}')
        return {}

    
def start_trading():
    logger.info("Nuevo ciclo del bot")
    assets_con_capital = get_dynamic_capital()
    if not assets_con_capital:
        enviar_alerta_telegram('⚠️ No hay capital disponible para operar.')
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_symbol = {
            executor.submit(ejecutar_trade, symbol, params): symbol
            for symbol, params in assets_con_capital.items()
        }
        for future in concurrent.futures.as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                future.result()  # Catch any exceptions from the thread
            except Exception as e:
                print(f"Error in trade {symbol}: {e}")


if __name__ == '__main__':

    try:
        enviar_alerta_telegram('🤖 Bot de trading optimizado iniciado.')
        while True:
            start_trading()
            time.sleep(60)  # Intervalo de verificación
    except Exception as e:
        logger.error(f'Error en el bot: {e}')
        enviar_alerta_telegram(f'⚠️ Error en el bot: {e}')


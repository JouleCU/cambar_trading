import ccxt
from loguru import logger
import os
import threading
import time

import concurrent.futures

import ta
import pandas as pd
from dotenv import load_dotenv
from message import enviar_alerta_telegram
from trading_logic import *

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
def ejecutar_trade(asset: TradingAssets):
    #logger.info(params)
    df = get_market_data(asset.symbol)
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
    
    trade_amount = asset.capital / price
    if not asset.compra_anterior:
        unique_waves = [wave for wave in df['wave'].unique() if wave != '']
        logger.info(f"\n[{asset.symbol}] Precio: {price:.4f} | RSI: {rsi:.4f} | MACD: {macd:.4f} | EMA_7: {ema_7:.4f} | EMA_25: {ema_25:.4f} | ADX: {adx:.4f} | Volumen: {volume:.4f} | Volumen MA: {volume_ma:.4f}")
        logger.info(f"Unique waves: {unique_waves}")
        # Estrategia de compra
        if (( 'Elliott_Wave_2' in df['wave'].values or 
          'Elliott_Wave_4' in df['wave'].values or 
          'Elliott_Wave_A' in df['wave'].values or 
          'Elliott_Wave_C' in df['wave'].values ) and 
        rsi < 50 and macd > -0.05 and ema_7 >= ema_25 and adx > 20 and volume > volume_ma):
            #if str.upper(os.getenv('BUY')) == "YES":
                #order = binance.create_market_buy_order(symbol, trade_amount)
            asset.precio_compra = price
            asset.cantidad_compra = trade_amount
            logger.info(f'Compra en {asset.symbol} a {price}')
            enviar_alerta_telegram(f'🚀 Compra en {asset.symbol} a {price}')
        
    if asset.compra_anterior:

        # Estrategia de venta
        if ('Elliott_Wave_B' in df['wave'].values or 'Elliott_Wave_3' in df['wave'].values or 'Elliott_Wave_5' in df['wave'].values or rsi > 70 or macd < 0 or ema_7 < ema_25):
        
            logger.info("Intención de vender")
            if price > asset.precio_compra:
                #if str.upper(os.getenv('SELL')) == "YES":
                    #binance.create_market_sell_order(symbol, asset.cantidad_compra)
                asset.profit =  price*(asset.cantidad_compra) - asset.capital
                asset.compra_anterior = False
                logger.info(f'Venta realizada en {asset.symbol} a {price} | Profit: {asset.profit}')
                enviar_alerta_telegram(f'✅ Venta en {asset.symbol} a {price} | Ganancia: {asset.profit:.4f} USDT')

# Función para obtener balance y distribuir capital dinámicamente
def get_dynamic_capital(bot: Bot):
    try:
        if os.getenv('ENV') == 'DEV':
            #logger.info("Test mode")
            usdt_balance = 1000
            balance = binance.fetch_balance()
            floki_balance = balance['total'].get('FLOKI', 0)
            #logger.info(floki_balance)

        else:
            balance = binance.fetch_balance()
            usdt_balance = balance['total'].get('USDT', 0)
            floki_balance = balance['total'].get('FLOKI', 0)
            if usdt_balance >= UMBRAL_CAPITAL:
                withdraw_amount = min(RETIRO_SEMANAL, usdt_balance - UMBRAL_CAPITAL)
                enviar_alerta_telegram(f'🔄 Retirando {withdraw_amount} USDT. Resto será reutilizado como capital.')
                usdt_balance -= withdraw_amount
            
            if usdt_balance <= 0:
                return bot
        bot.capital_inversion = usdt_balance
        trading_assets = bot.assets
        num_activos = len(trading_assets)
        
        capital_por_activo = usdt_balance / num_activos
        for asset in trading_assets:
            asset.capital = capital_por_activo
        bot.assets=trading_assets
        logger.info("Se obtuvo el capital")
        return bot
    except Exception as e:
        logger.error(f'Error al obtener balance: {e}')
        enviar_alerta_telegram(f'⚠️ Error al obtener balance: {e}')
        return bot

    
def start_trading(bot: Bot):
    logger.info("Nuevo ciclo del bot")
    assets_con_capital = get_dynamic_capital(bot)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_symbol = {
             executor.submit(ejecutar_trade, asset): asset.symbol
            for asset in bot.assets if asset.capital > 0  # Only trade assets with capital
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
        assets = [
                TradingAssets("FLOKI/USDT", capital=0, precio_compra = 0, cantidad_compra=0, profit=0, compra_anterior=False), 
                TradingAssets("DOGE/USDT", capital=0, precio_compra = 0, cantidad_compra=0, profit=0, compra_anterior=False), 
                TradingAssets("BTC/USDT", capital=250, precio_compra = 97457.14, cantidad_compra=0, profit=0, compra_anterior=True), 
                TradingAssets("DOT/USDT", capital=250, precio_compra = 4.9, cantidad_compra=0, profit=0, compra_anterior=True), 
                  ]

        trading_bot = Bot(
            capital_inversion=500,
            umbral_inversion=1000,
            retiro=200,
            profit_actual=0,
            profit_objetivo= 1000,
            assets=assets,
        )
        #assets_con_capital = get_dynamic_capital(trading_bot)

        flag = 0
        if os.getenv('ENV') == 'DEV':
            logger.info("Tradeando en test con 1000 USDT")
            trading_bot.assets[2].update_trading_amount()
            trading_bot.assets[3].update_trading_amount()
        while True:
            if flag==10:
                logger.info("enviando actualización")
                enviar_alerta_telegram(str(trading_bot))
                flag = 0
            start_trading(trading_bot)
            flag+=1
            time.sleep(60)  # Intervalo de verificación
            
        
    except Exception as e:
        logger.error(f'Error en el bot: {e}')
        enviar_alerta_telegram(f'⚠️ Error en el bot: {e}')


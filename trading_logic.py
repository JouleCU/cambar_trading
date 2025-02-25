import os 
import ccxt
import ta
import numpy as np
from loguru import logger
import pandas as pd
from message import enviar_alerta_telegram
from scipy.signal import find_peaks
from dataclasses import dataclass
from loguru import logger
import time

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


@dataclass
class TradingAssets:
    symbol: str
    strategy: str
    tp: float
    sl: float
    capital: float
    precio_compra: float
    cantidad_compra: float # capital / precio_compra
    profit: float
    compra_anterior: bool
    
    
    def update_trading_amount(self):
        self.cantidad_compra = self.capital/self.precio_compra

    def __str__(self):
        return f"▶ Symbol: {self.symbol}, Capital actual para el asset: {self.capital} Precio Compra: {self.precio_compra}"

@dataclass
class Bot:
    capital_inversion: float
    umbral_inversion: float
    retiro: float
    profit_actual: float
    profit_objetivo: float
    assets: list[TradingAssets]

    def obtener_capital_total(self):
        capital_total=0
        for asset in self.assets:
            capital_total+=asset.capital
        return capital_total

    def __str__(self):
        assets_str = "\n".join(str(asset) for asset in self.assets)

        return (f"Bot Details:\n"
                f"Capital Inversion: {self.capital_inversion}\n"
                f"Umbral Inversion: {self.umbral_inversion}\n"
                f"Retiro: {self.retiro}\n"
                f"Profit Actual: {self.profit_actual}\n"
                f"Profit Objetivo: {self.profit_objetivo}\n"
                f"Assets:\n{assets_str}")


def comprar_asset(binance,asset: TradingAssets,  trade_amount, price,  tipo):
    
    #asset.precio_compra = price
    #asset.cantidad_compra = trade_amount
    if str.upper(os.getenv('ENV')) == "DEV":
        logger.info(f'Compra en {asset.symbol} a {price}')
        enviar_alerta_telegram(f'🚀 Compra en {asset.symbol} a {price}')
        return 
    
    if tipo == 'limit':
        order = binance.create_limit_buy_order(asset.symbol, trade_amount, price * 0.995)  # 0.5% por debajo para evitar slippage
        logger.info(f'Compra LIMIT en {asset.symbol} a {price}')
        enviar_alerta_telegram(f'🚀 Compra LIMIT en {asset.symbol} a {price}')
        return order
    
    order = binance.create_market_buy_order(asset.symbol, trade_amount)
    logger.info(f'Compra en {asset.symbol} a {price}')
    enviar_alerta_telegram(f'🚀 Compra en {asset.symbol} a {price}')
    return order

def vender_asset(binance, symbol, price, asset: TradingAssets):
    if str.upper(os.getenv('SELL')) == "YES":
        binance.create_market_sell_order(symbol, asset.cantidad_compra)
    asset.profit =  price*(asset.cantidad_compra) - asset.capital
    asset.compra_anterior = False
    logger.info(f'Venta realizada en {asset.symbol} a {price} | Profit: {asset.profit}')
    enviar_alerta_telegram(f'✅ Venta en {asset.symbol} a {price} | Ganancia: {asset.profit:.4f} USDT')

def get_market_data(binance, asset: TradingAssets):
    try:
        strategy = asset.strategy
        timeframe = '15m' if strategy == 'scalping' else '1h'
        ohlcv = binance.fetch_ohlcv(asset.symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = verificar_integridad(df, asset.symbol)
        
        # Añadir indicadores TA-Lib esenciales
        df['rsi'] = ta.momentum.RSI(df['close'], window=14)
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14)
        df['adx'] = ta.trend.ADX(df['high'], df['low'], df['close'], window=14)  # Filtro de tendencia
        df['ma_50'] = ta.trend.SMA(df['close'], window=50)  # Media móvil para soportes/resistencias
        df['ema_20'] = ta.trend.EMA(df['close'], window=20)  # EMA para confirmación de tendencia
        df['stoch_k'], df['stoch_d'] = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3)
        
        # Calcular niveles de Fibonacci dinámicos
        df['fib_382'] = df['low'].rolling(50).min() + (df['high'].rolling(50).max() - df['low'].rolling(50).min()) * 0.382
        df['fib_618'] = df['low'].rolling(50).min() + (df['high'].rolling(50).max() - df['low'].rolling(50).min()) * 0.618
        
        # Filtro de liquidez mínima para FLOKI/DOGE (ajustado dinámicamente)
        if asset.symbol in ['FLOKI/USDT', 'DOGE/USDT']:
            atr = df['atr'].iloc[-1]
            liquidity_threshold = 800000 * (1 + 0.1 * (atr / df['atr'].mean())) if asset.symbol == 'FLOKI/USDT' else 2000000 * (1 + 0.1 * (atr / df['atr'].mean()))  # Ajuste dinámico por volatilidad
            if df['volume'].iloc[-1] * df['close'].iloc[-1] < liquidity_threshold:
                df['smc_zone'] = 'Neutral'
        
        # Detectar patrones avanzados con Ondas de Elliott y proyecciones
        df = detectar_onda_elliott(df)
        df = proyectar_movimientos_elliott(df)
        df = detectar_smc(df)
        
        # Loguear proyecciones para análisis (opcional, enviar a Telegram si es necesario)
        if not df['projection_up'].isna().all() or not df['projection_down'].isna().all():
            logger.info(f"Proyecciones para {asset.symbol}: Alcista hasta {df['projection_up'].iloc[-1]:.2f}, Bajista hasta {df['projection_down'].iloc[-1]:.2f}")
            enviar_alerta_telegram(f'📈 Proyecciones para {asset.symbol}: Alcista hasta {df['projection_up'].iloc[-1]:.2f}, Bajista hasta {df['projection_down'].iloc[-1]:.2f}')
        
        return df
    except ccxt.NetworkError as e:
        logger.error(f'Error de red al obtener datos de {asset.symbol}: {e}')
        enviar_alerta_telegram(f'⚠️ Error de red en {asset.symbol}: {e}')
        return None
    except ccxt.ExchangeError as e:
        logger.error(f'Error de exchange al obtener datos de {asset.symbol}: {e}')
        enviar_alerta_telegram(f'⚠️ Error de exchange en {asset.symbol}: {e}')
        return None
    except Exception as e:
        logger.error(f'Error inesperado al obtener datos de {asset.symbol}: {e}')
        enviar_alerta_telegram(f'⚠️ Error inesperado en {asset.symbol}: {e}')
        return None
    

# Función para detectar zonas de Smart Money Concept (manteniendo flexibilidad)
def detectar_smc(df):
    df['smc_zone'] = 'Neutral'
    volume_mean = df['volume'].rolling(window=20).mean()
    high_50 = df['high'].rolling(window=50).max()
    low_50 = df['low'].rolling(window=50).min()
    
    for i in range(2, len(df) - 2):
        if df['close'].iloc[i] < df['fib_382'].iloc[i] * 1.02 and df['volume'].iloc[i] > volume_mean.iloc[i] * 1.15:
            df.at[i, 'smc_zone'] = 'Potential_Accumulation'
        elif df['close'].iloc[i] > df['fib_618'].iloc[i] * 0.98 and df['volume'].iloc[i] > volume_mean.iloc[i] * 1.15:
            df.at[i, 'smc_zone'] = 'Potential_Distribution'
        elif df['close'].iloc[i] > low_50.iloc[i] * 1.02 and df['close'].iloc[i] < high_50.iloc[i] * 0.98:
            df.at[i, 'smc_zone'] = 'Fair_Value_Gap'
    
    return df

# Función para detectar Ondas de Elliott (como indicador complementario)
def detectar_onda_elliott(df, strategy):
    df['wave'] = ['None'] * len(df)
    prominence = 0.0001 if strategy == 'scalping' else 0.01  # Ajuste por volatilidad
    high_peaks, _ = find_peaks(df['high'], distance=3, prominence=prominence * (df['high'].max() - df['high'].min()))
    low_valleys, _ = find_peaks(-df['low'], distance=3, prominence=prominence * (df['low'].max() - df['low'].min()))
    
    for i in high_peaks:
        if i > 1 and i < len(df) - 1:
            prev_high = df['high'].iloc[max(0, i-2):i+1].max()
            next_high = df['high'].iloc[i+1:min(len(df), i+3)].max()
            if df['high'].iloc[i] > prev_high * 0.95 and df['high'].iloc[i] > next_high * 0.95:
                df.at[i, 'wave'] = 'Potential_Uptrend'
    
    for i in low_valleys:
        if i > 1 and i < len(df) - 1:
            prev_low = df['low'].iloc[max(0, i-2):i+1].min()
            next_low = df['low'].iloc[i+1:min(len(df), i+3)].min()
            if df['low'].iloc[i] < prev_low * 1.05 and df['low'].iloc[i] < next_low * 1.05:
                df.at[i, 'wave'] = 'Potential_Downtrend'
    
    return df

# Función para proyectar movimientos usando Ondas de Elliott y Fibonacci
def proyectar_movimientos_elliott(df):
    df['projection_up'] = np.nan
    df['projection_down'] = np.nan
    
    waves = df['wave'].values
    close = df['close'].values
    fib_382 = df['fib_382'].values
    fib_618 = df['fib_618'].values
    
    for i in range(1, len(df)):
        if waves[i] == 'Potential_Uptrend' and waves[i-1] == 'Potential_Downtrend':
            # Proyectar alza hasta el 161.8% de la onda anterior (impulso típico)
            wave_length = close[i] - close[np.where(waves[:i] == 'Potential_Downtrend')[0][-1]] if 'Potential_Downtrend' in waves[:i] else 0
            if wave_length > 0:
                projection_up = close[i] + (wave_length * 1.618)
                df.at[i, 'projection_up'] = min(projection_up, fib_618[i])  # Limitar por Fibonacci 61.8%
        elif waves[i] == 'Potential_Downtrend' and waves[i-1] == 'Potential_Uptrend':
            # Proyectar baja hasta el 61.8% o 100% de la onda anterior (corrección típica)
            wave_length = close[np.where(waves[:i] == 'Potential_Uptrend')[0][-1]] - close[i] if 'Potential_Uptrend' in waves[:i] else 0
            if wave_length > 0:
                projection_down = close[i] - (wave_length * 0.618)
                df.at[i, 'projection_down'] = max(projection_down, fib_382[i])  # Limitar por Fibonacci 38.2%
    
    return df

# Optimización: Función para verificar integridad de datos con alerta detallada
def verificar_integridad(df, symbol):
    if df.isnull().sum().sum() > 0:
        null_count = df.isnull().sum().sum()
        logger.warning(f"⚠️ Datos nulos detectados en {symbol}: {null_count} valores nulos. Revisando integridad...")
        df = df.fillna(method='ffill')  # Forward fill para manejar valores nulos
    return df

def redistribuir(bot: Bot):
    # Redistribuir capital proporcionalmente tras cada operación, considerando rentabilidad neta
    total_capital = bot.obtener_capital_total()
    for asset in bot.assets:
        net_profit = asset.capital - (CAPITAL_INICIAL / len(bot.assets) if s not in profits_semanales else 0)
        asset.capital  = (asset.capital  + net_profit * 0.1) / total_capital * capital_actual  # Reinversión del 10% de la rentabilidad
    
    # Gestión de capital y retiros (semanal)
    if capital_actual >= UMBRAL_CAPITAL and (pd.Timestamp.now() - ultimo_retiro).days >= 7:
        profit_semanal = min(max(profits_semanales, PROFIT_SEMANAL_OBJETIVO[0]), PROFIT_SEMANAL_OBJETIVO[1])
        if capital_actual > UMBRAL_CAPITAL + RETIRO_SEMANAL:
            capital_actual -= RETIRO_SEMANAL
            for asset in bot.assets:
                net_profit = asset.capital - (CAPITAL_INICIAL / len(bot.assets))
                asset.capital = (asset.capital + net_profit * 0.1) / sum(capital_por_moneda.values()) * capital_actual
            ultimo_retiro = pd.Timestamp.now()
            profits_semanales = 0
            enviar_alerta_telegram(f'💰 Retiro semanal de {RETIRO_SEMANAL} USD realizado. Capital actual: {capital_actual}')

def estrategia_compra(binance, asset: TradingAssets, df, volume_threshold, current_price, trade_amount):
    # Estrategia de compra (optimizada para maximizar ganancias, sin depender de Ondas de Elliott)
    if (df['smc_zone'].iloc[-1] in ['Potential_Accumulation', 'Fair_Value_Gap']) \
       and df['rsi'].iloc[-1] < 55 and df['close'].iloc[-1] > df['ema_20'].iloc[-1] * 0.98 \
       and df['volume'].iloc[-1] > volume_threshold \
       and (df['stoch_k'].iloc[-1] < 20 or df['stoch_d'].iloc[-1] < 20):
        
        # Stop Loss dinámico para scalping (FLOKI/DOGE), fijo para swing (BTC/SOL)
        dynamic_sl = min(0.015, 1.5 * df['atr'].iloc[-1] / current_price) if asset.strategy == 'scalping' else asset.sl
        sl_price = current_price - (current_price * dynamic_sl)
        tp_price = current_price * (1 + asset.tp)
        try:
            if asset.strategy == 'scalping':  # Orden limitada para FLOKI/DOGE
                order = binance.create_limit_buy_order(asset.symbol, asset.cantidad_compra, current_price * 0.995)  # 0.5% por debajo para evitar slippage
                comprar_asset(binance,asset, current_price,trade_amount)
            else:  # Orden de mercado para BTC/SOL
                order = binance.create_market_buy_order(asset.symbol, asset.cantidad_compra)
            
            '''
            # Verificar slippage para órdenes limitadas
            if asset.strategy == 'scalping':
                time.sleep(5)  # Esperar 5 segundos para verificar ejecución
                order_status = binance.fetch_order(order['id'], asset.symbol)
                executed_price = order_status['average'] if order_status['average'] else current_price
                slippage = abs((executed_price - (current_price * 0.995)) / (current_price * 0.995))
                if slippage > 0.005:  # Slippage > 0.5%
                    logger.warning(f"⚠️ Slippage alto en {asset.symbol}: {slippage*100:.2f}%")
                    enviar_alerta_telegram(f'⚠️ Slippage alto en {asset.symbol}: {slippage*100:.2f}%')
            
            # Verificar estado de la orden después de 30 segundos (opcional, comentar si no es necesario)
            time.sleep(30)  # Usar await para asyncio
            order_status = binance.fetch_order(order['id'], asset.symbol)
            if order_status['status'] != 'closed':
                binance.cancel_order(order['id'], asset.symbol)
                logger.warning(f"Orden limitada no ejecutada para {asset.symbol}, cancelada.")
                enviar_alerta_telegram(f'⚠️ Orden limitada no ejecutada para {asset.symbol}, cancelada.')
            '''
        except ccxt.BaseError as e:
            logger.error(f"Error en la orden de compra en {asset.symbol}: {e}")
            enviar_alerta_telegram(f'⚠️ Error en la orden de compra en {asset.symbol}: {e}')
            return
        profit_potential = asset.cantidad_compra * (tp_price - current_price) * (1 - 2 * COMMISSION_RATE)  # Ajuste por comisiones de compra/venta
        capital_por_moneda[asset.symbol] += profit_potential
        capital_actual += profit_potential
        profits_semanales += profit_potential
        enviar_alerta_telegram(f'🚀 Compra en {asset.symbol} a {current_price}, cantidad: {asset.cantidad_compra}, SL: {sl_price:.6f}, TP: {tp_price:.6f}')
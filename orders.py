import os

def orden_venta(binance, symbol, trade_amount):
    if str.upper(os.getenv('SELL')) == "YES":
        binance.create_market_sell_order(symbol, trade_amount)

def orden_compra(binance, symbol, trade_amount):
    if str.upper(os.getenv('BUY')) == "YES":
        order = binance.create_market_buy_order(symbol, trade_amount)



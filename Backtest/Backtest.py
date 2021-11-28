import pandas as pd
import json
import requests
import ta
import asyncio
from MoneyManager import MoneyManager


async def main():
    money_manager = MoneyManager('ready', 0, 0, 100)

    # get 5 min historical data
    url = 'https://api.binance.com/api/v3/klines'
    params = {'symbol': 'ETHUSDT', 'interval': '5m', 'limit': 1000}
    df5 = pd.DataFrame(json.loads(requests.get(url, params=params).text))
    df5 = df5.iloc[:, [0, 4]]
    df5.columns = ['Time', 'Price']
    df5.Price = df5.Price.astype(float)
    df5.Time = pd.to_datetime(df5.Time, unit='ms')
    df5.Time = df5.Time.dt.tz_localize('UTC').dt.tz_convert('Pacific/Auckland')

    n = len(df5)
    for i in range(50, n):
        data = df5.iloc[i-50:i, :]
        strategy(money_manager, data)
    else:
        print("Trades: " + str(money_manager.tradecount) + "    Wins: " + str(money_manager.wincount))


def strategy(money_manager, data):

    bb = ta.volatility.BollingerBands(close=data.Price, window=20, window_dev=2, fillna=False)
    h_band = bb.bollinger_hband().iloc[-1]
    l_band = bb.bollinger_lband().iloc[-1]
    price = data.iloc[-1].Price
    macd = ta.trend.MACD(close=data.Price, window_slow=26, window_fast=12, window_sign=9, fillna=False)

    if money_manager.state == 'ready':
        # shorting opportunity
        if price >= h_band:
            money_manager.state = 'shorting'

        # longing opportunity
        if price <= l_band:
            money_manager.state = 'longing'

    elif money_manager.state == 'shorting':
        # make sure price hasn't already gone to other side of BB
        if price <= l_band:
            money_manager.state = 'longing'

        elif macd.macd_diff().iloc[-2] > 0 > macd.macd_diff().iloc[-1]:
            # set stop loss at high bollinger band and profit at 1:1 ratio
            stop_loss = (h_band - price) / price
            # don't enter trade if profit not enough to cover trading fee 0.75%
            if stop_loss <= 0.0015:
                money_manager.state = 'ready'

            else:
                money_manager.bal_eth = money_manager.bal_usd / price * -1
                money_manager.bal_usd = money_manager.bal_usd * 2
                money_manager.entry_price = price
                money_manager.state = 'short'
                print("SHORT   " + str(data.iloc[-1].Time))
                print("Entry price: " + str(money_manager.entry_price) + "    Stop Loss: " + str(stop_loss))

    elif money_manager.state == 'longing':
        # make sure price hasn't already gone to other side of BB
        if price >= h_band:
            money_manager.state = 'shorting'

        elif macd.macd_diff().iloc[-2] < 0 < macd.macd_diff().iloc[-1]:
            # set stop loss at low bollinger band and profit at 1:1 ratio
            stop_loss = (price - l_band) / l_band
            # don't enter trade if profit not enough to cover trading fee 0.75%
            if stop_loss <= 0.00015:
                money_manager.state = 'ready'

            else:
                money_manager.bal_eth = money_manager.bal_usd / price
                money_manager.bal_usd = 0
                money_manager.entry_price = price
                money_manager.state = 'long'
                print("LONG   " + str(data.iloc[-1].Time))
                print("Entry price: " + str(money_manager.entry_price) + "    Stop Loss: " + str(stop_loss))

    elif money_manager.state == 'short':
        # set stop loss at high bollinger band and profit at 1:1 ratio
        stop_loss = (h_band - money_manager.entry_price) / money_manager.entry_price
        # limit stop loss to 0.8%
        if stop_loss > 0.008:
            stop_loss = 0.008

        if price >= money_manager.entry_price * (1 + stop_loss) or price <= money_manager.entry_price / (1 + stop_loss):
            money_manager.bal_usd = money_manager.bal_usd + (money_manager.bal_eth * price)
            money_manager.bal_eth = 0
            money_manager.state = 'ready'
            money_manager.tradecount += 1
            if price <= money_manager.entry_price / (1 + stop_loss):
                money_manager.wincount += 1
            print("CLOSED SHORT   " + str(price))
            print("ETH Bal: " + str(money_manager.bal_eth) + "    USD Bal: " + str(money_manager.bal_usd) + "     Exit price: " + str(price))

    elif money_manager.state == 'long':
        # set stop loss at low bollinger band and profit at 1:1 ratio
        stop_loss = (money_manager.entry_price - l_band) / l_band
        # limit stop loss to 0.8%
        if stop_loss > 0.008:
            stop_loss = 0.008

        if price <= money_manager.entry_price / (1 + stop_loss) or price >= money_manager.entry_price * (1 + stop_loss):
            money_manager.bal_usd = money_manager.bal_eth * price
            money_manager.bal_eth = 0
            money_manager.state = 'ready'
            money_manager.tradecount += 1
            if price >= money_manager.entry_price * (1 + stop_loss):
                money_manager.wincount += 1
            print("CLOSED LONG   " + str(price))
            print("ETH Bal: " + str(money_manager.bal_eth) + "    USD Bal: " + str(money_manager.bal_usd) + "     Exit price: " + str(price))

    else:
        print("Invalid State: " + money_manager.state)


def create_frame(msg):
    df = pd.DataFrame([msg])
    df = df.loc[:, ['E', 'p']]
    df.columns = ['Time', 'Price']
    df.Price = df.Price.astype(float)
    df.Time = pd.to_datetime(df.Time, unit='ms')
    return df


loop = asyncio.get_event_loop()
loop.run_until_complete(main())

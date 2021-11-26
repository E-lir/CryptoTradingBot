from binance import Client
import pandas as pd
import websockets
import json
import requests
import ta
import asyncio
from binance import AsyncClient, BinanceSocketManager
from MoneyManager import MoneyManager

with open('keys.txt') as f:
    api_key = f.readline().strip()
    secret_key = f.readline()
    client = Client(api_key, secret_key)

stream = websockets.connect('wss://stream.binance.com:9443/stream?streams=ethusdt@miniTicker')


async def main():
    short_frame = pd.DataFrame()
    money_manager = MoneyManager('ready', 0, 0, 100)

    # get 5 min historical data
    url = 'https://api.binance.com/api/v3/klines'
    params = {'symbol': 'ETHUSDT', 'interval': '5m', 'limit': 50}
    df5 = pd.DataFrame(json.loads(requests.get(url, params=params).text))
    df5 = df5.iloc[:, [0, 4]]
    df5.columns = ['Time', 'Price']
    df5.Time = pd.to_datetime(df5.Time, unit='ms')

    # get 15 min historical data
    params = {'symbol': 'ETHUSDT', 'interval': '15m', 'limit': 50}
    df15 = pd.DataFrame(json.loads(requests.get(url, params=params).text))
    df15 = df15.iloc[:, [0, 4]]
    df15.columns = ['Time', 'Price']
    df15.Time = pd.to_datetime(df15.Time, unit='ms')

    timer5m = df5.iloc[-1].Time
    timer15m = df15.iloc[-1].Time
    short_timer = df5.iloc[-1].Time

    cl = await AsyncClient.create()
    bm = BinanceSocketManager(cl)
    # start any sockets here, i.e a trade socket
    ts = bm.trade_socket('ETHUSDT')
    # then start receiving messages
    async with ts as tscm:
        while True:
            res = await tscm.recv()
            row = create_frame(res)
            # update 1 sec data frame
            if row.iloc[-1].Time >= short_timer + pd.Timedelta(seconds=1):
                short_frame = short_frame.append(row)
                short_timer = short_timer + pd.Timedelta(seconds=1)
                # short_frame is for short term price data, keep most recent 300 rows - 5 minutes worth
                if len(short_frame) > 300:
                    short_frame = short_frame.iloc[1:, :]

                strategy(money_manager, df5, df15, short_frame)

            # update 5 min data frame
            if row.iloc[-1].Time > timer5m + pd.Timedelta(minutes=5):
                df5 = df5.append(row)
                timer5m = timer5m + pd.Timedelta(minutes=5)
                # keep most recent 100 rows
                if len(df5) > 100:
                    df5 = df5.iloc[1:, :]

            # update 15 min data frame
            if row.iloc[-1].Time > timer15m + pd.Timedelta(minutes=15):
                df15 = df15.append(row)
                timer15m = timer15m + pd.Timedelta(minutes=15)
                # keep most recent 100 rows
                if len(df15) > 100:
                    df15 = df15.iloc[1:, :]

    await client.close_connection()


def strategy(money_manager, df5, df15, short_frame):

    bb = ta.volatility.BollingerBands(close=df15.Price, window=20, window_dev=2, fillna=False)
    h_band = bb.bollinger_hband().iloc[-1]
    l_band = bb.bollinger_lband().iloc[-1]
    sma1 = ta.trend.SMAIndicator(close=short_frame.Price, window=10, fillna=False)
    macd = ta.trend.MACD(close=df5.Price, window_slow=26, window_fast=12, window_sign=9, fillna=False)

    if money_manager.state == 'ready':
        # shorting opportunity
        if sma1.sma_indicator().iloc[-1] >= h_band:
            money_manager.state = 'shorting'
            print(money_manager.state)

        # longing opportunity
        if sma1.sma_indicator().iloc[-1] <= l_band:
            money_manager.state = 'longing'

    elif money_manager.state == 'shorting':
        # make sure price hasn't already gone to other side of BB
        if sma1.sma_indicator().iloc[-1] <= l_band:
            money_manager.state = 'longing'

        elif macd.macd_diff().iloc[-2] > 0 > macd.macd_diff().iloc[-1]:
            # set stop loss at high bollinger band and profit at 1:1 ratio
            stop_loss = (h_band - sma1.sma_indicator().iloc[-1]) / sma1.sma_indicator().iloc[-1]
            # don't enter trade if profit not enough to cover trading fee 0.75%
            if stop_loss <= 0.0015:
                money_manager.state = 'ready'

            else:
                money_manager.bal_eth = money_manager.bal_usd / short_frame.Price.iloc[-1] * -1
                money_manager.bal_usd = money_manager.bal_usd * 2
                money_manager.entry_price = short_frame.Price.iloc[-1]
                money_manager.state = 'short'
                print("SHORT   " + str(short_frame.Time.iloc[-1]))
                print("Entry price: " + str(money_manager.entry_price) + "    Stop Loss: " + str(stop_loss))

    elif money_manager.state == 'longing':
        # make sure price hasn't already gone to other side of BB
        if sma1.sma_indicator().iloc[-1] >= h_band:
            money_manager.state = 'shorting'

        elif macd.macd_diff().iloc[-2] < 0 < macd.macd_diff().iloc[-1]:
            # set stop loss at low bollinger band and profit at 1:1 ratio
            stop_loss = (sma1.sma_indicator().iloc[-1] - l_band) / l_band
            # don't enter trade if profit not enough to cover trading fee 0.75%
            if stop_loss <= 0.0015:
                money_manager.state = 'ready'

            else:
                money_manager.bal_eth = money_manager.bal_usd / short_frame.Price.iloc[-1]
                money_manager.bal_usd = 0
                money_manager.entry_price = short_frame.Price.iloc[-1]
                money_manager.state = 'long'
                print("LONG   " + str(short_frame.Time.iloc[-1]))
                print("Entry price: " + str(money_manager.entry_price) + "    Stop Loss: " + str(stop_loss))

    elif money_manager.state == 'short':
        # set stop loss at high bollinger band and profit at 1:1 ratio
        stop_loss = (h_band - money_manager.entry_price) / money_manager.entry_price
        # limit stop loss to 0.8%
        if stop_loss > 0.008:
            stop_loss = 0.008

        elif short_frame.Price.iloc[-1] >= money_manager.entry_price * (1 + stop_loss) or short_frame.Price.iloc[-1] <= money_manager.entry_price / (1 + stop_loss):
            money_manager.bal_usd = money_manager.bal_usd + (money_manager.bal_eth * short_frame.Price.iloc[-1])
            money_manager.bal_eth = 0
            money_manager.state = 'ready'
            print("CLOSED SHORT   " + str(short_frame.Time.iloc[-1]))
            print("ETH Bal: " + str(money_manager.bal_eth) + "    USD Bal: " + str(money_manager.bal_usd) + "     Exit price: " + str(short_frame.Price.iloc[-1]))

    elif money_manager.state == 'long':
        # set stop loss at low bollinger band and profit at 1:1 ratio
        stop_loss = (money_manager.entry_price - l_band) / l_band
        # limit stop loss to 0.8%
        if stop_loss > 0.008:
            stop_loss = 0.008

        elif short_frame.Price.iloc[-1] <= money_manager.entry_price / (1 + stop_loss) or short_frame.Price.iloc[-1] >= money_manager.entry_price * (1 + stop_loss):
            money_manager.bal_usd = money_manager.bal_eth * short_frame.Price.iloc[-1]
            money_manager.bal_eth = 0
            money_manager.state = 'ready'
            print("CLOSED LONG   " + str(short_frame.Time.iloc[-1]))
            print("ETH Bal: " + str(money_manager.bal_eth) + "    USD Bal: " + str(money_manager.bal_usd) + "     Exit price: " + str(short_frame.Price.iloc[-1]))

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

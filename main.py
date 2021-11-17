from binance import Client
import pandas as pd
import websockets
import json
import asyncio
import requests
import ta


with open('keys.txt') as f:
    api_key = f.readline().strip()
    secret_key = f.readline()
    client = Client(api_key, secret_key)

stream = websockets.connect('wss://stream.binance.com:9443/stream?streams=ethusdt@miniTicker')

state = 'ready'
entry_price = 0
bal_usd = 100
bal_eth = 0


async def main():
    df = pd.DataFrame()
    short_frame = pd.DataFrame()

    # get historical data
    url = 'https://api.binance.com/api/v3/klines'
    params = {'symbol': 'ETHUSDT', 'interval': '15m'}
    df = pd.DataFrame(json.loads(requests.get(url, params=params).text))
    df = df.iloc[:, [0, 4]]
    df.columns = ['Time', 'Price']
    df.Time = pd.to_datetime(df.Time, unit='ms')

    newest_time = df.iloc[-1].Time

    # get new data
    while True:
        async with stream as receiver:
            data = await receiver.recv()
            data = json.loads(data)['data']
            row = create_frame(data)
            short_frame = short_frame.append(row)

            # short_frame is for short term price data, 100 rows ~ 16.5 minutes worth
            if len(short_frame) > 100:
                short_frame = short_frame.iloc[1:, :]

            # append new row to df every 15 m
            if row.iloc[-1].Time > newest_time + pd.Timedelta(minutes=15):
                df = df.append(row)
                newest_time = newest_time + pd.Timedelta(minutes=15)

            # implement strategy
            strategy(df, short_frame)


def strategy(df, short_frame):
    global state
    global entry_price
    global bal_eth
    global bal_usd

    bb = ta.volatility.BollingerBands(close=df.Price, window=20, window_dev=2, fillna=False)
    h_band = bb.bollinger_hband().iloc[-1]
    l_band = bb.bollinger_lband().iloc[-1]
    m_band = bb.bollinger_mavg().iloc[-1]
    sma1 = ta.trend.SMAIndicator(close=short_frame.Price, window=6, fillna=False)
    sma5 = ta.trend.SMAIndicator(close=short_frame.Price, window=30, fillna=False)

    if state == 'ready':
        # shorting opportunity
        if sma1.sma_indicator().iloc[-1] >= h_band:
            state = 'shorting'

        # longing opportunity
        if sma1.sma_indicator().iloc[-1] <= l_band:
            state = 'longing'

    elif state == 'shorting':
        if sma5.sma_indicator().iloc[-7] > sma5.sma_indicator().iloc[-1]:
            bal_eth = bal_usd / short_frame.Price.iloc[-1] * -1
            bal_usd = bal_usd * 2
            entry_price = short_frame.Price.iloc[-1]
            state = 'short'
            print("SHORT")
            print("ETH Bal: " + str(bal_eth) + "    USD Bal: " + str(bal_usd) + "     Entry price: " + str(entry_price))

    elif state == 'longing':
        if sma5.sma_indicator().iloc[-7] < sma5.sma_indicator().iloc[-1]:
            bal_eth = bal_usd / short_frame.Price.iloc[-1]
            bal_usd = 0
            entry_price = short_frame.Price.iloc[-1]
            state = 'long'
            print("LONG")
            print("ETH Bal: " + str(bal_eth) + "    USD Bal: " + str(bal_usd) + "     Entry price: " + str(entry_price))

    elif state == 'short':
        # wait for price to hit middle bollinger band
        if short_frame.Price.iloc[-1] <= m_band or short_frame.Price.iloc[-1] > entry_price * 1.005:
            bal_usd = bal_usd + (bal_eth * short_frame.Price.iloc[-1])
            bal_eth = 0
            state = 'ready'
            print("CLOSED SHORT")
            print("ETH Bal: " + str(bal_eth) + "    USD Bal: " + str(bal_usd) + "     Exit price: " + str(short_frame.Price.iloc[-1]))

    elif state == 'long':
        # wait for price to hit middle bollinger band
        if short_frame.Price.iloc[-1] >= m_band or short_frame.Price.iloc[-1] < entry_price / 1.005:
            bal_usd = bal_eth * short_frame.Price.iloc[-1]
            bal_eth = 0
            state = 'ready'
            print("CLOSED LONG")
            print("ETH Bal: " + str(bal_eth) + "    USD Bal: " + str(bal_usd) + "     Exit price: " + str(short_frame.Price.iloc[-1]))

    else:
        print("Invalid State: " + state)


def create_frame(msg):
    df = pd.DataFrame([msg])
    df = df.loc[:, ['E', 'c']]
    df.columns = ['Time', 'Price']
    df.Price = df.Price.astype(float)
    df.Time = pd.to_datetime(df.Time, unit='ms')
    return df


loop = asyncio.get_event_loop()
loop.run_until_complete(main())

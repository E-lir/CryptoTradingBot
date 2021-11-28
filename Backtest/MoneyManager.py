class MoneyManager:
    def __init__(self, state, entry_price, bal_eth, bal_usd):
        self.state = state
        self.entry_price = entry_price
        self.bal_eth = bal_eth
        self.bal_usd = bal_usd
        self.tradecount = 0
        self.wincount = 0

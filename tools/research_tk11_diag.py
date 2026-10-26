# -*- coding: utf-8 -*-
"""ENA pencere-1 anomali teshisi: +580$ / 0 islem — gercek mi?"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
import config as cfg
from core.binance_client import candle_from_payload
from core.paper import PaperTrader

def fetch_rows(symbol, interval, total):
    url = f"{cfg.FAPI_REST}/fapi/v1/klines"
    out = []
    end = None
    while len(out) < total:
        take = min(1500, total - len(out))
        params = {"symbol": symbol, "interval": interval, "limit": take}
        if end is not None:
            params["endTime"] = end
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out = rows + out
        end = rows[0][0] - 1
    return out

mums = []
for row in fetch_rows("ENAUSDT", "1m", 2000):
    c = candle_from_payload(row)
    c.closed = True
    mums.append(c)
n = len(mums)
a = n - 4 * 500                     # pencere 1 (en eski 500)

p = PaperTrader("ENAUSDT")
p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
            wallet_fraction=0.8, mode="tk", risk_pct=0.03)
p.tk_window = 60
p.running = True
p.start_balance = 1000.0
p.balance = 1000.0
bt = p.backtest(mums[a:a + 500], "1m")
print("bt:", bt["profit"], "islem", bt["trades"],
      "K", bt["wins"], "Z", bt["losses"])
print("p.trades sayisi:", len(p.trades),
      "| toplam net:", round(sum(t.net_pnl for t in p.trades), 2))
print("acik pozisyon kaldi mi:", p.position is not None)
if p.position is not None:
    q = p.position
    print("  acik:", q.side, "giris", q.entry, "tk_tp", getattr(q, "tk_tp", None))
son = mums[a + 499]
print("ilk pencere ftp araligi:",
      mums[a].open, "->", son.close)

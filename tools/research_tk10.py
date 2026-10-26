# -*- coding: utf-8 -*-
"""TIK son eksen: tp genisligi, en iyi knob kombinasyonuna binmis."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests

import config as cfg


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


def to_mum(rows):
    from core.binance_client import candle_from_payload
    out = []
    for row in rows:
        c = candle_from_payload(row)
        c.closed = True
        out.append(c)
    return out


def calistir(candles, sym, tp, sl):
    from core.paper import PaperTrader
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.tk_window = 60
    p.tk_tp = tp
    p.tk_sl = sl
    p.tk_be = True
    p.tk_be_lock = 0.5
    p.tk_pause_bars = 3
    p.tk_leg_flip = False
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    return p.backtest(candles, "1m")


COINS = ["HBARUSDT", "DOGEUSDT", "ADAUSDT", "SOLUSDT"]
for sym in COINS:
    mums = to_mum(fetch_rows(sym, "1m", 3000))
    n = len(mums)
    print(f"\n#### {sym} (sl3 + be_lock.5 + pause3) ####")
    for tp in (0.0025, 0.003, 0.0035, 0.004):
        net = k = z = 0
        for wi in range(6):
            a = n - (6 - wi) * 500
            bt = calistir(mums[a:a + 500], sym, tp, 0.003)
            net += bt["profit"]; k += bt["wins"]; z += bt["losses"]
        wr = 100.0 * k / max(1, k + z)
        print(f"  tp={tp*1000:>3.1f}%: {net:>+9.2f}$ "
              f"islem {k+z:>3} WR {wr:>4.0f}%")

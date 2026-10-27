# -*- coding: utf-8 -*-
"""TK2 TP/SL ekonomisi: 1h yildiz karari, 8 coin x 5 pencere."""
from __future__ import annotations

import os
import sys

REP = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, REP)

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


from core.binance_client import candle_from_payload
from core.paper import PaperTrader

COINS = ["UNIUSDT", "HBARUSDT", "ADAUSDT", "ENAUSDT", "DOGEUSDT",
         "BTCUSDT", "SOLUSDT", "ETHUSDT"]

VERI = {}
for sym in COINS:
    try:
        mums = []
        for row in fetch_rows(sym, "1h", 2500):
            c = candle_from_payload(row)
            c.closed = True
            mums.append(c)
        VERI[sym] = mums
    except Exception as e:                       # noqa: BLE001
        print(sym, "veri yok:", e)

KOMBO = [(0.003, 0.004, "tp3/sl4 (mevcut)"),
         (0.004, 0.004, "tp4/sl4"),
         (0.005, 0.004, "tp5/sl4"),
         (0.004, 0.005, "tp4/sl5"),
         (0.006, 0.005, "tp6/sl5")]

satir = []
for tp, sl, ad in KOMBO:
    tpl = 0.0
    poz = 0
    n_is = 0
    for sym, mums in VERI.items():
        n = len(mums)
        for wi in range(5):
            a = n - (5 - wi) * 500
            p = PaperTrader(sym)
            p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                        wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
            p.tk_window = 60
            p.tk_tp = tp
            p.tk_sl = sl
            p.running = True
            p.start_balance = 1000.0
            p.balance = 1000.0
            bt = p.backtest(mums[a:a + 500], "1h")
            kapali = sum(t.net_pnl for t in p.trades)
            tpl += kapali
            n_is += len(p.trades)
            if kapali > 0:
                poz += 1
    satir.append((tpl, ad, poz, n_is))
    print(f"{ad:<18} {tpl:>+10.2f}$   poz-pencere {poz:>2}/40  islem {n_is}")

print()
for tpl, ad, poz, n_is in sorted(satir, reverse=True):
    print(f"{ad:<18} {tpl:>+10.2f}$  poz {poz}/40  islem {n_is}")

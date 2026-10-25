# -*- coding: utf-8 -*-
"""
NÖTR-HOLD ölçümü: NÖTR market çıkışı yerine BE-klip + stop koruması.
Taze 1h verisi, production default (corr AÇIK) + varyantlar.
Calistirma: python tools/research_nor_hold.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import config as cfg


def fetch_rows(symbol, interval, limit):
    url = f"{cfg.FAPI_REST}/fapi/v1/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": interval,
                                  "limit": limit}, timeout=20)
    r.raise_for_status()
    return r.json()


def to_mum(rows):
    from core.binance_client import candle_from_payload
    out = []
    for row in rows:
        c = candle_from_payload(row)
        c.closed = True
        out.append(c)
    return out


VARIANTLAR = [
    ("NÖTR-kapat", False, 0.0),          # yandaki mevcut hal (uretim)
    ("NÖTR-hold-s4", True, 0.004),
    ("NÖTR-hold-s8", True, 0.008),
    ("NÖTR-hold-s12", True, 0.012),
]


def calistir(candles, tf, ntr_hold, stop):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="ma_only", risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.ntr_hold = ntr_hold
    p.corr_stop_down = stop
    bt = p.backtest(candles, tf)
    return bt["profit"], bt["trades"], bt["wins"], len(p.trades)


def main():
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        for limit in (500, 1500):
            mums = to_mum(fetch_rows(sym, "1h", limit))
            satir = []
            for ad, hold, stp in VARIANTLAR:
                net, ntr, k, islem = calistir(mums, "1h", hold, stp)
                satir.append(f"{ad}: {net:>+8.1f}$/{ntr} islem")
                print(f"{sym} 1h x{limit:<5} {ad}: "
                      f"{net:>+9.2f}$ islem {ntr} (kazanc-anlik {islem})")
            print()


if __name__ == "__main__":
    main()

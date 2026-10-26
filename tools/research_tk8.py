# -*- coding: utf-8 -*-
"""
TIK duzeltici knob OLCUMU (canli HBAR cogor teshisine yanit):
  V0 BASE  (mevcut: pause0, BE0, flip0)
  V1 PAUSE3  V2 PAUSE6          (stop-sonrasi bar bekletme)
  V3 BE                          (basabas kogusu trig 0.5)
  V4 PAUSE3+BE     V5 P3+BE+FLIP     V6 P6+BE+FLIP
6 coin x 6 pencere (3000 mum 1m). Hedef: net + K/Z + cogor cadisi.
Calistirma: python tools/research_tk8.py
"""
from __future__ import annotations

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


VARYANTLAR = [
    ("BASE          ", 0, False, False),
    ("PAUSE3        ", 3, False, False),
    ("PAUSE6        ", 6, False, False),
    ("BE            ", 0, True, False),
    ("P3+BE         ", 3, True, False),
    ("P3+BE+FLIP    ", 3, True, True),
    ("P6+BE+FLIP    ", 6, True, True),
]


def calistir(candles, sym, pause, be, flip):
    from core.paper import PaperTrader
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.tk_window = 60
    p.tk_pause_bars = pause
    p.tk_be = be
    p.tk_leg_flip = flip
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    bt = p.backtest(candles, "1m")
    return bt, p


COINS = ["HBARUSDT", "ERAUSDT", "ENAUSDT", "SOLUSDT", "DOGEUSDT", "ADAUSDT"]

for sym in COINS:
    try:
        mums = to_mum(fetch_rows(sym, "1m", 3000))
    except Exception as e:                       # noqa: BLE001
        print(sym, "veri yok", e)
        continue
    n = len(mums)
    print(f"\n#### {sym} 1m x{n} ####")
    for ad, pause, be, flip in VARYANTLAR:
        net = n_is = k = z = 0
        sebler = {}
        for wi in range(6):
            a = n - (6 - wi) * 500
            bt, p = calistir(mums[a:a + 500], sym, pause, be, flip)
            net += bt["profit"]; n_is += bt["trades"]
            k += bt["wins"]; z += bt["losses"]
            for t in p.trades:
                key = t.exit_reason[:14]
                e, m = sebler.get(key, (0, 0.0))
                sebler[key] = (e + 1, m + t.net_pnl)
        print(f"  {ad}: {net:>+9.2f}$ islem {n_is:>3} K{k} Z{z} "
              f"WR{100.0*k/max(1,k+z):>4.0f}%")

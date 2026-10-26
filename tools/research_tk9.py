# -*- coding: utf-8 -*-
"""
TIK ekonomi duzeltme OLCUMU: asil sorun w/l ASIMETRISI (+12.7 vs -28).
Eksenler: SL k西游记 (0.002/0.0025/0.003), BE lock (0/0.3/0.5), pause 3.
6 pencere, 4 coin. Hedef: WR-threshold dunenellige ve WR balansi.
Calistirma: python tools/research_tk9.py
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


def calistir(candles, sym, tp, sl, be, be_lock, pause):
    from core.paper import PaperTrader
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.tk_window = 60
    p.tk_tp = tp
    p.tk_sl = sl
    p.tk_be = be
    p.tk_be_lock = be_lock
    p.tk_pause_bars = pause
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    return p.backtest(candles, "1m")


COINS = ["HBARUSDT", "SOLUSDT", "DOGEUSDT", "ADAUSDT"]

for sym in COINS:
    try:
        mums = to_mum(fetch_rows(sym, "1m", 3000))
    except Exception as e:                       # noqa: BLE001
        print(sym, "veri yok", e)
        continue
    n = len(mums)
    tp = 0.002
    print(f"\n#### {sym} 1m x{n} (tp={tp*1000:.0f}% 6 pencere) ####")
    satir = []
    for sl in (0.003, 0.0025, 0.002):
        for be_lock, be in ((0.0, False), (0.3, True), (0.5, True)):
            net = k = z = 0
            for wi in range(6):
                a = n - (6 - wi) * 500
                bt = calistir(mums[a:a + 500], sym, tp, sl,
                              be, be_lock, 3)
                net += bt["profit"]; k += bt["wins"]; z += bt["losses"]
            wr = 100.0 * k / max(1, k + z)
            # breakeven kazanc-orani: kayip/warszawa asimetrisi
            satir.append((net, sl, be_lock, wr, k + z, k, z))
    # birlesmek yerine kaba sira
    for net, sl, bl, wr, n_is, k, z in sorted(
            satir, key=lambda r: r[0], reverse=True):
        print(f"  sl={sl*1000:>4.1f}% be_lock={bl:<3}: {net:>+9.2f}$"
              f" islem {n_is:>3} K{k} Z{z} WR {wr:>4.0f}%")

# -*- coding: utf-8 -*-
"""
TICK filtre knob taramasi (2. pas): sinyal kalitesi eksenleri.
Umut veren hücreler (pas 1): SOL 1m tp=2-3% sl=5%, BTC 5m tp=3% sl=5%.
Eksenler: theta_max (derin geri cekilme ust siniri), vol_mult (talep
gucu), fill (altin cebe giris konumu), trend (SMA200 uyumu), window.

Calistirma: python tools/research_tk2.py
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


def calistir(candles, tf, tp, sl, **knobs):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.tk_on = True
    p.tk_tp = tp
    p.tk_sl = sl
    for k, v in knobs.items():
        setattr(p, {"win": "tk_window", "theta": "tk_theta_max",
                    "vol": "tk_vol_mult", "fill": "tk_fill",
                    "trend": "tk_trend"}[k], v)
    bt = p.backtest(candles, tf)
    return bt["profit"], bt["trades"], bt["wins"], bt["losses"]


HUCLER = [
    ("SOLUSDT 1m", "SOLUSDT", "1m", 0.002, 0.005),
    ("SOLUSDT 1m", "SOLUSDT", "1m", 0.003, 0.005),
    ("BTCUSDT 5m", "BTCUSDT", "5m", 0.003, 0.005),
    ("ETHUSDT 1m", "ETHUSDT", "1m", 0.003, 0.002),
]


def main():
    data = {}
    for name, sym, tf, tp, sl in HUCLER:
        data[(sym, tf)] = to_mum(fetch_rows(sym, tf, 1500))

    for ad, sym, tf, tp, sl in HUCLER:
        mums = data[(sym, tf)]
        print(f"\n#### {ad} tp={tp*1000:.0f}% sl={sl*1000:.0f}% "
              f"x{len(mums)} ####")
        for theta in (0.678, 0.85):
            for vol in (1.0, 1.5):
                for fill in (0.45, 0.55):
                    for tr in (False, True):
                        net, n, k, z = calistir(
                            mums, tf, tp, sl, theta=theta, vol=vol,
                            fill=fill, trend=tr, win=60)
                        fl = "trend" if tr else "    "
                        print(f"  th>={theta:<5} volx{vol} fill={fill} "
                              f"{fl}: {net:>+9.2f}$ ({n}) K{k} Z{z}")


if __name__ == "__main__":
    main()

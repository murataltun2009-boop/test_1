# -*- coding: utf-8 -*-
"""
TICK adaylarinin PENCERE-DAYANIKLILIGI: taze veri, 3 x 500 dik pencere.
Adaylar (pas 2 sonucu):
  SOL  1m tp2% sl5% fill0.55 th<=0.85 vol1.0   (+194$ tek pencerede)
  SOL  1m tp3% sl5% fill0.55 th<=0.85 vol1.0   (+210$ tek pencerede)
  BTC  5m tp3% sl5% fill0.55 th<=0.678 vol1.0  (+56$ tek pencerede)
  ETH  1m tp3% sl2% fill0.45 th<=0.678 vol1.0  (+50$ tek pencerede)
Calistirma: python tools/research_tk3.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datetime

import requests

import config as cfg

ADAYLAR = [
    ("SOL 1m", "SOLUSDT", "1m", 0.002, 0.005, 0.55, 0.85),
    ("SOL 1m", "SOLUSDT", "1m", 0.003, 0.005, 0.55, 0.85),
    ("BTC 5m", "BTCUSDT", "5m", 0.003, 0.005, 0.55, 0.678),
    ("BTC 5m", "BTCUSDT", "5m", 0.003, 0.005, 0.55, 0.85),
    ("ETH 1m", "ETHUSDT", "1m", 0.003, 0.002, 0.45, 0.678),
]


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


def calistir(candles, tf, tp, sl, theta):
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
    p.tk_theta_max = theta
    p.tk_fill = 0.55
    p.tk_vol_mult = 1.0
    p.tk_window = 60
    bt = p.backtest(candles, tf)
    return bt


def main():
    cache = {}
    for ad, sym, tf, tp, sl, fill, theta in ADAYLAR:
        if (sym, tf) not in cache:
            cache[(sym, tf)] = to_mum(fetch_rows(sym, tf, 1500))
        mums = cache[(sym, tf)]
        n = len(mums)
        print(f"\n#### {ad} tp={tp*1000:.0f}% sl={sl*1000:.0f}% "
              f"th<={theta} x{n} ####")
        topl = 0.0
        for wi in range(3):
            a = n - (3 - wi) * 500
            bt = calistir(mums[a:a + 500], tf, tp, sl, theta)
            topl += bt["profit"]
            bas = datetime.datetime.fromtimestamp(
                mums[a].open_time / 1000, datetime.timezone.utc)
            print(f"  pencere {wi+1} [{bas:%d.%m %H:%M}] "
                  f"{bt['profit']:>+9.2f}$ islem {bt['trades']:>2} "
                  f"K{bt['wins']} Z{bt['losses']}")
        print(f"  TOPLAM {topl:+.2f}$")


if __name__ == "__main__":
    main()

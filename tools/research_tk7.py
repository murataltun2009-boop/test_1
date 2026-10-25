# -*- coding: utf-8 -*-
"""TIK 1m adaylarinin PENCERE-ICI DAGILIMI: tek pencereye dayali
kazananlari ayristirmak. 6x500 dagitik pencere (guncel dogrulama)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datetime

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


def calistir(candles, sym, tf):
    from core.paper import PaperTrader
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.tk_window = 60
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    return p.backtest(candles, tf)


ADAY = ["ERAUSDT", "ENAUSDT", "UNIUSDT", "HBARUSDT", "LINKUSDT",
        "SOLUSDT", "DOGEUSDT", "ADAUSDT"]

for sym in ADAY:
    mums = to_mum(fetch_rows(sym, "1m", 3000))
    n = len(mums)
    topl = 0.0
    poz = 0
    satir = []
    for wi in range(6):
        a = n - (6 - wi) * 500
        dil = mums[a:a + 500]
        bt = calistir(dil, sym, "1m")
        topl += bt["profit"]
        if bt["profit"] > 0:
            poz += 1
        bas = datetime.datetime.fromtimestamp(
            dil[0].open_time / 1000, datetime.timezone.utc)
        satir.append(f"[{bas:%d.%m %H:%M}] {bt['profit']:>+7.1f}/"
                     f"{bt['trades']} i")
        print(f"  {sym} w{wi+1}: {bt['profit']:>+9.2f}$ islem {bt['trades']:>2}")
    print(f"TOPLAM {sym}: {topl:+.2f}$ poz-pencere {poz}/6 "
          f"| {' | '.join(satir[:2])}...\n")

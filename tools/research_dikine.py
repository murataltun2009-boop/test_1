# -*- coding: utf-8 -*-
"""
DIKINE PENCERE ölçümü — taze 1h verisi, 3 coin x 4 pencere (500 bar) x
modlar. Production default (düzeltici AÇIK, compounding'li).
Amaç: TEK pencereye dayanmayan, rejime dayanikli seçim.
Calistirma: python tools/research_dikine.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

import config as cfg
import datetime


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


MODLAR = ["ma_only", "osc_only", "signal", "signal_long", "ppt"]
PENCERE = 500


def calistir(candles, tf, mode):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    bt = p.backtest(candles, tf)
    return bt["profit"], bt["trades"]


def main():
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        mums = to_mum(fetch_rows(sym, "1h", PENCERE * 4 + 100))
        n = len(mums)
        print(f"\n======== {sym} 1h — {n} mum, {PENCERE} barlik "
              f"{PENCERE * 4 // PENCERE} dikey pencere ========")
        toplamlar = {m: 0.0 for m in MODLAR}
        for wi in range(4):
            a = n - (4 - wi) * PENCERE
            b = a + PENCERE
            dil = mums[a:b]
            bas = datetime.datetime.fromtimestamp(
                dil[0].open_time / 1000, datetime.timezone.utc)
            bit = datetime.datetime.fromtimestamp(
                dil[-1].open_time / 1000, datetime.timezone.utc)
            sonuc = []
            for m in MODLAR:
                net, tr = calistir(dil, "1h", m)
                toplamlar[m] += net
                sonuc.append(f"{m:>12}:{net:>+8.1f}$({tr:>3})")
            print(f"  pencere {wi+1} [{bas:%d.%m}..{bit:%d.%m}]: "
                  + " | ".join(sonuc))
        print("  TOPLAM: " + " | ".join(
            f"{m}: {toplamlar[m]:>+8.1f}$" for m in MODLAR))


if __name__ == "__main__":
    main()

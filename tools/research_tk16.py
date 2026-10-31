# -*- coding: utf-8 -*-
"""
TK canli zarar duzeltmesi — KOMBINASYON OLCUMU (2026-10-31).

Knop degiskenleri: pozisyon boyu (fraction), banka esigi (bank_pct +
RR tabani), zarar-sonrasi bekleme (pause), stop genisligi (sl).

Not: fraction kuculdukce stop kaybi (para) kuculur; banka hedefi
bakiyenin yuzdesi olarak SABIT kaldigi icin hedefin FIYAT mesafesi
buyur -> R:R iyilesir. Bu yuzden fraction + bank_pct birlikte olculur.

Calistirma: python tools/research_tk16.py
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


from core.paper import PaperTrader

COINS = ["DOGEUSDT", "HBARUSDT", "UNIUSDT", "BTCUSDT", "ETHUSDT",
         "ENAUSDT", "ADAUSDT"]

# (etiket, fraction, bank_pct, bank_rr, pause, sl_override)
VARIANTS = [
    ("A eski (f1.0 bp2.5 rr0 p0)", 1.0, 0.025, 0.0, 0, None),
    ("B f0.4 bp2.5 rr0 p0", 0.4, 0.025, 0.0, 0, None),
    ("C f0.4 bp2.5 rr0 p3", 0.4, 0.025, 0.0, 3, None),
    ("D f0.4 bp1.5 rr1.8 p3", 0.4, 0.015, 1.8, 3, None),
    ("E f0.4 bp1.0 rr2.2 p3", 0.4, 0.010, 2.2, 3, None),
    ("F f0.6 bp2.0 rr1.8 p3", 0.6, 0.020, 1.8, 3, None),
    ("G f0.4 bp2.5 rr2.2 p0", 0.4, 0.025, 2.2, 0, None),
    ("H f0.4 bp2.5 rr0 p3 sl0.5", 0.4, 0.025, 0.0, 3, 0.005),
    ("I f0.4 bp1.5 rr1.8 p5", 0.4, 0.015, 1.8, 5, None),
    ("J f0.3 bp2.5 rr0 p3", 0.3, 0.025, 0.0, 3, None),
]

data = {}
for sym in COINS:
    try:
        data[sym] = to_mum(fetch_rows(sym, "1m", 3000))
    except Exception as e:                       # noqa: BLE001
        print(sym, "veri yok:", e)

for etiket, frac, bp, rr, pause, sl in VARIANTS:
    tpl = 0.0
    n_is = 0
    kaz = 0
    kay = 0
    kom = 0.0
    kaz_m = 0.0
    kay_m = 0.0
    en_kotu = 0.0
    per_coin = {}
    for sym, mums in data.items():
        n = len(mums)
        sym_pnl = 0.0
        for wi in range(6):
            a = n - (6 - wi) * 500
            if a < 200:
                continue
            p = PaperTrader(sym)
            p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                        wallet_fraction=0.8, mode="tk", risk_pct=0.03)
            p.tk_window = 60
            p.tk_fraction = frac
            p.tk_bank_pct = bp
            p.tk_bank_rr = rr
            p.tk_pause_bars = pause
            if sl is not None:
                p.tk_sl = sl
            p.running = True
            p.start_balance = 1000.0
            p.balance = 1000.0
            p.backtest(mums[a:a + 500], "1m")
            kapali = sum(t.net_pnl for t in p.trades)
            sym_pnl += kapali
            tpl += kapali
            en_kotu = min(en_kotu, kapali)
            n_is += len(p.trades)
            kom += p.commission_paid
            for t in p.trades:
                if t.net_pnl >= 0:
                    kaz += 1
                    kaz_m += t.net_pnl
                else:
                    kay += 1
                    kay_m += t.net_pnl
        per_coin[sym] = sym_pnl
    ort = tpl / n_is if n_is else 0.0
    aw = kaz_m / kaz if kaz else 0.0
    al = kay_m / kay if kay else 0.0
    det = " ".join(f"{s[:4]}{v:+.0f}" for s, v in per_coin.items())
    print(f"{etiket:<28} {tpl:>+8.0f}$  islem {n_is:>3} "
          f"K{kaz}/Z{kay}  ort {ort:+.2f}$  kaz {aw:+.1f}/kay {al:+.1f}  "
          f"kom {kom:.0f}$  en-kotu-pencere {en_kotu:+.0f}$")
    print(f"   {det}")

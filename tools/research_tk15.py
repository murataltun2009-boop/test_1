# -*- coding: utf-8 -*-
"""
TK canli zarar duzeltmesi OLCUMU (2026-10-31).

Canli teshis: 66 islem, net -330$, komisyon 255$. Kok neden: SL %0,3 x
10x x %80 teminat -> stop kaybi ~bakiyenin %2,4'u; banka hedefi
bakiyenin %2,5'i -> brut R:R ~1:1, komisyonla negatif beklenti.

Burada uc knop olculur (ayni veri, ayni pencereler):
  * PAPER_TK_BANK_RR      : banka esigi >= stop riski x RR
  * PAPER_TK_PAUSE_BARS   : zarar sonrasi ayni yonde K bar giris yok
  * PAPER_TK_FRACTION     : pozisyon boyu (yalniz mutlak $ olcegi)

Calistirma: python tools/research_tk15.py
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

# (etiket, bank_rr, pause_bars)
VARIANTS = [
    ("ESKI (rr0 pause0)", 0.0, 0),
    ("rr1.8", 1.8, 0),
    ("rr2.2", 2.2, 0),
    ("rr1.8+pause3", 1.8, 3),
    ("rr2.2+pause3", 2.2, 3),
    ("rr2.2+pause5", 2.2, 5),
]

data = {}
for sym in COINS:
    try:
        data[sym] = to_mum(fetch_rows(sym, "1m", 3000))
    except Exception as e:                       # noqa: BLE001
        print(sym, "veri yok:", e)

for etiket, rr, pause in VARIANTS:
    tpl = 0.0
    n_is = 0
    kaz = 0
    kay = 0
    kom = 0.0
    stop_n = 0
    flip_n = 0
    print(f"\n#### {etiket} ####")
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
            p.tk_fraction = 1.0          # olcum: boyut etkisi ayri
            p.tk_bank_rr = rr
            p.tk_pause_bars = pause
            p.running = True
            p.start_balance = 1000.0
            p.balance = 1000.0
            p.backtest(mums[a:a + 500], "1m")
            kapali = sum(t.net_pnl for t in p.trades)
            sym_pnl += kapali
            tpl += kapali
            n_is += len(p.trades)
            kaz += sum(1 for t in p.trades if t.net_pnl >= 0)
            kay += sum(1 for t in p.trades if t.net_pnl < 0)
            kom += p.commission_paid
            for t in p.trades:
                if "stop" in t.exit_reason:
                    stop_n += 1
                elif "flip" in t.exit_reason or "döndü" in t.exit_reason:
                    flip_n += 1
        print(f"  {sym:<12} {sym_pnl:>+9.2f}$")
    ort = tpl / n_is if n_is else 0.0
    print(f"  TOPLAM {tpl:+.2f}$  islem {n_is} (K{kaz}/Z{kay})  "
          f"islem-ort {ort:+.2f}$  komisyon {kom:.0f}$  "
          f"stop {stop_n} / flip {flip_n}")

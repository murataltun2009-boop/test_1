# -*- coding: utf-8 -*-
"""
TK 2. tur ince tarama (2026-10-31): banka hedefi / stop / deadband /
confirm / pause kombinasyonlari. Sabit: f0.5, 8x500, 7 coin.
Calistirma: python tools/research_tk18.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research_tk16 as r
from core.paper import PaperTrader

# (etiket, bank_pct, sl, db, cf, pause)
VARIANTS = [
    ("A bp2.5 sl0.3 db0", 0.025, 0.003, 0.0, 1, 3),
    ("B bp3.0 sl0.3 db0", 0.030, 0.003, 0.0, 1, 3),
    ("C bp3.5 sl0.3 db0", 0.035, 0.003, 0.0, 1, 3),
    ("D bp3.0 sl0.4 db0", 0.030, 0.004, 0.0, 1, 3),
    ("E bp3.0 sl0.25 db0", 0.030, 0.0025, 0.0, 1, 3),
    ("F bp3.0 sl0.3 db0.02", 0.030, 0.003, 0.0002, 1, 3),
    ("G bp3.0 sl0.3 db0.03", 0.030, 0.003, 0.0003, 1, 3),
    ("H bp3.0 sl0.3 cf2", 0.030, 0.003, 0.0, 2, 3),
    ("I bp3.0 sl0.3 p0", 0.030, 0.003, 0.0, 1, 0),
    ("J bp4.0 sl0.3 db0", 0.040, 0.003, 0.0, 1, 3),
]

data = {}
for sym in r.COINS:
    try:
        data[sym] = r.to_mum(r.fetch_rows(sym, "1m", 4500))
    except Exception as e:                       # noqa: BLE001
        print(sym, "veri yok:", e)

for etiket, bp, sl, db, cf, pz in VARIANTS:
    tpl = 0.0
    n = 0
    k = 0
    z = 0
    km = 0.0
    zm = 0.0
    kom = 0.0
    worst = 0.0
    per = {}
    for sym, mums in data.items():
        N = len(mums)
        sp = 0.0
        for wi in range(8):
            a = N - (8 - wi) * 500
            if a < 200:
                continue
            p = PaperTrader(sym)
            p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                        wallet_fraction=0.8, mode="tk", risk_pct=0.03)
            p.tk_window = 60
            p.tk_fraction = 0.50
            p.tk_bank_pct = bp
            p.tk_bank_rr = 1.8
            p.tk_pause_bars = pz
            p.tk_sl = sl
            p.tk_rib_deadband = db
            p.tk_rib_confirm = cf
            p.running = True
            p.start_balance = 1000.0
            p.balance = 1000.0
            p.backtest(mums[a:a + 500], "1m")
            w = sum(t.net_pnl for t in p.trades)
            sp += w
            tpl += w
            worst = min(worst, w)
            n += len(p.trades)
            kom += p.commission_paid
            for t in p.trades:
                if t.net_pnl >= 0:
                    k += 1
                    km += t.net_pnl
                else:
                    z += 1
                    zm += t.net_pnl
        per[sym] = sp
    aw = km / k if k else 0.0
    al = zm / z if z else 0.0
    det = " ".join(f"{s[:4]}{v:+.0f}" for s, v in per.items())
    print(f"{etiket:<22} {tpl:>+7.0f}$ islem {n:>4} "
          f"K{k}/Z{z} (%{100*k/max(1,k+z):.0f}) ort {tpl/max(1,n):+.2f}$ "
          f"kaz {aw:+.1f}/kay {al:+.1f} kom {kom:.0f}$ en-kotu {worst:+.0f}$")
    print("   " + det)

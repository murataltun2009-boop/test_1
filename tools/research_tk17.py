# -*- coding: utf-8 -*-
"""
TK ikinci tur duzeltme OLCUMU (2026-10-31, canli 27 islem: -25,74$).

Canli desen: girisler donus tepelerine denk geliyor; kazanclar +23,5
(banka %2,5), kayiplar -15,5 (stop %0,3 + komisyon) -> R:R ~1,5 ama
kazanma orani %37 (10/27). Basabas icin ~%40 gerekli.

Knoplar:
  * tk_sar      : stop->ters (chop'ta ping-pong supheli)
  * tk_rib_deadband / tk_rib_confirm : EMA20/EMA50 mikro-kesisme filtresi
  * tk_entry_offset : yildiz yonunde X kadar ilerleme tetigi (tukenmis
    donus tepesine giris elenir)

Calistirma: python tools/research_tk17.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research_tk16 as r
from core.paper import PaperTrader

# (etiket, sar, deadband, confirm, offset, bank_pct)
VARIANTS = [
    ("0 MEVCUT", True, 0.0, 1, 0.0, 0.025),
    ("1 SAR kapali", False, 0.0, 1, 0.0, 0.025),
    ("2 SAR off + db0.03%", False, 0.0003, 1, 0.0, 0.025),
    ("3 SAR off + db0.05%", False, 0.0005, 1, 0.0, 0.025),
    ("4 SAR off + confirm2", False, 0.0, 2, 0.0, 0.025),
    ("5 SAR off + off0.05%", False, 0.0, 1, 0.0005, 0.025),
    ("6 SAR off + off0.10%", False, 0.0, 1, 0.0010, 0.025),
    ("7 SAR off + db+off", False, 0.0003, 1, 0.0005, 0.025),
    ("8 SAR off + bank3%", False, 0.0, 1, 0.0, 0.030),
    ("9 SAR off + db + bank3", False, 0.0003, 1, 0.0, 0.030),
    ("10 SAR on + db + off", True, 0.0003, 1, 0.0005, 0.025),
]

data = {}
for sym in r.COINS:
    try:
        data[sym] = r.to_mum(r.fetch_rows(sym, "1m", 4500))
    except Exception as e:                       # noqa: BLE001
        print(sym, "veri yok:", e)

for etiket, sar, db, cf, off, bp in VARIANTS:
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
            p.tk_pause_bars = 3
            p.tk_sar = sar
            p.tk_rib_deadband = db
            p.tk_rib_confirm = cf
            p.tk_entry_offset = off
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
    print(f"{etiket:<24} {tpl:>+7.0f}$ islem {n:>4} "
          f"K{k}/Z{z} (%{100*k/max(1,k+z):.0f}) ort {tpl/max(1,n):+.2f}$ "
          f"kaz {aw:+.1f}/kay {al:+.1f} kom {kom:.0f}$ en-kotu {worst:+.0f}$")
    print("   " + det)

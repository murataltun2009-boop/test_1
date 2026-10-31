# -*- coding: utf-8 -*-
"""
TK 3. tur: PULLBACK (negatif giris offseti) olcumu — 2026-10-31.

Canli desen: girisler donus tepelerine denk geliyor (SHORT 0,1909 -> 0,1915).
Sinyal yonunde ILERLEME tetigi (offset>0) olculdu, zararli bulundu.
Simdi TERSI deneniyor: sinyal fiyatinin GERISINE pasif limit koy
(pullback) — ayni sinyal, daha iyi fiyat, stop mesafesi kucuk.

Sabit: f0.5, bp3.5, rr1.8, pause3, cf2, REQ=True, 1m, 7 coin.
Calistirma: python tools/research_tk19.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import research_tk16 as r
from core.paper import PaperTrader

# (etiket, deadband, offset)
VARIANTS = [
    ("A db.05 off 0 (mevcut)", 0.0005, 0.0),
    ("B db.05 off -0.02%", 0.0005, -0.0002),
    ("C db.05 off -0.05%", 0.0005, -0.0005),
    ("D db.05 off -0.10%", 0.0005, -0.0010),
    ("E db.02 off -0.05%", 0.0002, -0.0005),
    ("F db.08 off -0.05%", 0.0008, -0.0005),
]


def olc(data, nwin, etiket, db, off):
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
        for wi in range(nwin):
            a = N - (nwin - wi) * 500
            if a < 200:
                continue
            p = PaperTrader(sym)
            p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                        wallet_fraction=0.8, mode="tk", risk_pct=0.03)
            p.tk_window = 60
            p.tk_bank_pct = 0.035
            p.tk_bank_rr = 1.8
            p.tk_pause_bars = 3
            p.tk_rib_confirm = 2
            p.tk_rib_deadband = db
            p.tk_entry_offset = off
            p.tk_require_trend = True
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
    print(f"{etiket:<24} {tpl:>+7.0f}$ islem {n:>4} "
          f"K{k}/Z{z} (%{100*k/max(1,k+z):.0f}) ort {tpl/max(1,n):+.2f}$ "
          f"kaz {km/max(1,k):+.1f}/kay {zm/max(1,z):+.1f} "
          f"kom {kom:.0f}$ en-kotu {worst:+.0f}$")
    print("   " + " ".join(f"{s[:4]}{v:+.0f}" for s, v in per.items()))


if __name__ == "__main__":
    d8 = {}
    d6 = {}
    for sym in r.COINS:
        try:
            rows = r.fetch_rows(sym, "1m", 4500)
            d8[sym] = r.to_mum(rows)
            d6[sym] = r.to_mum(rows[-3000:])
        except Exception as e:                    # noqa: BLE001
            print(sym, "veri yok:", e)
    print("=== 8x500 (4500 bar) ===")
    for v in VARIANTS:
        olc(d8, 8, *v)
    print("=== 6x500 (3000 bar) ===")
    for v in VARIANTS:
        olc(d6, 6, *v)

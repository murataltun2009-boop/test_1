# -*- coding: utf-8 -*-
"""
DUZELTICI (seri kilidi) OLCUMU — tarama.

Kural: zarar biten islemden sonra K BAR yeni GIRIS acilmaz.
Teshis: kayip serileri kumali (teshis raporu: zarar sonrasi ort -7.5$,
temiz seride +1.6$, dort mod + dort pencerede tutarli).

Her mod icin K=0 (kapali, taban) ile K suresi yanyana yazilir.
Genel guvenlik amaciyla DIGER modlarin (trend/muro/1m/ppt/range)
neye benzedigine bakilir.

Calistirma:  python tools/research_duzeltici.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base

MODLAR = ["ma_only", "osc_only", "signal", "signal_long",
          "range", "trend", "muro", "1m", "ppt"]
K_SET = [0, 2, 4, 6, 8, 12]


def calistir(mode: str, cdl, tf, k: int):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.corr_on = True
    p.corr_pause_bars = k
    return p.backtest(cdl, tf)


def main():
    toplam = {(m, k): 0.0 for m in MODLAR for k in K_SET}
    for name, cdl, tf in base.jobs():
        print(f"\n############ {name} ############")
        for m in MODLAR:
            satir = []
            for k in K_SET:
                bt = calistir(m, cdl, tf, k)
                toplam[(m, k)] += bt["profit"]
                satir.append(f"K{k}={bt['profit']:>7.1f}$")
            print(f"{m:>12}: " + " | ".join(satir))
    print("\n############ OZET: toplam net kar/Z (4 pencere, 1000$ baslangic) ############")
    print(f"{'MOD':>12} | " + " | ".join(f"K{k}" for k in K_SET) + " | en iyi")
    for m in MODLAR:
        nets = [toplam[(m, k)] for k in K_SET]
        yi = max(range(len(K_SET)), key=lambda i: nets[i])
        print(f"{m:>12} | " + " | ".join(f"{n:>7.1f}" for n in nets) +
              f" | K{K_SET[yi]}")


if __name__ == "__main__":
    main()

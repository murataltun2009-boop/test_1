# -*- coding: utf-8 -*-
"""
KESIN KARAR OLcUMU 2 — 1. turun en iyisi (KARMGUC) uzerine rafinaj:
  GUCREV : GUC yen yazimi gate ONCESI (arm, zayif sinyalle dusmez)
  K8/K10 : daha uzun durus + ARM + GUC
  MAKER  : exit komisyonu maker %0.02 (limit dolum gercekcigi)
  GUCBE  : GUC + 1h/15m mikro-klip (corr_be_buf 0.004)
SABIT STAKE, pencere bazli.
Calistirma: python tools/research_karar2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base

MODLAR = ["signal", "signal_long", "ma_only", "osc_only"]
VARIANTLAR = ["TABAN", "KARMGUC", "GUCREV", "K8GUC", "K10GUC",
              "MAKER", "GUCBE"]


def calistir(mode: str, cdl, tf, varyant: str):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.fixed_stake = True
    if varyant == "TABAN":
        p.corr_on = False
    elif varyant == "KARMGUC":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = True
        p.corr_strong_only = True
    elif varyant == "GUCREV":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = True
        p.corr_strong_only = True
        p.corr_strong_first = True
    elif varyant == "K8GUC":
        p.corr_on = True
        p.corr_pause_bars = 8
        p.corr_arm_on = True
        p.corr_strong_only = True
    elif varyant == "K10GUC":
        p.corr_on = True
        p.corr_pause_bars = 10
        p.corr_arm_on = True
        p.corr_strong_only = True
    elif varyant == "MAKER":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = True
        p.corr_strong_only = True
        p.fee_close_rate = 0.0002       # maker exit (limit dolum)
    elif varyant == "GUCBE":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = True
        p.corr_strong_only = True
        # mikro-klip default corr_be_buf=0.004 + corr_tfs {1h,15m} aktif
    bt = p.backtest(cdl, tf)
    return bt["profit"], bt["trades"]


def main():
    toplam = {(v, m): 0.0 for v in VARIANTLAR for m in MODLAR}
    for name, cdl, tf in base.jobs():
        print(f"\n############ {name} ############")
        print(f"{'VARYANT':>8} | " + " | ".join(f"{m:>11}" for m in MODLAR))
        for v in VARIANTLAR:
            satir = []
            for m in MODLAR:
                net, n = calistir(m, cdl, tf, v)
                toplam[(v, m)] += net
                satir.append(f"{net:>+11.1f}")
            print(f"{v:>8} | " + " | ".join(satir))
    print("\n############ TOPLAM (4 pencere, sabit stake) ############")
    for m in MODLAR:
        print(f"-- {m}")
        for v in VARIANTLAR:
            print(f"   {v:>8}: {toplam[(v, m)]:>+9.1f}$")


if __name__ == "__main__":
    main()

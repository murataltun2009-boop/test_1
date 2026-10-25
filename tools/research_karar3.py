# -*- coding: utf-8 -*-
"""
KESIN KARAR OLcUMU 3 — dürüst maker dolum (yalniz LIMIT cikislar:
basabas klip dokunmasi / kâr kilidi / kâr bankasi = %0.02;
NÖTR-flip / stop / likidasyon market = %0.05).
Varyantlar: KARMGUC vs GUCREV vs K8/K10 uzerine rafinaj.
SABIT STAKE, pencere bazli.
Calistirma: python tools/research_karar3.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base

MODLAR = ["signal", "signal_long", "ma_only", "osc_only"]
VARIANTLAR = ["TABAN", "KARMGUC", "GUCREV", "GUC8REV", "GUC10REV",
              "GUCREV-ARMYOK", "GUCREV-KARM"]


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
    elif varyant == "GUC8REV":
        p.corr_on = True
        p.corr_pause_bars = 8
        p.corr_arm_on = True
        p.corr_strong_only = True
        p.corr_strong_first = True
    elif varyant == "GUC10REV":
        p.corr_on = True
        p.corr_pause_bars = 10
        p.corr_arm_on = True
        p.corr_strong_only = True
        p.corr_strong_first = True
    elif varyant == "GUCREV-ARMYOK":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = False
        p.corr_strong_only = True
        p.corr_strong_first = True
    elif varyant == "GUCREV-KARM":
        # arm ON ama strong_first YOK (1. tur sirasi)
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = True
        p.corr_strong_only = True
        p.corr_strong_first = False
    bt = p.backtest(cdl, tf)
    return bt["profit"], bt["trades"]


def main():
    toplam = {(v, m): 0.0 for v in VARIANTLAR for m in MODLAR}
    for name, cdl, tf in base.jobs():
        print(f"\n############ {name} ############")
        print(f"{'VARYANT':>14} | " + " | ".join(f"{m:>11}" for m in MODLAR))
        for v in VARIANTLAR:
            satir = []
            for m in MODLAR:
                net, n = calistir(m, cdl, tf, v)
                toplam[(v, m)] += net
                satir.append(f"{net:>+11.1f}")
            print(f"{v:>14} | " + " | ".join(satir))
    print("\n############ TOPLAM (4 pencere, sabit stake) ############")
    for m in MODLAR:
        print(f"-- {m}")
        for v in VARIANTLAR:
            print(f"   {v:>14}: {toplam[(v, m)]:>+9.1f}$")


if __name__ == "__main__":
    main()

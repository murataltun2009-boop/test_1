# -*- coding: utf-8 -*-
"""
URETIM KONTROL: yeni default'lar (corr K8+ARM+GUC+first, maker exit)
compounding'li (fixed_stake=False) tum modlarda pencere bazli.
Taban (corr kapali) ile yan yana: diger modlarin zarar GORULMUYOR mu?
Calistirma: python tools/research_uretim.py
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


def calistir(mode: str, cdl, tf, corr: bool):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.fixed_stake = False            # gercek: compounding
    p.corr_on = corr
    p.corr_arm_on = corr
    p.corr_strong_only = corr
    p.corr_strong_first = corr
    bt = p.backtest(cdl, tf)
    return bt["profit"]


def main():
    # Config default'lari corr tarafinda kullanilir; taban icin olduklari
    # bayraklari elle kapatiyoruz (ayni instansta).
    toplam = {(m, o): 0.0 for m in MODLAR for o in ("KAPALI", "ACIK")}
    for name, cdl, tf in base.jobs():
        print(f"\n############ {name} ############")
        for m in MODLAR:
            kap = calistir(m, cdl, tf, False)
            acik = calistir(m, cdl, tf, True)
            toplam[(m, "KAPALI")] += kap
            toplam[(m, "ACIK")] += acik
            print(f"  {m:>12}: kapali {kap:>+10.1f}$ | acik {acik:>+10.1f}$")
    print("\n############ TOPLAM (4 pencere, compounding) ############")
    for m in MODLAR:
        print(f"  {m:>12}: kapali {toplam[(m, 'KAPALI')]:>+10.1f}$"
              f" | acik {toplam[(m, 'ACIK')]:>+10.1f}$")


if __name__ == "__main__":
    main()

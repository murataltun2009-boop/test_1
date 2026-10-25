# -*- coding: utf-8 -*-
"""
KESIN KARAR OLCUMU (durst dolum, pencere bazli):
  * TABAN        : uretim default (fib skor ON, corr OFF)
  * K{k}         : c?r unl kiliti corr_pause_bars=k (fib ON)
  * NO FIB       : fib skor gate OFF (durst tepkimesinden sonra tekrar olc)
  * BE1H         : K + 1h/15m mikro-klip (corr_be_buf 0.004)
Sonuclar SABIT STAKE ve pencere-baz-yazilir (karsilastirma adil).
Calistirma: python tools/research_karar.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base

MODLAR = ["signal", "signal_long", "ma_only", "osc_only"]
VARIANTLAR = ["TABAN", "K2", "K4", "K6", "NOFIB", "BE1H",
              "ARM", "GUC", "KARM", "KARMGUC"]


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
    elif varyant.startswith("K") and varyant[1:].isdigit():
        p.corr_on = True
        p.corr_pause_bars = int(varyant[1:])
    elif varyant == "NOFIB":
        p.corr_on = False
        p.fib_score_on = False
    elif varyant == "BE1H":
        p.corr_on = True
        p.corr_pause_bars = 4
        # mikro-klip: corr_tfs default {"1h","15m"} kalsin
    elif varyant == "ARM":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = True
    elif varyant == "GUC":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_strong_only = True
    elif varyant == "KARM":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = True
        p.corr_strong_only = False
    elif varyant == "KARMGUC":
        p.corr_on = True
        p.corr_pause_bars = 6
        p.corr_arm_on = True
        p.corr_strong_only = True
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

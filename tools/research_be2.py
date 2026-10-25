# -*- coding: utf-8 -*-
"""
DUZELTICI ince tarama — SABIT STAKE ile (compounding yok, karsilastirma
adil): basabaş tolerans (corr_be_buf) x seri kilidi (corr_pause_bars).

Rapor: toplam net + EN KOTU pencere (saglamlık) + islem sayisi.
Calistirma: python tools/research_be2.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base

MODLAR = ["signal", "signal_long", "ma_only", "osc_only"]
BE_SET = [0.0012, 0.002, 0.003, 0.004, 0.005]
K_SET = [0, 2, 4, 6, 8]


def calistir(mode, cdl, tf, be, k):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.fixed_stake = True
    p.corr_on = True
    p.corr_be_buf = be
    p.corr_pause_bars = k
    bt = p.backtest(cdl, tf)
    return bt["profit"], bt["trades"]


def main():
    res = {}
    for name, cdl, tf in base.jobs():
        for m in MODLAR:
            for be in BE_SET:
                for k in K_SET:
                    net, n = calistir(m, cdl, tf, be, k)
                    res.setdefault((m, be, k), []).append((net, n))
    print("### SABIT STAKE ozeti: toplam | en kotu pencere | islemleri toplam)")
    print(f"{'MOD':>12} {'BE':>7} " + " ".join(f"K{k}" for k in K_SET))
    for m in MODLAR:
        for be in BE_SET:
            satir = []
            for k in K_SET:
                g = res[(m, be, k)]
                tot = sum(x[0] for x in g)
                worst = min(x[0] for x in g)
                n = sum(x[1] for x in g)
                satir.append(f"{tot:>+7.0f}/{worst:>+6.0f}")
            print(f"{m:>12} {be:>7.1e} " + "  ".join(satir))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
DUZELTICI FINAL tarama — honest fill + TF-limt cito-klip:
  * corr ON: sadecee 1h/15m skor modlarinda mikro-klip (corr_be_buf)
  * 5m skor modlari default BE (0.0012) ile kalir
Kapsam: corr OFF (taban) vs corr_be x K (sabit stake) + final compounding.
Calistirma: python tools/research_final.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base

MODLAR = ["signal", "signal_long", "ma_only", "osc_only"]
BE_SET = [0.0012, 0.0025, 0.004]
K_SET = [0, 2, 4]


def trader(mode):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    return p


def main():
    res = {}
    print("### TABAN (corr OFF) + DUZELTICI grid — SABIT STAKE ###")
    for name, cdl, tf in base.jobs():
        print(f"\n-- {name}")
        # taban
        for m in MODLAR:
            p = trader(m)
            p.fixed_stake = True
            p.corr_on = False
            bt = p.backtest(cdl, tf)
            res.setdefault(("TABAN", m, 0), []).append(bt["profit"])
            print(f"   TABAN    {m:>12} : {bt['profit']:>+8.1f}$")
        for be in BE_SET:
            for k in K_SET:
                for m in MODLAR:
                    p = trader(m)
                    p.fixed_stake = True
                    p.corr_on = True
                    p.corr_be_buf = be
                    p.corr_pause_bars = k
                    bt = p.backtest(cdl, tf)
                    res.setdefault((f"BE{be:.4f}K{k}", m, 0),
                                   []).append(bt["profit"])
        g = [(lab, m, sum(v)) for (lab, m, _), v in res.items()]
        for lab, m, tot in sorted(g, key=lambda x: -x[2])[:8]:
            print(f"   kisma: {lab:>12} {m:>12} toplam {tot:>+9.1f}$")
    print("\n### OZET (4 pencere toplam, sabit stake) ###")
    for (lab, m, _), v in sorted(res.items(), key=lambda kv: -sum(kv[1])):
        print(f"  {lab:>12} {m:>12} toplam {sum(v):>+9.1f}$")


if __name__ == "__main__":
    main()

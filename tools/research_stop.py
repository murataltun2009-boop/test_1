# -*- coding: utf-8 -*-
"""
DUZELTICI STOP taramasi (cekinadil dolum, sabit stake):
  skor modlarinda mikro-klip YOK, kok-integer stop = giris x (1-stop_down),
  +2% banka (touch, adil) bolgesi acik.
Rapor: toplam + en kotu pencere + islem.
Calistirma: python tools/research_stop.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base

MODLAR = ["signal", "signal_long", "ma_only", "osc_only"]
ST_SET = [0.002, 0.003, 0.005, 0.008, 0.012]
K_SET = [0, 2, 4]


def calistir(mode, cdl, tf, st, k):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.fixed_stake = True
    p.corr_on = True
    p.corr_stop_down = st
    p.corr_pause_bars = k
    bt = p.backtest(cdl, tf)
    banka = sum(1 for t in p.trades if "bankas" in t.exit_reason)
    return bt["profit"], bt["trades"], banka


def main():
    res = {}
    for name, cdl, tf in base.jobs():
        for m in MODLAR:
            for st in ST_SET:
                for k in K_SET:
                    net, n, b = calistir(m, cdl, tf, st, k)
                    res.setdefault((m, st, k), []).append((net, n, b))
    print("### SABIT STAKE: toplam | en kotu pencere | banka vurma toplam")
    print(f"{'MOD':>12} {'STOPD':>7} " + " ".join(f"K{k}" for k in K_SET))
    for m in MODLAR:
        for st in ST_SET:
            satir = []
            for k in K_SET:
                g = res[(m, st, k)]
                tot = sum(x[0] for x in g)
                worst = min(x[0] for x in g)
                nb = sum(x[2] for x in g)
                satir.append(f"{tot:>+7.0f}/{worst:>+6.0f}/b{nb}")
            print(f"{m:>12} {st:>7.3f} " + "  ".join(satir))


if __name__ == "__main__":
    main()

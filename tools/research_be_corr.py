# -*- coding: utf-8 -*-
"""
DUZELTICI 2. BILESSEN TARAMASI — basabaş toleransi (breakeven_buf) x
seri kilidi (corr_pause_bars) ortak matrisi.

TEGO bulgu: kazanan +1.6$ net (0.12% tampon), kaybeden -8.0$ net (komisyon
yuvarlak-trip); banka +%2 fiyat => +152$ net ama basabaş korumasi pozisyonu
yolda kesiyor. Iki kolu birlikte olcum.

Calistirma: python tools/research_be_corr.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import research_ppt as base

MODLAR = ["signal", "signal_long", "ma_only", "osc_only"]
BE_SET = [0.0012, 0.002, 0.004, 0.008, 0.0]   # 0 = koruma KAPALI
K_SET = [0, 4, 6, 8]


def calistir(mode: str, cdl, tf, be: float, k: int):
    from core.paper import PaperTrader
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    p.breakeven_buf = be
    p.corr_on = True
    p.corr_pause_bars = k
    bt = p.backtest(cdl, tf)
    bank_hit = sum(1 for t in p.trades if "bankas" in t.exit_reason)
    return bt, bank_hit


def main():
    toplam = {(m, be, k): 0.0 for m in MODLAR for be in BE_SET for k in K_SET}
    for name, cdl, tf in base.jobs():
        print(f"\n############ {name} ############")
        for m in MODLAR:
            print(f"-- {m}")
            for be in BE_SET:
                satir = []
                for k in K_SET:
                    bt, bank = calistir(m, cdl, tf, be, k)
                    toplam[(m, be, k)] += bt["profit"]
                    satir.append(f"K{k}={bt['profit']:>7.1f}({bank})")
                print(f"  BE{be:.4f}{'(off)' if be == 0 else '      '}: " +
                      " | ".join(satir))
    print("\n############ OZET: toplam net kar/Z ############")
    print(f"{'MOD':>12} {'BE':>8} | " + " | ".join(f"K{k}" for k in K_SET))
    for m in MODLAR:
        for be in BE_SET:
            nets = [toplam[(m, be, k)] for k in K_SET]
            print(f"{m:>12} {be:>8} | " + " | ".join(f"{n:>9.1f}" for n in nets))


if __name__ == "__main__":
    main()

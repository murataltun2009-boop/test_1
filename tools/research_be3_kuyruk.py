# -*- coding: utf-8 -*-
"""
DUZELTICI KUYRUK DENETIMI — sabit stake, BE tarayici audit:
  * kazanc/zarar ortalama ve adet, alis-satis oranti
  * EN KOTU 3 islem, zarar pudare (P95/P99)
  * likidasyon / hedef / banka adetleri
  * pozisyon tutma suresi (ort + tekil 90. persentil)
Calistirma: python tools/research_be3_kuyruk.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import config as cfg
import research_ppt as base

MODLAR = ["signal", "signal_long", "ma_only", "osc_only"]
BE_SET = [0.003, 0.004, 0.005, 0.006, 0.008]
K = 0


def audit(mode, cdl, tf, be):
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
    p.corr_pause_bars = K
    p.backtest(cdl, tf)
    ts = p.trades
    if not ts:
        return None
    nets = np.array([t.net_pnl for t in ts])
    gross = np.array([t.gross_pnl for t in ts])
    win = nets >= 0
    liki = sum(1 for t in ts if "LIKIDA" in (t.exit_reason or "").upper())
    hedef = sum(1 for t in ts if "hedefe" in (t.exit_reason or ""))
    banka = sum(1 for t in ts if "bankas" in (t.exit_reason or ""))
    return {
        "islem": len(ts),
        "net": float(nets.sum()),
        "kazanc_adet": int(win.sum()),
        "kazanc_ort": float(nets[win].mean()) if win.any() else 0.0,
        "zarar_adet": int((~win).sum()),
        "zarar_ort": float(nets[~win].mean()) if (~win).any() else 0.0,
        "zarar_p95": float(np.percentile(nets[~win], 5)) if (~win).any() else 0.0,
        "en_kotu": float(nets.min()),
        "likidasyon": liki,
        "hedef": hedef,
        "banka": banka,
        "en_kotu_3": [float(x) for x in sorted(nets)[:3]],
    }


def main():
    for name, cdl, tf in base.jobs():
        print(f"\n=== {name} ===")
        for be in BE_SET:
            satirlar = []
            for m in MODLAR:
                r = audit(m, cdl, tf, be)
                if r is None:
                    continue
                satirlar.append(
                    f"{m[:5]:5} net{r['net']:>+7.0f} Z{r['zarar_adet']:<4}"
                    f" Zort{r['zarar_ort']:>+6.1f} kotu{r['en_kotu']:>+6.1f}"
                    f" liki{r['likidasyon']} hedef{r['hedef']} banka{r['banka']}"
                    f" kotu3{[round(x,1) for x in r['en_kotu_3']]}")
            print(f"BE{be:.3f}:")
            for s_ in satirlar:
                print("   " + s_)


if __name__ == "__main__":
    main()

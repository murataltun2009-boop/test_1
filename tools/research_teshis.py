# -*- coding: utf-8 -*-
"""
ZARAR ANATOMISI — skor modlarinda (fib ACIK, uretim default) islem bazli
analiz. Duzeltici indikator TASARimi icin once TESHIS:

  * cikis sebelerine gore net P/L dagilimi (hangi kapilar para yiyor?)
  * kazanc/zarar asimetrisi ( Throw / Risk )
  * giris baglamina gore dilimler: ATR persentil, saat, pencere konumu,
    yon, ard arda zarar sira no

Calistirma:  python tools/research_teshis.py
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

MODLAR = ["ma_only", "osc_only", "signal", "signal_long"]


def atr_serisi(cdl):
    h = np.array([c.high for c in cdl], dtype=float)
    l = np.array([c.low for c in cdl], dtype=float)
    c = np.array([c.close for c in cdl], dtype=float)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    n = 14
    out = np.full(c.size, np.nan)
    if c.size > n:
        v = np.convolve(tr, np.ones(n) / n, mode="valid")
        out[n - 1:n - 1 + v.size] = v
    return out


def analiz(pencere_adi, cdl, trades):
    """Pencere x mod trades -> tanidik dilimler. Returns list of records."""
    atr = atr_serisi(cdl)
    open_ts = np.array([c.open_time for c in cdl], dtype=float)
    closes = np.array([c.close for c in cdl], dtype=float)
    hi = np.array([c.high for c in cdl], dtype=float)
    lo = np.array([c.low for c in cdl], dtype=float)
    # pencere konumu (100 bar)
    look = min(100, max(5, cdl and 5 or 5))
    pos = np.full(closes.size, np.nan)
    for i in range(closes.size):
        a = max(0, i - 99)
        L, H = lo[a:i + 1].min(), hi[a:i + 1].max()
        if H > L:
            pos[i] = (closes[i] - L) / (H - L)

    # ATR persentil (son 300 bar icinde)
    pct = np.full(closes.size, np.nan)
    for i in range(closes.size):
        a = max(0, i - 299)
        w = atr[a:i + 1]
        w = w[~np.isnan(w)]
        if w.size > 10:
            pct[i] = (w <= atr[i] if not np.isnan(atr[i]) else w <= w[-1]
                      ).mean() * 100.0 if atr[i] >= w.min() else 0.0
        if not np.isnan(atr[i]) and w.size > 10:
            pct[i] = float((w <= atr[i]).mean() * 100.0)

    recs = []
    streak = 0
    for t in trades:
        # giris bars indexi: open_ts'te arama (leriden geriye)
        i = int(np.searchsorted(open_ts, t.opened_at))
        i = min(i, closes.size - 1)
        saat = (int(t.opened_at) // 3600000) % 24
        rec = {
            "mod": None,
            "net": t.net_pnl,
            "gross": t.gross_pnl,
            "sebep": t.exit_reason,
            "yatay": t.exit_reason,
            "saat": saat,
            "atr_pct": pct[i] if i >= 0 else np.nan,
            "pos": pos[i] if i >= 0 else np.nan,
            "yon": ("SHORT" if "SHORT" in (t.reason or "") else "LONG"),
            "tutma_bars": (int(t.closed_at) - int(t.opened_at)) / 300000.0,
        }
        recs.append(rec)
        streak = streak + 1 if t.net_pnl < 0 else 0
        rec["streak"] = streak
    return recs


def ozet_bloklari(all_recs, isim, alan, kenarlar, baslik):
    print(f"\n--- {isim} | {baslik} ---")
    gruplar = defaultdict(lambda: [0, 0.0])
    for r in all_recs:
        v = r[alan]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            gr = "?"
        else:
            gr = "?"
            for i in range(len(kenarlar) - 1):
                if kenarlar[i] <= v < kenarlar[i + 1]:
                    gr = f"[{int(kenarlar[i])},{int(kenarlar[i+1])}) "
                    break
            else:
                gr = f"[{int(kenarlar[-1])}+]"
        gruplar[gr][0] += 1
        gruplar[gr][1] += r["net"]
    for gr in sorted(gruplar):
        n, net = gruplar[gr]
        ort = net / n if n else 0
        print(f"  {gr:>16} islem {n:>5} | net {net:>9.1f}$ | ort {ort:>7.3f}$")


def main():
    hepsi = {m: [] for m in MODLAR}
    for name, cdl, tf in base.jobs():
        print(f"\n############ {name} ############")
        from core.paper import PaperTrader
        p = PaperTrader(cfg.Settings())
        p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                    wallet_fraction=0.8, mode="signal", risk_pct=0.03)
        p.running = True
        p.start_balance = 1000.0
        p.balance = 1000.0
        for m in MODLAR:
            from core.paper import PaperTrader as PT
            pt = PT(cfg.Settings())
            pt.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                         wallet_fraction=0.8, mode=m, risk_pct=0.03)
            pt.running = True
            pt.start_balance = 1000.0
            pt.balance = 1000.0
            # fib skor bayragi uretim default'unda (config) birakildi
            bt = pt.backtest(cdl, tf)
            # configure moddan sonra: backtest cagrisinda mode setli mi?
            recs = analiz(name, cdl, pt.trades)
            for r in recs:
                r["mod"] = m
            hepsi[m].extend(recs)
            wins = bt["wins"]
            n = bt["trades"]
            print(f"{m:>12}: {n} islem net {bt['profit']:>8.1f}$ "
                  f"| k/z ort: "
                  f"kazanc {sum(r['net'] for r in recs if r['net']>0)/max(1,wins):.2f}$ "
                  f"| zarar {sum(r['net'] for r in recs if r['net']<0)/max(1,n-wins):.2f}$")

            # cikis sebebelri
            sebepler = defaultdict(lambda: [0, 0.0])
            for r in recs:
                key = r["sebep"][:34]
                sebepler[key][0] += 1
                sebepler[key][1] += r["net"]
            print(f"{'':>12}  cikis sebeb -> net (en kotu 6):")
            for key, (n2, net2) in sorted(sebepler.items(),
                                          key=lambda kv: kv[1][1])[-6:]:
                print(f"{'':>14}{key:<34} {n2:>5} islem {net2:>9.1f}$")
            # en kotu 3
            kotu = sorted(recs, key=lambda r: r["net"])[:3]
            for k in kotu:
                print(f"{'':>14}KOTU: {k['net']:>8.1f}$ {k['sebep'][:22]:<24}"
                      f" {k['yon']} tutma {k['tutma_bars']:.1f} bar "
                      f"atr% {k['atr_pct']:.0f} saat {k['saat']}")

    print("\n############ TUM PENCERELER (toplam) ############")
    for m in MODLAR:
        rs = hepsi[m]
        n = len(rs)
        net = sum(r["net"] for r in rs)
        print(f"\n== {m}: {n} islem, net {net:.1f}$ ==")
        ozet_bloklardi(rs, m, "atr_pct", [0, 20, 40, 60, 80, 100],
                       "ATR persentil giris")
        ozet_bloklardi(rs, m, "saat", list(range(25)), "Saat (UTC)")
        ozet_bloklardi(rs, m, "pos", [0, .2, .4, .6, .8, 1.01],
                       "Pencere konumu")
        ozet_bloklardi(rs, m, "streak", [0, 1, 2, 3, 4, 5, 99],
                       "Ard arda zarar sira no")
        # yon
        for yon in ("LONG", "SHORT"):
            g = [r for r in rs if r["yon"] == yon]
            print(f"  {yon:>16} islem {len(g):>5} | net "
                  f"{sum(r['net'] for r in g):>9.1f}$")


def ozet_bloklardi(rs, isim, alan, kenarlar, baslik):
    print(f"\n--- {isim} | {baslik} ---")
    gruplar = defaultdict(lambda: [0, 0.0])
    for r in rs:
        v = r[alan]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            gr = "?"
        elif alan == "saat":
            gr = f"{int(v):02d}"
        else:
            gr = "?"
            for i in range(len(kenarlar) - 1):
                if kenarlar[i] <= v < kenarlar[i + 1]:
                    gr = f"[{int(kenarlar[i])},{int(kenarlar[i+1])})"
                    break
            else:
                gr = f"[{int(kenarlar[-1])}+]"
        gruplar[gr][0] += 1
        gruplar[gr][1] += r["net"]
    for gr in sorted(gruplar):
        n, net = gruplar[gr]
        ort = net / n if n else 0
        print(f"  {gr:>16} islem {n:>5} | net {net:>9.1f}$ | ort {ort:>7.3f}$")


if __name__ == "__main__":
    main()

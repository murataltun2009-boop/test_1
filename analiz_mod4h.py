"""Karar modlarinin 4h uzerindeki etkisini karsilastirir.

Odak: kullanicinin sorunu -- acik LONG pozisyonu ("LONG @ 83.706,60")
hedefine ulasamayacag icin asili kaldi ve zarar ediyor. "signal_long"
modu bunu SAT sinyaliyle kapatir.

Calistir:  python analiz_mod4h.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from core.analysis import analyze
from core.binance_client import BinanceFuturesClient
from core.paper import PaperTrader

cl = BinanceFuturesClient(config.SYMBOL)


def sinyaller(cs, tf):
    res = analyze(symbol=config.SYMBOL, timeframe=tf,
                  open_times=[c.open_time for c in cs],
                  o=[c.open for c in cs], h=[c.high for c in cs],
                  l=[c.low for c in cs], c=[c.close for c in cs],
                  v=[c.volume for c in cs],
                  close_times=[c.close_time for c in cs],
                  strong_threshold=config.STRONG_THRESHOLD,
                  base_threshold=config.BASE_THRESHOLD)
    return [s.value for s in res.signals]


def kosu(cs, tf, mod, sig=None, bekleme=0):
    tr = PaperTrader(symbol=config.SYMBOL, balance=1000.0, leverage=10.0,
                     lookback=20)
    tr.running = True
    tr.mode = mod
    tr.short_rule = "entry"
    tr.min_hold_bars = bekleme
    tr.configure(balance=1000.0)
    st = tr.backtest(cs, tf, sig)
    n_long = sum(1 for t in tr.trades if t.side == "LONG")
    n_short = sum(1 for t in tr.trades if t.side == "SHORT")
    p = tr.position
    acik_kar = tr.unrealized(cs[-1].close)
    return st, n_long, n_short, p, acik_kar


for tf in ("4h", "1h", "15m"):
    cs = cl.fetch_klines(tf, 500)
    sig = sinyaller(cs, tf)
    dag = {}
    for s in sig:
        dag[s] = dag.get(s, 0) + 1
    print()
    print("=" * 92)
    print("%s  ·  500 mum  ·  sinyal dagilimi: %s" % (tf, dag))
    print("=" * 92)
    print("%-16s %6s %7s %9s %11s %11s  %s"
          % ("mod", "LONG#", "SHORT#", "komisyon", "net", "bakiye", "acik"))
    print("-" * 92)
    for ad, mod, s, bh in (("aralik (eski)", "range", None, 0),
                           ("signal_long", "signal_long", sig, 0),
                           ("aralik + sinyal cikis", "signal_exit", sig, 0),
                           ("signal_long b10", "signal_long", sig, 10)):
        st, nl, ns, p, ak = kosu(cs, tf, mod, s, bh)
        acik = "-"
        if p:
            acik = "%s @ %.2f  acik %+.2f" % (p.side, p.entry, ak)
        print("%-16s %6d %7d %9.2f %+11.2f %11.2f  %s"
              % (ad, nl, ns, st["commission"], st["profit"], st["equity"], acik))
    print("-" * 92)
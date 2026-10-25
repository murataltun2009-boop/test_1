# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, '.'); sys.path.insert(0, 'tools')
import config as cfg, research_ppt as base
from core.paper import PaperTrader
from collections import defaultdict

name, cdl, tf = next(iter(base.jobs()))
print('pencere:', name)
for (m, st, k) in [('signal', 0.005, 0), ('osc_only', 0.005, 0)]:
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=m, risk_pct=0.03)
    p.running = True; p.start_balance = 1000.0; p.balance = 1000.0
    p.fixed_stake = True; p.corr_on = True; p.corr_stop_down = st
    p.corr_pause_bars = k
    bt = p.backtest(cdl, tf)
    ts = p.trades
    print('', m, 'islem:', len(ts), 'net:', sum(t.net_pnl for t in ts))
    seb = defaultdict(lambda: [0, 0.0, 0.0])
    for t in ts:
        key = '.'.join(t.exit_reason.split()[:2])
        a = seb[key]; a[0] += 1; a[1] += t.net_pnl; a[2] += t.gross_pnl
    for key, (n, net, gro) in sorted(seb.items(), key=lambda kv: -kv[1][0])[:8]:
        print('    %-26s %4d islem | net %9.1f | brut %9.1f' % (key, n, net, gro))
    kotu = sorted(ts, key=lambda t: t.net_pnl)[:5]
    for t in kotu:
        print('    KOTU %s %.4f->%.4f net %+.1f | %s | %s'
              % (t.side, t.entry, t.exit, t.net_pnl,
                 t.exit_reason[:20], t.reason[:20]))

# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, '.'); sys.path.insert(0, 'tools')
import config as cfg, research_ppt as base
from core.paper import PaperTrader

name, cdl, tf = next(iter(base.jobs()))
print('pencere:', name)
for m in ['signal', 'ma_only']:
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=m, risk_pct=0.03)
    p.running = True; p.start_balance = 1000.0; p.balance = 1000.0
    p.corr_on = True; p.corr_pause_bars = 6
    bt = p.backtest(cdl, tf)
    ts = p.trades
    print('', m, 'islem:', len(ts))
    for t in ts[:8]:
        print('  %s %.4f->%.4f gross %+.2f fee %.2f+%.2f net %+.2f | %s | %s'
              % (t.side, t.entry, t.exit, t.gross_pnl, t.fee_open,
                 t.fee_close, t.net_pnl, t.exit_reason[:24], t.reason[:24]))
    L = [t for t in ts if t.side == 'LONG']; S = [t for t in ts if t.side == 'SHORT']
    for lab, g in (('LONG', L), ('SHORT', S)):
        if not g: continue
        win = [t for t in g if t.net_pnl >= 0]; los = [t for t in g if t.net_pnl < 0]
        print('  %s: %d | K %d ort %+.2f | Z %d ort %+.2f | toplam %+.1f'
              % (lab, len(g), len(win),
                 sum(t.net_pnl for t in win)/max(1,len(win)),
                 len(los), sum(t.net_pnl for t in los)/max(1,len(los)),
                 sum(t.net_pnl for t in g)))
    from collections import defaultdict
    seb = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    for t in ts:
        k = (t.side, t.exit_reason[:20])
        a = seb[k]; a[0] += 1; a[1] += t.net_pnl; a[2] += t.gross_pnl
        a[3] += t.fee_open + t.fee_close
    print('  cikis sebebleri (adet sirali):')
    for k, (n, net, gro, fee) in sorted(seb.items(), key=lambda kv: -kv[1][0])[:10]:
        print('    %6s %-22s %5d islem | net %9.1f; brut %9.1f; fee %8.1f'
              % (k[0], k[1], n, net, gro, fee))

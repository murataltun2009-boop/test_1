# -*- coding: utf-8 -*-
"""TIK2 stabilizasyon arastirmasi (2026-11-07).

Ham kural serisi -> aday filtreler -> PaperTrader.backtest ile net PnL.
Filtreler NEDENSELDIR: yalnizca o bar ve onceki barlara bakar.

Kullanim:
    python tools/research_tk2_stab.py ENAUSDT 1m 500
    python tools/research_tk2_stab.py ENAUSDT 1m 5000
    python tools/research_tk2_stab.py BTCUSDT 1m 20000
"""
import json
import os
import sys
import time

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np  # noqa: E402

from core import tk2_rules  # noqa: E402
from core.analysis import analyze  # noqa: E402
from core.paper import PaperTrader  # noqa: E402

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
         "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
HULL = tk2_rules.MA_GROUPS["HULL"][0]


class C:
    __slots__ = ("open_time", "open", "high", "low", "close", "volume",
                 "close_time", "closed")

    def __init__(self, t, o, h, l, c, v, ct):
        self.open_time = int(t)
        self.open = float(o)
        self.high = float(h)
        self.low = float(l)
        self.close = float(c)
        self.volume = float(v)
        self.close_time = int(ct)
        self.closed = True


def load(sym, tf, n):
    path = os.path.join("data", "research", f"{tf}_{sym}.json")
    d = json.load(open(path, encoding="utf-8"))
    t = list(d["t"])[-n:]
    o = list(d["o"])[-n:]
    h = list(d["h"])[-n:]
    l = list(d["l"])[-n:]
    c = list(d["c"])[-n:]
    v = list(d["v"])[-n:]
    step = TF_MS[tf]
    return [C(t[i], o[i], h[i], l[i], c[i], v[i], t[i] + step - 1)
            for i in range(len(t))]


def dir_of(x):
    return 1 if x == "AL" else (-1 if x == "SAT" else 0)


def lab_of(d):
    return "AL" if d > 0 else ("SAT" if d < 0 else "NÖTR")


def smooth_dirs(x, win):
    """Pencere ici cogunluk: |toplam| >= ceil(win/2) ise yon, degilse 0."""
    if win <= 1:
        return np.asarray(x, dtype=np.int8).copy()
    cs = np.concatenate([[0], np.cumsum(np.asarray(x, dtype=np.int32))])
    out = np.zeros(len(x), dtype=np.int8)
    need = win // 2 + 1
    for i in range(len(x)):
        a = max(0, i - win + 1)
        s = int(cs[i + 1] - cs[a])
        if s >= need:
            out[i] = 1
        elif s <= -need:
            out[i] = -1
    return out


def stabilize(raw, hull=None, vote=1, vote_min=0, confirm_entry=1,
              confirm_exit=1, confirm_flip=1, min_dwell=0,
              hull_veto=False, hull_entry_veto=False, hull_smooth=1,
              hull_entry_fast=False, hull_governor=False,
              hull_fast_exit=True):
    """Kural serisini gecmis barlara bakarak yumusatir (nedensel).

    vote          : son N barin yon toplami (0 = kapali)
    vote_min      : toplamin bu buyukluge ulasmasi gerekir (0=otomatik)
    confirm_entry : 0'dan yone gecis icin arka arkaya K bar
    confirm_exit  : yonden 0'a (notr) cikis icin K bar
    confirm_flip  : yonden ters yone gecis icin K bar
    min_dwell     : bir yonde en az K bar kal (erken cikis/flip engeli)
    hull_veto     : HULL yonune ters YENI sinyali notr yap
    hull_smooth   : HULL yonunu son K barlik cogunlukla yumusat
    hull_governor : HULL pozisyon yonundeyse cikis/flip icin K bar sabir;
                    HULL ters donduyse hizli cikis (hull_fast_exit)
    """
    d = np.asarray([dir_of(x) for x in raw], dtype=np.int8)
    n = len(d)
    if vote and vote > 1:
        need = vote_min or (vote // 2 + 1)
        cs = np.concatenate([[0], np.cumsum(d.astype(np.int32))])
        cand = np.zeros(n, dtype=np.int8)
        for i in range(n):
            a = max(0, i - vote + 1)
            s = int(cs[i + 1] - cs[a])
            if s >= need:
                cand[i] = 1
            elif s <= -need:
                cand[i] = -1
    else:
        cand = d.copy()

    hs = smooth_dirs(hull, hull_smooth) if hull is not None else None
    if hs is not None and hull_veto:
        for i in range(n):
            if cand[i] != 0 and hs[i] != 0 and cand[i] != hs[i]:
                cand[i] = 0

    out = np.zeros(n, dtype=np.int8)
    state = 0
    pending = 0
    pc = 0
    last_change = -10 ** 9
    for i in range(n):
        c = int(cand[i])
        if state == 0 and hs is not None and hull_entry_veto:
            # GIRIS kapisi: yalnizca pozisyon YOKKEN HULL'a ters yeni
            # yon engellenir. Acik pozisyonun cikisi HULL yuzunden
            # geciktirilmez (gereksiz round-trip / komisyon olmaz).
            if c != 0 and hs[i] != 0 and c != hs[i]:
                c = 0
        if c == state:
            pending = 0
            pc = 0
            out[i] = state
            continue
        if state != 0 and min_dwell > 0 and (i - last_change) < min_dwell:
            out[i] = state
            continue
        need = confirm_entry if state == 0 else (
            confirm_exit if c == 0 else confirm_flip)
        if state == 0 and hull_entry_fast and hs is not None and c != 0 \
                and hs[i] == c:
            # HULL yeni yonu dogruluyorsa giris icin ek onay bekleme.
            need = 1
        if state != 0 and hull_governor and hs is not None:
            if hs[i] == state:
                # HULL hala pozisyon yonunde: kisa karsi sinyali yut.
                need = max(need, confirm_exit if c == 0 else confirm_flip)
            elif hull_fast_exit:
                # HULL ters dondu: cikis/flip icin tek bar yeter.
                need = 1
        need = max(1, int(need))
        if c == pending:
            pc += 1
        else:
            pending = c
            pc = 1
        if pc >= need:
            state = c
            last_change = i
            pending = 0
            pc = 0
        out[i] = state
    return [lab_of(int(x)) for x in out]


def run_len(seq):
    if not seq:
        return 0.0, 0
    runs = 1
    flips = 0
    for a, b in zip(seq, seq[1:]):
        if a != b:
            runs += 1
            flips += 1
    return len(seq) / runs, flips


def bt(sym, tf, candles, sig):
    p = PaperTrader(sym)
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
    p.fixed_stake = True
    p._quiet = True
    t0 = time.monotonic()
    st = p.backtest(candles, tf, signals=sig)
    st["_ms"] = int((time.monotonic() - t0) * 1000)
    tr = list(p.trades)
    st["_long"] = sum(1 for x in tr if str(x.side).upper().startswith("LONG"))
    st["_short"] = len(tr) - st["_long"]
    wins = [x for x in tr if x.net_pnl >= 0]
    losses = [x for x in tr if x.net_pnl < 0]
    st["_avg_win"] = sum(x.net_pnl for x in wins) / max(1, len(wins))
    st["_avg_loss"] = sum(x.net_pnl for x in losses) / max(1, len(losses))
    gw = sum(x.net_pnl for x in wins)
    gl = -sum(x.net_pnl for x in losses)
    st["_pf"] = gw / gl if gl > 0 else 0.0
    cum = peak = dd = 0.0
    for x in tr:
        cum += x.net_pnl
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    st["_dd"] = dd
    st["_exp"] = st["profit"] / max(1, len(tr))
    return st


def main():
    sym, tf, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    candles = load(sym, tf, n)
    print(f"\n=== {sym} {tf} {len(candles)} bar  "
          f"({time.strftime('%Y-%m-%d %H:%M', time.localtime(candles[0].open_time/1000))}"
          f" -> {time.strftime('%Y-%m-%d %H:%M', time.localtime(candles[-1].open_time/1000))}) ===",
          flush=True)
    t0 = time.monotonic()
    res = analyze(
        symbol=sym, timeframe=tf,
        open_times=[c.open_time for c in candles],
        o=[c.open for c in candles], h=[c.high for c in candles],
        l=[c.low for c in candles], c=[c.close for c in candles],
        v=[c.volume for c in candles],
        close_times=[c.close_time for c in candles])
    raw = tk2_rules.series(res.osc_codes, res.ma_codes)
    hull = np.asarray(res.ma_codes[HULL])
    print(f"analyze {int((time.monotonic()-t0)*1000)} ms  "
          f"AL={raw.count('AL')} SAT={raw.count('SAT')} "
          f"NOTR={raw.count('NÖTR')}  hull+={int((hull>0).sum())} "
          f"hull-={int((hull<0).sum())}", flush=True)
    ar, af = run_len(raw)
    print(f"ham seri: ortalama kosu {ar:.2f} bar, gecis {af}", flush=True)

    variants = [
        ("ham (base)", {}),
        ("HULL veto", dict(hull_veto=True)),
        ("HULL veto s3", dict(hull_veto=True, hull_smooth=3)),
        ("HULL giris", dict(hull_entry_veto=True)),
        ("HULL giris s3", dict(hull_entry_veto=True, hull_smooth=3)),
        ("HULL giris s5", dict(hull_entry_veto=True, hull_smooth=5)),
        ("giris2", dict(confirm_entry=2)),
        ("giris3", dict(confirm_entry=3)),
        ("flip2", dict(confirm_flip=2)),
        ("flip3", dict(confirm_flip=3)),
        ("cikis2", dict(confirm_exit=2)),
        ("cikis3", dict(confirm_exit=3)),
        ("cikis2+flip2", dict(confirm_exit=2, confirm_flip=2)),
        ("cikis3+flip3", dict(confirm_exit=3, confirm_flip=3)),
        ("HULLg+flip2", dict(hull_entry_veto=True, confirm_flip=2)),
        ("HULLg+cikis2", dict(hull_entry_veto=True, confirm_exit=2)),
        ("HULLg+c2f2", dict(hull_entry_veto=True, confirm_exit=2,
                            confirm_flip=2)),
        ("HULLg+giris2", dict(hull_entry_veto=True, confirm_entry=2)),
        ("HULLg+c2f2+g2", dict(hull_entry_veto=True, confirm_entry=2,
                               confirm_exit=2, confirm_flip=2)),
        ("HULLg+oy3", dict(hull_entry_veto=True, vote=3)),
        ("HULLg+oy5", dict(hull_entry_veto=True, vote=5)),
        ("HULL vali", dict(hull_governor=True, confirm_exit=3,
                           confirm_flip=3)),
        ("HULL vali+veto", dict(hull_governor=True, hull_veto=True,
                                confirm_exit=3, confirm_flip=3)),
        ("HULLg+cikis2+oy3", dict(hull_entry_veto=True, confirm_exit=2,
                                  vote=3)),
    ]

    rows = []
    for name, kw in variants:
        sig = stabilize(raw, hull, **kw) if kw else raw
        sr, sf = run_len(sig)
        st = bt(sym, tf, candles, sig)
        rows.append((name, sr, sf, st))
        print(f"  {name:20s} run={sr:5.2f} gecis={sf:5d} "
              f"islem={st['trades']:4d} ({st['_long']}L/{st['_short']}S) "
              f"net={st['profit']:+8.2f}$ kom={st['commission']:7.2f} "
              f"kaz=%{100*st['wins']/max(1,st['trades']):3.0f} "
              f"PF={st['_pf']:4.2f} DD={st['_dd']:+7.2f} "
              f"ortK={st['_avg_win']:+6.2f} ortZ={st['_avg_loss']:+6.2f} "
              f"bt={st['_ms']}ms", flush=True)

    print("\nSIRALAMA (net):")
    for name, sr, sf, st in sorted(rows, key=lambda x: -x[3]["profit"]):
        print(f"  {st['profit']:+9.2f}$  {name:20s} islem={st['trades']:4d} "
              f"PF={st['_pf']:4.2f} DD={st['_dd']:+7.2f} "
              f"kom={st['commission']:7.2f} run={sr:.2f}")


if __name__ == "__main__":
    main()

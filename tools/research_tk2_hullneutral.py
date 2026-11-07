# -*- coding: utf-8 -*-
"""TIK2 HULL-notr davranisi olcumu (2026-11-07).

Kullanici kurali: HULL notr (0) iken pozisyonu kapatma; yukari yonlu ise
LONG, asagi yonlu ise SHORT'ta kal. Mevcut pozisyonlari koru.

Iki yorum olculur:
  freeze : HULL notrken ACIK pozisyonu dondur (kapatma).
  trend  : HULL notrken yonu HULL egimi (hma[i]-hma[i-n]) belirlesin.

Giris onayi (kullanici secimi): yeni giris icin 2 ardisik mum onayi;
cikis hizli (ilk ters/NOTR mumda kapat).

Kullanim:
    python tools/research_tk2_hullneutral.py
    python tools/research_tk2_hullneutral.py --ena
"""
import os
import sys
import time

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np  # noqa: E402

from core.analysis import analyze  # noqa: E402
from tools.research_tk2_stab import load  # noqa: E402
from tools.research_tk2_cross import bt  # noqa: E402

DATASETS = [
    ("ENAUSDT", "1m", 4000, 500),
    ("BTCUSDT", "1m", 4000, 500),
    ("ETHUSDT", "1m", 4000, 500),
    ("SOLUSDT", "1m", 4000, 500),
]


def _dir_of(x):
    return 1 if x == "AL" else (-1 if x == "SAT" else 0)


def _lab_of(d):
    return "AL" if d > 0 else ("SAT" if d < 0 else "NÖTR")


def _codes(sym, tf, candles):
    res = analyze(
        symbol=sym, timeframe=tf,
        open_times=[c.open_time for c in candles],
        o=[c.open for c in candles], h=[c.high for c in candles],
        l=[c.low for c in candles], c=[c.close for c in candles],
        v=[c.volume for c in candles],
        close_times=[c.close_time for c in candles])
    raw = [("AL" if v > 0 else ("SAT" if v < 0 else "NÖTR"))
           for v in _series_from_codes(res.osc_codes, res.ma_codes)]
    hull = [int(x) for x in res.ma_codes["Hull Hareketli Ortalama (9)"]]
    hma = np.asarray(res.ma_series["hma"], dtype=float)
    return raw, hull, hma


def _series_from_codes(osc_codes, ma_codes):
    from core import tk2_rules
    return [tk2_rules._dir_of(x) for x in tk2_rules.series(
        osc_codes, ma_codes)]


def hull_trend(hull, hma, slope_n=3):
    """HULL notrken yon: egim; egim yoksa son gecerli HULL yonu."""
    n = len(hull)
    out = [0] * n
    last = 0
    for i in range(n):
        if hull[i] != 0:
            out[i] = hull[i]
            last = hull[i]
            continue
        d = 0
        j = i - slope_n
        if j >= 0 and np.isfinite(hma[i]) and np.isfinite(hma[j]):
            diff = float(hma[i]) - float(hma[j])
            if diff > 0:
                d = 1
            elif diff < 0:
                d = -1
        if d == 0:
            d = last
        out[i] = d
        if d != 0:
            last = d
    return out


def stabilize_custom(raw, hull, hma, *, entry_confirm=1,
                     neutral_mode="freeze", slope_n=3):
    """Kural serisi + HULL notr davranisi + giris onayi.

    neutral_mode:
      "off"    : mevcut davranis (HULL notr = giris serbest)
      "freeze" : HULL notrken acik pozisyonu dondur
      "trend"  : HULL notrken yon = HULL egimi
    """
    dirs = [_dir_of(x) for x in raw]
    n = len(dirs)
    tr = hull_trend(hull, hma, slope_n=slope_n)
    out = []
    state = 0
    pending = 0
    pc = 0
    for i in range(n):
        c = dirs[i]
        notr = (hull[i] == 0)
        if notr and neutral_mode != "off":
            if state != 0:
                if neutral_mode == "freeze":
                    # Mevcut pozisyonu koru; kapatma.
                    pending = 0
                    pc = 0
                    out.append(state)
                    continue
                if neutral_mode == "trend_keep":
                    # SADECE egim pozisyon yonundeyse koru; tersse
                    # normal kural islesin (hizli cikis korunur).
                    if tr[i] == state:
                        pending = 0
                        pc = 0
                        out.append(state)
                        continue
                    # asagi dus: normal mantiga devam
                elif neutral_mode in ("tut0", "tut0+egim"):
                    # SADECE "sinyal notr oldugu icin kapanma"yi engelle.
                    # Aktif ters sinyalde hizli cikis korunur.
                    if c == 0:
                        if neutral_mode == "tut0" or tr[i] == state:
                            pending = 0
                            pc = 0
                            out.append(state)
                            continue
                    # c != 0 veya egim ters: normal mantiga devam
                elif tr[i] != 0 and tr[i] != state:
                    # trend: yon egimle hizalanir (donus varsa cevir)
                    state = tr[i]
                    pending = 0
                    pc = 0
                    out.append(state)
                    continue
                else:
                    out.append(state)
                    continue
            # flat: notr HULL'da yeni giris icin onay gerekir
            if neutral_mode == "trend" and tr[i] != 0:
                c = tr[i]
            elif neutral_mode in ("trend_keep", "tut0", "tut0+egim"):
                pass  # normal giris kurallari
            else:
                c = 0
        # GIRIS KAPISI: HULL notr DEGILKEN ters giris engellenir.
        if state == 0 and hull[i] != 0 and c != 0 and c != hull[i]:
            c = 0
        if state == 0:
            if c != 0:
                if c == pending:
                    pc += 1
                else:
                    pending = c
                    pc = 1
                if pc >= max(1, int(entry_confirm)):
                    state = c
                    pending = 0
                    pc = 0
            else:
                pending = 0
                pc = 0
            out.append(state)
        elif c == state:
            pending = 0
            pc = 0
            out.append(state)
        elif c == -state:
            # ilk ters mum: kapat (hizli cikis); yeni giris onayli
            state = 0
            if c == pending:
                pc += 1
            else:
                pending = c
                pc = 1
            if pc >= max(1, int(entry_confirm)):
                state = c
                pending = 0
                pc = 0
            out.append(state)
        else:
            # NOTR: kapat (hizli cikis)
            state = 0
            pending = 0
            pc = 0
            out.append(0)
    return [_lab_of(int(x)) for x in out]


VARIANTS = [
    ("ham", dict(__raw=True), 0),
    ("prod", dict(entry_confirm=1, neutral_mode="off"), 3),
    ("prod+freeze", dict(entry_confirm=1, neutral_mode="freeze"), 3),
    ("prod+trend", dict(entry_confirm=1, neutral_mode="trend"), 3),
    ("giris2", dict(entry_confirm=2, neutral_mode="off"), 3),
    ("giris2+freeze", dict(entry_confirm=2, neutral_mode="freeze"), 3),
    ("giris2+trend", dict(entry_confirm=2, neutral_mode="trend"), 3),
    ("giris2+freeze s5", dict(entry_confirm=2, neutral_mode="freeze",
                              slope_n=5), 3),
    ("giris2+trend s5", dict(entry_confirm=2, neutral_mode="trend",
                             slope_n=5), 3),
    ("prod+tut", dict(entry_confirm=1, neutral_mode="trend_keep"), 3),
    ("prod+tut s5", dict(entry_confirm=1, neutral_mode="trend_keep",
                         slope_n=5), 3),
    ("giris2+tut", dict(entry_confirm=2, neutral_mode="trend_keep"), 3),
    ("prod+tut0", dict(entry_confirm=1, neutral_mode="tut0"), 3),
    ("prod+tut0+egim", dict(entry_confirm=1,
                            neutral_mode="tut0+egim"), 3),
    ("prod+tut0+egim s5", dict(entry_confirm=1,
                               neutral_mode="tut0+egim", slope_n=5), 3),
]


def main():
    datasets = DATASETS
    if "--ena" in sys.argv:
        datasets = [("ENAUSDT", "1m", 500, 500),
                    ("ENAUSDT", "1m", 402, 402)]
    agg = {name: dict(net=0.0, trades=0, comm=0.0, dd=0.0, pos=0,
                      folds=0) for name, _, _ in VARIANTS}
    t_start = time.monotonic()
    for sym, tf, n, fold in datasets:
        candles = load(sym, tf, n)
        raw, hull, hma = _codes(sym, tf, candles)
        sigs = {}
        for name, kw, _mh in VARIANTS:
            kw2 = dict(kw)
            if kw2.pop("__raw", False):
                sigs[name] = raw
            else:
                sigs[name] = stabilize_custom(raw, hull, hma, **kw2)
        nf = len(candles) // fold
        print(f"\n--- {sym} {tf} {len(candles)} bar, {nf} x {fold} dilim ---",
              flush=True)
        for name, _kw, mh in VARIANTS:
            net = comm = 0.0
            trades = pos = 0
            dd = 0.0
            for f in range(nf):
                a, b = f * fold, (f + 1) * fold
                sl = slice(a, b)
                st = bt(sym, tf, candles[sl], sigs[name][sl], min_hold=mh)
                net += st["profit"]
                trades += st["trades"]
                comm += st["commission"]
                dd = min(dd, st["_dd"])
                pos += 1 if st["profit"] > 0 else 0
            a_ = agg[name]
            a_["net"] += net
            a_["trades"] += trades
            a_["comm"] += comm
            a_["dd"] = min(a_["dd"], dd)
            a_["pos"] += pos
            a_["folds"] += nf
            print(f"  {name:22s} net={net:+9.2f}$ poz={pos}/{nf} "
                  f"islem={trades:4d} kom={comm:7.2f} DD={dd:+8.2f}",
                  flush=True)

    print("\n" + "=" * 78)
    print("TOPLAM:")
    for name, a in sorted(agg.items(), key=lambda kv: -kv[1]["net"]):
        print(f"  {name:22s} net={a['net']:+10.2f}$ "
              f"poz={a['pos']}/{a['folds']} islem={a['trades']:5d} "
              f"kom={a['comm']:8.2f} DD={a['dd']:+9.2f}")
    print(f"\ntoplam sure {int(time.monotonic()-t_start)} s")


if __name__ == "__main__":
    main()

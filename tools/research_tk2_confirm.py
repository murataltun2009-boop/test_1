# -*- coding: utf-8 -*-
"""TIK2 4-mum / 2-ardisik onay olcumu (2026-11-07).

Kullanici kurali: tek mumda yon degismesin. Son 4 mumluk pencerede
Y Y Y R -> bekle; sonraki mum da R ise (Y Y R R) gec. Yani yeni yon
icin en az 2 ARDISIK mum onayi.

Bu betik HULL giris kapisi + minimum tutma uzerine onay varyantlarini
ayni 4 sembol x 8 x 500 bar 1m verisinde karsilastirir.

Kullanim:
    python tools/research_tk2_confirm.py
"""
import os
import sys
import time

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from core import tk2_rules  # noqa: E402
from tools.research_tk2_cross import analyze_codes, bt  # noqa: E402
from tools.research_tk2_stab import load, stabilize  # noqa: E402

DATASETS = [
    ("ENAUSDT", "1m", 4000, 500),
    ("BTCUSDT", "1m", 4000, 500),
    ("ETHUSDT", "1m", 4000, 500),
    ("SOLUSDT", "1m", 4000, 500),
]

VARIANTS = [
    # ad, stabilize kw, min_hold
    ("ham", {}, 0),
    ("prod (mevcut)", dict(hull_entry_veto=True), 3),
    ("hold4 (onaysiz)", dict(hull_entry_veto=True), 4),
    ("giris2 only", dict(hull_entry_veto=True, confirm_entry=2), 3),
    ("flip2 only", dict(hull_entry_veto=True, confirm_flip=2), 3),
    ("giris2+flip2", dict(hull_entry_veto=True, confirm_entry=2,
                          confirm_flip=2), 3),
    ("giris2+flip2 hold4", dict(hull_entry_veto=True, confirm_entry=2,
                                confirm_flip=2), 4),
    ("giris2+flip2+cikis2", dict(hull_entry_veto=True, confirm_entry=2,
                                 confirm_flip=2, confirm_exit=2), 3),
    ("win4 2of4 (son 4 mum)", dict(__win4=True), 3),
    ("win4 2of4 hold4", dict(__win4=True), 4),
    ("min_dwell4", dict(hull_entry_veto=True, min_dwell=4), 3),
    ("min_dwell4 hold4", dict(hull_entry_veto=True, min_dwell=4), 4),
    ("giris2+min_dwell4", dict(hull_entry_veto=True, confirm_entry=2,
                               min_dwell=4), 3),
    ("flip2+min_dwell4", dict(hull_entry_veto=True, confirm_flip=2,
                              min_dwell=4), 3),
    ("entry2 exit-fast", dict(__entry2=2), 3),
    ("entry3 exit-fast", dict(__entry2=3), 3),
    ("entry2 exit-fast hold4", dict(__entry2=2), 4),
    ("onay4 (giris/flip/cikis)", dict(hull_entry_veto=True,
                                      confirm_entry=4, confirm_flip=4,
                                      confirm_exit=4), 3),
]


def new_agg():
    return dict(net=0.0, gw=0.0, gl=0.0, trades=0, comm=0.0,
                dd=0.0, pos=0, folds=0, per=[])


def _dir_of(x):
    return 1 if x == "AL" else (-1 if x == "SAT" else 0)


def _lab_of(d):
    return "AL" if d > 0 else ("SAT" if d < 0 else "NÖTR")


def stabilize_win4(raw, hull, win=4, need=2, hull_entry_veto=True):
    """Son `win` mumda yeni yön en az `need` kez varsa geç.

    Kullanici kurali (2026-11-07): Y Y Y R -> geçme; sonraki de R ise
    (Y Y R R) -> geç. R R R G -> geçme; sonraki de G ise -> geç.
    NÖTR de ayni pencereyle degerlendirilir (2 NÖTR -> kapat).
    """
    dirs = [_dir_of(x) for x in raw]
    n = len(dirs)
    hs = [int(x) for x in hull] if hull is not None and len(hull) == n \
        else None
    out = []
    state = 0
    for i in range(n):
        d = dirs[i]
        # GIRIS KAPISI: pozisyon yokken HULL'a ters yeni yon acilmaz.
        if state == 0 and hull_entry_veto and hs is not None \
                and d != 0 and hs[i] != 0 and d != hs[i]:
            d = 0
        a = max(0, i - win + 1)
        pencere = dirs[a:i + 1]
        if d != 0 and pencere.count(d) >= need:
            state = d
        elif d == 0 and pencere.count(0) >= need:
            state = 0
        out.append(state)
    return [_lab_of(int(x)) for x in out]


def stabilize_entry2(raw, hull, need=2, hull_entry_veto=True):
    """Çıkış hızlı, yeni giriş 2 ardışık onaylı.

    Kullanici secimi (2026-11-07): "sadece girisi onayla".
      * Açık pozisyonda ilk ters mum: pozisyon KAPANIR (hızlı çıkış).
      * Ters yönde yeni pozisyon: ancak `need` ardışık mum sonra açılır.
      * Düz (flat) durumda giriş: `need` ardışık mum ister.
      * NÖTR: anında kapatır (çıkış hızlı).
    HULL giriş kapısı her yeni girişte uygulanır.
    """
    dirs = [_dir_of(x) for x in raw]
    n = len(dirs)
    hs = [int(x) for x in hull] if hull is not None and len(hull) == n \
        else None
    out = []
    state = 0
    pending = 0
    pc = 0
    for i in range(n):
        c = dirs[i]
        # GIRIS KAPISI: yeni giris HULL'a tersse engellenir.
        if c != 0 and hull_entry_veto and hs is not None \
                and hs[i] != 0 and c != hs[i]:
            c = 0
        if state == 0:
            if c != 0:
                if c == pending:
                    pc += 1
                else:
                    pending = c
                    pc = 1
                if pc >= need:
                    state = c
                    pending = 0
                    pc = 0
                    out.append(state)
                else:
                    out.append(0)
            else:
                pending = 0
                pc = 0
                out.append(0)
        elif c == state:
            pending = 0
            pc = 0
            out.append(state)
        elif c == -state:
            # Ilk ters mum: KAPAT (hizli cikis), ama yeni giris icin
            # onay sayacini tasi.
            out.append(0)
            state = 0
            if c == pending:
                pc += 1
            else:
                pending = c
                pc = 1
            if pc >= need:
                state = c
                pending = 0
                pc = 0
                out[-1] = state
        else:
            # NOTR: aninda kapat.
            state = 0
            pending = 0
            pc = 0
            out.append(0)
    return [_lab_of(int(x)) for x in out]


def main():
    datasets = DATASETS
    if "--ena" in sys.argv:
        datasets = [("ENAUSDT", "1m", 500, 500),
                    ("ENAUSDT", "1m", 402, 402)]
    agg = {name: new_agg() for name, _, _ in VARIANTS}
    t_start = time.monotonic()
    for sym, tf, n, fold in datasets:
        candles = load(sym, tf, n)
        raw, hull = analyze_codes(sym, tf, candles)
        sigs = {}
        for name, kw, _mh in VARIANTS:
            kw2 = dict(kw)
            if kw2.pop("__win4", False):
                sigs[name] = stabilize_win4(raw, hull)
            elif kw2.get("__entry2"):
                need = int(kw2["__entry2"])
                sigs[name] = stabilize_entry2(raw, hull, need=need)
            else:
                sigs[name] = (stabilize(raw, hull, **kw2) if kw2 else raw)
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
            a_["per"].append((sym, net, pos, nf, dd))
            print(f"  {name:28s} net={net:+9.2f}$ poz={pos}/{nf} "
                  f"islem={trades:4d} kom={comm:7.2f} DD={dd:+8.2f}",
                  flush=True)

    print("\n" + "=" * 78)
    print("TOPLAM:")
    rows = sorted(agg.items(), key=lambda kv: -kv[1]["net"])
    for name, a in rows:
        print(f"  {name:28s} net={a['net']:+10.2f}$ "
              f"poz={a['pos']}/{a['folds']} islem={a['trades']:5d} "
              f"kom={a['comm']:8.2f} DD={a['dd']:+9.2f}")
    print(f"\ntoplam sure {int(time.monotonic()-t_start)} s")


if __name__ == "__main__":
    main()

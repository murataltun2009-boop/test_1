# -*- coding: utf-8 -*-
"""ENA dilim bazli karsilastirma (prod vs HULL-notr tut0)."""
import os
import sys

ROOT = r"C:\Users\PC-ITENG\Documents\BTCUSDT_TA_Live"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import tools.research_tk2_hullneutral as h  # noqa: E402
from tools.research_tk2_cross import bt  # noqa: E402
from tools.research_tk2_stab import load  # noqa: E402

NAMES = ["prod", "prod+tut0", "prod+tut0+egim", "prod+freeze",
         "prod+trend"]
candles = load("ENAUSDT", "1m", 4000)
raw, hull, hma = h._codes("ENAUSDT", "1m", candles)
kw = {n: dict(k) for n, k, _m in h.VARIANTS}
sigs = {n: h.stabilize_custom(raw, hull, hma, **kw[n]) for n in NAMES}
print("dilim" + "".join(f"{n:>18s}" for n in NAMES))
tot = {n: 0.0 for n in NAMES}
for f in range(8):
    a, b = f * 500, (f + 1) * 500
    row = ""
    for n in NAMES:
        st = bt("ENAUSDT", "1m", candles[a:b], sigs[n][a:b], min_hold=3)
        tot[n] += st["profit"]
        row += f"{st['profit']:+18.2f}"
    print(f"{f + 1:5d}{row}")
print("TOPLAM" + "".join(f"{tot[n]:+18.2f}" for n in NAMES))

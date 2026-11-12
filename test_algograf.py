# -*- coding: utf-8 -*-
"""ALGO-GRAF — GRAFİK ÇİZGİ SIRALAMA testi (2026-11-13).

Kullanıcı kuralı (5 dk):
  * Çizgiler: MAVİ=EMA50, YEŞİL=VWMA20, TURUNCU=EMA20, PEMBE=HULL9,
    MOR=EMA200. SMA200 (gri) kurallarda KULLANILMAZ.
  * MAVİ üst + PEMBE alt -> SHORT aç/koru; PEMBE ayrılınca kapat.
  * PEMBE üst + MAVİ alt -> LONG aç/koru; YEŞİL>PEMBE olunca kapat.
  * YEŞİL üst + PEMBE alt -> NÖTR.
  * PEMBE->YEŞİL->TURUNCU->MAVİ -> LONG kapat.
  * PEMBE üst + YEŞİL alt -> NÖTR.
  * PEMBE üst + MAVİ alt iken MOR, YEŞİL/TURUNCU ile çakışırsa -> LONG kapat.
  * PEMBE->TURUNCU->YEŞİL->MOR->MAVİ -> SHORT aç; PEMBE yeşil/turuncunun
    altına inince kapat.
  * MAVİ MOR ile çakışıp altında kalırken PEMBE en alta -> SHORT kapat.
  * Kararsızlıkta NÖTR.
  * Varyantlar: algograf (iki yön), algograf_long (yalnız LONG),
    algograf_short (yalnız SHORT).

Çalıştırma:
    python test_algograf.py
"""
import os
import sys

sys.path.insert(0, ".")

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import numpy as np   # noqa: E402

from core import algograf   # noqa: E402
from core.paper import LONG, SHORT, PaperTrader   # noqa: E402

_GECEN = 0
_KALAN = 0


def kontrol(ad, kosul):
    global _GECEN, _KALAN
    if kosul:
        _GECEN += 1
        print("  GECTI ", ad)
    else:
        _KALAN += 1
        print("  KALDI ", ad)


def ma(rows):
    """(turuncu, mavi, mor, pembe, yesil) satirlarindan ma_series."""
    a = np.asarray(rows, dtype=float).T
    return {"ema20": a[0], "ema50": a[1], "ema200": a[2],
            "hma": a[3], "vwma": a[4], "sma200": a[4] * 1.1}


# Hazır dizilimler (fiyat ~100, tolerans %0,05 = 0.05):
R1 = (101.0, 104.0, 99.0, 98.0, 100.0)      # MAVI ust, PEMBE alt -> SHORT
R3 = (101.0, 97.0, 100.0, 104.0, 99.0)      # PEMBE ust, MAVI alt -> LONG
R5 = (100.0, 96.0, 98.0, 106.0, 103.0)      # PEMBE->YESIL->TURUNCU->MAVI
R8 = (103.0, 96.0, 98.0, 106.0, 100.0)      # PEMBE->TURUNCU->YESIL->MOR->MAVI


def C(t, close, open_):
    class _C:
        pass
    c = _C()
    c.closed = True
    c.open = open_
    c.open_time = t
    c.close = close
    c.high = max(open_, close) * 1.0001
    c.low = min(open_, close) * 0.9999
    c.volume = 1.0
    c.close_time = t + 59_999
    return c


def trader(mode="algograf"):
    p = PaperTrader("BTCUSDT")
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode)
    p.running = True
    p._quiet = True
    return p


# ==================================================================
print("1) Mod ailesi ve cizgi eslemesi")
s = algograf.summary()
kontrol("1.1 uc varyant", sorted(s["modes"]) == ["algograf", "algograf_long",
                                                "algograf_short"])
kontrol("1.2 MAVI=EMA50", algograf.LINE_KEYS["MAVİ"] == "ema50")
kontrol("1.3 YESIL=VWMA20", algograf.LINE_KEYS["YEŞİL"] == "vwma")
kontrol("1.4 TURUNCU=EMA20", algograf.LINE_KEYS["TURUNCU"] == "ema20")
kontrol("1.5 PEMBE=HULL9", algograf.LINE_KEYS["PEMBE"] == "hma")
kontrol("1.6 MOR=EMA200", algograf.LINE_KEYS["MOR"] == "ema200")
kontrol("1.7 SMA200 kurallarda yok",
        "sma200" not in algograf.LINE_KEYS.values())
kontrol("1.8 mod tanima", algograf.is_algograf_mode("algograf")
        and algograf.is_algograf_mode("algograf_long")
        and algograf.is_algograf_mode("algograf_short")
        and not algograf.is_algograf_mode("tk2"))
kontrol("1.9 yon eslemesi", algograf.side_for_mode("algograf_long") == 1
        and algograf.side_for_mode("algograf_short") == -1
        and algograf.side_for_mode("algograf") is None)

# ==================================================================
print("2) Kural 1/2: MAVI ust + PEMBE alt -> SHORT, PEMBE ayrilinca kapat")
seri = algograf.series(ma([R1, R1,
                           (101.0, 103.0, 99.0, 101.5, 100.0)]))
kontrol("2.1 giris SAT", seri[0] == "SAT")
kontrol("2.2 pozisyonda kal (SAT)", seri[1] == "SAT")
kontrol("2.3 PEMBE yesile degdi -> SAT-KAPAT", seri[2] == "SAT-KAPAT")

# PEMBE en alttan MOR yuzunden cikti (yesil/turuncu ustunde kalsa da)
seri = algograf.series(ma([R1,
                           (101.0, 104.0, 97.0, 98.0, 100.0)]))
kontrol("2.4 PEMBE en alttan cikti -> SAT-KAPAT", seri[1] == "SAT-KAPAT")

# ==================================================================
print("3) Kural 3: PEMBE ust + MAVI alt -> LONG, YESIL>PEMBE kapatir")
seri = algograf.series(ma([R3, R3,
                           (101.0, 97.0, 98.0, 104.0, 105.0)]))
kontrol("3.1 giris AL", seri[0] == "AL")
kontrol("3.2 pozisyonda kal (AL)", seri[1] == "AL")
kontrol("3.3 YESIL PEMBE ustune -> AL-KAPAT", seri[2] == "AL-KAPAT")

# ==================================================================
print("4) Notr dizilimler")
seri = algograf.series(ma([(100.0, 98.0, 99.0, 97.0, 102.0)]))
kontrol("4.1 YESIL ust + PEMBE alt -> NOTR", seri[0] == "NÖTR")
seri = algograf.series(ma([(100.0, 98.0, 99.0, 102.0, 97.0)]))
kontrol("4.2 PEMBE ust + YESIL alt -> NOTR", seri[0] == "NÖTR")

# ==================================================================
print("5) Kural 5: PEMBE->YESIL->TURUNCU->MAVI -> LONG kapat")
seri = algograf.series(ma([R3, R5]))
kontrol("5.1 once LONG", seri[0] == "AL")
kontrol("5.2 tam dizilim -> AL-KAPAT", seri[1] == "AL-KAPAT")

# ==================================================================
print("6) Kural 7: MOR yesil/turuncu ile cakisirsa LONG kapat")
seri = algograf.series(ma([R3,
                           (101.0, 97.0, 101.0, 104.0, 99.0)]))
kontrol("6.1 MOR ~ TURUNCU -> AL-KAPAT", seri[1] == "AL-KAPAT")
seri = algograf.series(ma([R3,
                           (101.0, 97.0, 99.02, 104.0, 99.0)]))
kontrol("6.2 MOR ~ YESIL (tolerans) -> AL-KAPAT", seri[1] == "AL-KAPAT")
seri = algograf.series(ma([R3,
                           (101.0, 97.0, 99.5, 104.0, 99.0)]))
kontrol("6.3 MOR uzak -> LONG devam", seri[1] == "AL")

# ==================================================================
print("7) Kural 8: PEMBE->TURUNCU->YESIL->MOR->MAVI -> SHORT")
seri = algograf.series(ma([(103.0, 96.0, 98.0, 106.0, 100.0),
                           (103.0, 96.0, 98.0, 99.0, 100.0)]))
kontrol("7.1 giris SAT", seri[0] == "SAT")
kontrol("7.2 PEMBE yesilin altina -> SAT-KAPAT", seri[1] == "SAT-KAPAT")

# ==================================================================
print("8) Kural 9: MAVI~MOR altinda + PEMBE en altta -> SHORT kapat")
# R8 short acar; sonra MAVI MOR'a yaklasir ve PEMBE en alta gecer.
seri = algograf.series(ma([(103.0, 96.0, 98.0, 106.0, 100.0),
                           (101.0, 97.99, 98.0, 95.0, 99.0)]))
kontrol("8.1 once SHORT", seri[0] == "SAT")
kontrol("8.2 R9 + PEMBE dip -> SAT-KAPAT", seri[1] == "SAT-KAPAT")

# ==================================================================
print("9) Varyantlar")
rows = [R1, (101.0, 103.0, 99.0, 101.5, 100.0), R3,
        (101.0, 97.0, 98.0, 104.0, 105.0), R8]
m = ma(rows)
kontrol("9.1 iki yon", algograf.series(m) ==
        ["SAT", "SAT-KAPAT", "AL", "AL-KAPAT", "SAT"])
kontrol("9.2 yalniz LONG: short yok",
        algograf.series(m, side=1) ==
        ["NÖTR", "NÖTR", "AL", "AL-KAPAT", "NÖTR"])
kontrol("9.3 yalniz SHORT: long yok",
        algograf.series(m, side=-1) ==
        ["SAT", "SAT-KAPAT", "NÖTR", "NÖTR", "NÖTR"])
# R8 dizilimi short-only'de ACILMAZ (yalniz kural 1).
m8 = ma([R8, R8])
kontrol("9.4 short-only yalniz kural 1",
        algograf.series(m8, side=-1) == ["NÖTR", "NÖTR"])
kontrol("9.5 long-only R8'i long saymaz",
        algograf.series(m8, side=1) == ["NÖTR", "NÖTR"])

# ==================================================================
print("10) Cakisma / kararsizlik")
# Tum cizgiler ayni seviyede: hicbir siralama kurulu degil -> NOTR.
kontrol("10.1 tam cakisma -> NOTR",
        algograf.series(ma([(100.0, 100.0, 100.0, 100.0, 100.0)
                            ])) == ["NÖTR"])
# MAVI ile TURUNCU cakisirsa "MAVI en ustte" siralama sayilmaz.
kontrol("10.2 mavi~turuncu R1'i bozar",
        algograf.series(ma([(104.0, 104.02, 99.0, 98.0, 100.0)]))[0]
        == "NÖTR")

# ==================================================================
print("11) Nedensellik (lookahead yok)")
rows = [R1, R1, (101.0, 103.0, 99.0, 101.5, 100.0), R3, R3,
        (101.0, 97.0, 98.0, 104.0, 105.0), R8]
tam = algograf.series(ma(rows))
ok = True
for k in range(1, len(rows) + 1):
    kesik = algograf.series(ma(rows[:k]))
    if kesik != tam[:k]:
        ok = False
        break
kontrol("11.1 her kesme ayni gecmisi verir", ok)

# Isinma / NaN -> NOTR, sonra normal.
nan = float("nan")
seri = algograf.series(ma([(nan, nan, nan, nan, nan), R1]))
kontrol("11.2 isinma NOTR", seri[0] == "NÖTR" and seri[1] == "SAT")

# ==================================================================
print("12) Paper motoru: ALGO-GRAF ac/kapa")
p = trader()
kontrol("12.1 baslangic duz", p.position is None)
p._algograf(100.0, "5m", "SAT")
kontrol("12.2 SAT -> SHORT", p.position is not None
        and p.position.side == SHORT)
p._algograf(100.0, "5m", "SAT")
kontrol("12.3 ayni etiket yeni islem acmaz", len(p.trades) == 0)
p._algograf(100.0, "5m", "SAT-KAPAT")
kontrol("12.4 SAT-KAPAT -> duz", p.position is None
        and len(p.trades) == 1)
p._algograf(100.0, "5m", "AL")
kontrol("12.5 AL -> LONG", p.position is not None
        and p.position.side == LONG)
p._algograf(100.0, "5m", "SAT-KAPAT")
kontrol("12.6 ters KAPAT yok sayilir", p.position is not None)
p._algograf(100.0, "5m", "AL-KAPAT")
kontrol("12.7 AL-KAPAT -> duz", p.position is None)
p._algograf(100.0, "5m", "AL")
p._algograf(100.0, "5m", "NÖTR")
kontrol("12.8 NOTR pozisyonu kapatir", p.position is None)
p._algograf(100.0, "5m", None)
kontrol("12.9 etiketsiz tick dokunmaz", p.position is None)

# ==================================================================
print("13) Paper: geriye donuk test modu tanir")
p = trader("algograf")
candles = [C(i * 300_000, 100.0 + 0.01 * i, 100.0 + 0.01 * i)
           for i in range(80)]
seri = p._build_signal_series(candles, "5m")
kontrol("13.1 seri uzunlugu", len(seri) == len(candles))
kontrol("13.2 etiketler gecerli",
        all(x in algograf.LABELS for x in seri))
st = p.backtest(candles, "5m")
kontrol("13.3 backtest calisti", st.get("mode") == "algograf"
        and st.get("bars") == len(candles))

# ==================================================================
print()
print(f"SONUC: {_GECEN} gecti, {_KALAN} kaldi")
if _KALAN:
    sys.exit(1)

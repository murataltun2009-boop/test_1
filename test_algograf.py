# -*- coding: utf-8 -*-
"""ALGO-GRAF — GRAFİK ÇİZGİ SIRALAMA testi (2026-11-13).

Kullanıcı kuralı (5 dk, 4 çizgi — EMA200/SMA200 grafikte yok):
  * Çizgiler: MAVİ=EMA50, YEŞİL=VWMA20, TURUNCU=EMA20, PEMBE=HULL9.
  * SHORT: MAVİ en üstte, PEMBE en altta (turuncu/yeşil arada) -> SHORT
    aç ve pozisyonda kal.
  * SHORT KAPAT: PEMBE, TURUNCU'nun veya YEŞİL'in altına inerse ya da
    onlarla çakışırsa kapat.
  * LONG: PEMBE en üstte, MAVİ en altta olduğu aralıkta LONG açık kalır.
  * LONG KAPAT: YEŞİL, PEMBE'nin üstüne çıkınca kapat.
  * NÖTR: YEŞİL en üstte, PEMBE en altta -> pozisyon NÖTR.
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
    """(turuncu, mavi, pembe, yesil) satirlarindan ma_series."""
    a = np.asarray(rows, dtype=float).T
    return {"ema20": a[0], "ema50": a[1], "hma": a[2], "vwma": a[3],
            # Kullanilmayan seriler: kural bunlari OKUMAMALI.
            "ema200": a[1] * 1.2, "sma200": a[1] * 1.3,
            "ichimoku": a[1] * 1.4}


# Hazır dizilimler (fiyat ~100, tolerans %0,05 = 0.05):
R1 = (101.0, 104.0, 98.0, 100.0)      # MAVI ust, PEMBE alt -> SHORT
R1B = (101.0, 103.0, 101.5, 100.0)    # PEMBE turuncunun ustune cikti -> kapat
R3 = (101.0, 97.0, 104.0, 99.0)       # PEMBE ust, MAVI alt -> LONG
R3B = (101.0, 97.0, 104.0, 105.0)     # YESIL PEMBE ustune -> kapat
RN = (100.0, 98.0, 97.0, 102.0)       # YESIL ust, PEMBE alt -> NOTR


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
kontrol("1.6 MOR (EMA200) kurallarda YOK",
        "MOR" not in algograf.LINE_KEYS)
kontrol("1.7 yalniz 4 cizgi", len(algograf.LINE_KEYS) == 4)
kontrol("1.8 EMA200/SMA200 okunmuyor",
        "ema200" not in algograf.LINE_KEYS.values()
        and "sma200" not in algograf.LINE_KEYS.values())
kontrol("1.9 mod tanima", algograf.is_algograf_mode("algograf")
        and algograf.is_algograf_mode("algograf_long")
        and algograf.is_algograf_mode("algograf_short")
        and not algograf.is_algograf_mode("tk2"))
kontrol("1.10 yon eslemesi", algograf.side_for_mode("algograf_long") == 1
        and algograf.side_for_mode("algograf_short") == -1
        and algograf.side_for_mode("algograf") is None)

# ==================================================================
print("2) SHORT: MAVI ust + PEMBE alt -> ac/koru; PEMBE ayrilinca kapat")
seri = algograf.series(ma([R1, R1, R1B]))
kontrol("2.1 giris SAT", seri[0] == "SAT")
kontrol("2.2 pozisyonda kal (SAT)", seri[1] == "SAT")
kontrol("2.3 PEMBE turuncunun ustune cikti -> SAT-KAPAT", seri[2] == "SAT-KAPAT")

# PEMBE yesil ile cakisirsa (yesilin biraz ustunde) da kapatir.
seri = algograf.series(ma([R1, (101.0, 104.0, 100.02, 100.0)]))
kontrol("2.4 PEMBE ~ YESIL (cakisma) -> SAT-KAPAT", seri[1] == "SAT-KAPAT")

# PEMBE en altta kaldikca tutmaya devam eder.
seri = algograf.series(ma([R1, (101.0, 104.0, 99.0, 100.0)]))
kontrol("2.5 PEMBE hala en altta -> SAT", seri[1] == "SAT")

# ==================================================================
print("3) LONG: PEMBE ust + MAVI alt; YESIL>PEMBE kapatir")
seri = algograf.series(ma([R3, R3, R3B]))
kontrol("3.1 giris AL", seri[0] == "AL")
kontrol("3.2 pozisyonda kal (AL)", seri[1] == "AL")
kontrol("3.3 YESIL PEMBE ustune -> AL-KAPAT", seri[2] == "AL-KAPAT")

# ==================================================================
print("4) Notr dizilimler")
seri = algograf.series(ma([RN]))
kontrol("4.1 YESIL ust + PEMBE alt -> NOTR", seri[0] == "NÖTR")
seri = algograf.series(ma([(98.0, 99.0, 101.0, 100.0)]))
kontrol("4.2 kararsiz dizilim -> NOTR", seri[0] == "NÖTR")

# ==================================================================
print("5) Acik pozisyonda notr dizilim kapatir")
seri = algograf.series(ma([R3, RN]))
kontrol("5.1 LONG iken NOTR -> AL-KAPAT", seri[1] == "AL-KAPAT")
seri = algograf.series(ma([R1, RN]))
kontrol("5.2 SHORT iken NOTR -> SAT-KAPAT", seri[1] == "SAT-KAPAT")

# ==================================================================
print("6) Karsilikli dizilimler")
seri = algograf.series(ma([R3, R1]))
kontrol("6.1 LONG iken SHORT dizilimi -> AL-KAPAT", seri[1] == "AL-KAPAT")
seri = algograf.series(ma([R1, R3]))
kontrol("6.2 SHORT iken LONG dizilimi -> SAT-KAPAT", seri[1] == "SAT-KAPAT")

# ==================================================================
print("7) Cakisma / tolerans")
# Tum cizgiler ayni seviyede: hicbir siralama kurulu degil -> NOTR.
kontrol("7.1 tam cakisma -> NOTR",
        algograf.series(ma([(100.0, 100.0, 100.0, 100.0)])) == ["NÖTR"])
# 2026-11-13 DUZELTME: varsayilan tolerans 0 (siki siralama). Kucuk fark
# da "en ustte" sayilir; aksi halde BTC 69k'da ~34$'lik olu bant LONG/SHORT
# girislerini tamamen engelliyordu.
kontrol("7.2 kucuk fark (0,02) da siralama sayilir -> SAT",
        algograf.series(ma([(104.0, 104.02, 98.0, 100.0)]))[0] == "SAT")
# Acikca tolerans verilirse eski olu bant davranisi korunur.
kontrol("7.3 tolerans %0,05 iken 0,02 fark cakisma sayilir",
        algograf.series(ma([(104.0, 104.02, 98.0, 100.0)]),
                        touch=0.0005)[0] == "NÖTR")
kontrol("7.4 0,10 fark siki modda siralama sayilir",
        algograf.series(ma([(104.0, 104.10, 98.0, 100.0)]))[0] == "SAT")
kontrol("7.5 tolerans %0,20 iken ayni fark cakisma sayilir",
        algograf.series(ma([(104.0, 104.10, 98.0, 100.0)]),
                        touch=0.002)[0] == "NÖTR")
# Canli BTC hatasi (2026-11-13 19:05): PEMBE>YESIL>TURUNCU>MAVI, MAVI ile
# TURUNCU arasi yalnizca ~8$ (0,0115%). Eski %0,05 bant bunu NÖTR yapiyordu;
# siki modda LONG acilmalidir.
kontrol("7.6 BTC 5m: dar MAVI-TURUNCU farki LONG acar",
        algograf.series(ma([(68870.05, 68862.10, 68976.09,
                             68925.32)])) == ["AL"])

# ==================================================================
print("8) Varyantlar")
rows = [R1, R1B, R3, R3B, RN]
m = ma(rows)
kontrol("8.1 iki yon", algograf.series(m) ==
        ["SAT", "SAT-KAPAT", "AL", "AL-KAPAT", "NÖTR"])
kontrol("8.2 yalniz LONG: short yok",
        algograf.series(m, side=1) ==
        ["NÖTR", "NÖTR", "AL", "AL-KAPAT", "NÖTR"])
kontrol("8.3 yalniz SHORT: long yok",
        algograf.series(m, side=-1) ==
        ["SAT", "SAT-KAPAT", "NÖTR", "NÖTR", "NÖTR"])
kontrol("8.4 long-only SHORT diziliminde giris yapmaz",
        algograf.series(ma([R1, R1]), side=1) == ["NÖTR", "NÖTR"])
kontrol("8.5 short-only LONG diziliminde giris yapmaz",
        algograf.series(ma([R3, R3]), side=-1) == ["NÖTR", "NÖTR"])

# ==================================================================
print("9) Nedensellik (lookahead yok)")
rows = [R1, R1, R1B, R3, R3, R3B, RN]
tam = algograf.series(ma(rows))
ok = True
for k in range(1, len(rows) + 1):
    kesik = algograf.series(ma(rows[:k]))
    if kesik != tam[:k]:
        ok = False
        break
kontrol("9.1 her kesme ayni gecmisi verir", ok)

# Isinma / NaN -> NOTR, sonra normal.
nan = float("nan")
seri = algograf.series(ma([(nan, nan, nan, nan), R1]))
kontrol("9.2 isinma NOTR", seri[0] == "NÖTR" and seri[1] == "SAT")

# Eksik seri -> bos liste (kural okunamaz).
kontrol("9.3 eksik ma_series -> bos", algograf.series({}) == [])

# ==================================================================
print("10) Paper motoru: ALGO-GRAF ac/kapa")
p = trader()
kontrol("10.1 baslangic duz", p.position is None)
p._algograf(100.0, "5m", "SAT")
kontrol("10.2 SAT -> SHORT", p.position is not None
        and p.position.side == SHORT)
p._algograf(100.0, "5m", "SAT")
kontrol("10.3 ayni etiket yeni islem acmaz", len(p.trades) == 0)
p._algograf(100.0, "5m", "SAT-KAPAT")
kontrol("10.4 SAT-KAPAT -> duz", p.position is None
        and len(p.trades) == 1)
p._algograf(100.0, "5m", "AL")
kontrol("10.5 AL -> LONG", p.position is not None
        and p.position.side == LONG)
p._algograf(100.0, "5m", "SAT-KAPAT")
kontrol("10.6 ters KAPAT yok sayilir", p.position is not None)
p._algograf(100.0, "5m", "AL-KAPAT")
kontrol("10.7 AL-KAPAT -> duz", p.position is None)
p._algograf(100.0, "5m", "AL")
p._algograf(100.0, "5m", "NÖTR")
kontrol("10.8 NOTR pozisyonu kapatir", p.position is None)
p._algograf(100.0, "5m", None)
kontrol("10.9 etiketsiz tick dokunmaz", p.position is None)

# ==================================================================
print("11) Paper: geriye donuk test modu tanir")
p = trader("algograf")
candles = [C(i * 300_000, 100.0 + 0.01 * i, 100.0 + 0.01 * i)
           for i in range(80)]
seri = p._build_signal_series(candles, "5m")
kontrol("11.1 seri uzunlugu", len(seri) == len(candles))
kontrol("11.2 etiketler gecerli",
        all(x in algograf.LABELS for x in seri))
st = p.backtest(candles, "5m")
kontrol("11.3 backtest calisti", st.get("mode") == "algograf"
        and st.get("bars") == len(candles))

# ==================================================================
print("12) Koruyucu stop + ayni yonde yeniden giris kilidi")
p = trader("algograf")
p.algo_sl = 0.01
p._algograf(100.0, "5m", "AL")
kontrol("12.1 LONG stop seviyesi %1 altta",
        p.position is not None and abs(p.position.stop_price - 99.0) < 1e-9)
p._algograf(99.5, "5m", "AL")
kontrol("12.2 stop'a degmeden pozisyon durur", p.position is not None)
p._algograf(99.5, "5m", "AL", 98.99, 100.0)
kontrol("12.3 bar dip stop'u vurdu -> kapandi", p.position is None
        and len(p.trades) == 1)
kontrol("12.4 stop cikisi stop fiyatindan",
        abs(p.trades[0].exit - 99.0) < 1e-9)
p._algograf(99.5, "5m", "AL")
kontrol("12.5 ayni yonde yeniden giris YOK (kilit)",
        p.position is None)
p._algograf(99.5, "5m", "NÖTR")
p._algograf(99.6, "5m", "AL")
kontrol("12.6 kural sifirlaninca yeniden giris var",
        p.position is not None and p.position.side == LONG)

# SHORT stop: giris 100 -> stop 101, anlik fiyat asarsa kapanir.
p = trader("algograf")
p.algo_sl = 0.01
p._algograf(100.0, "5m", "SAT")
kontrol("12.7 SHORT stop seviyesi %1 ustte",
        p.position is not None and abs(p.position.stop_price - 101.0) < 1e-9)
p._algograf(101.4, "5m", "SAT")
kontrol("12.8 fiyat stop'u gecti -> kapandi", p.position is None
        and len(p.trades) == 1)
kontrol("12.9 gap dolumu anlik fiyattan",
        abs(p.trades[0].exit - 101.4) < 1e-9)

# Stop kapali: kural disi cikis yok.
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(90.0, "5m", "AL")
kontrol("12.10 algo_sl=0 -> stop yok", p.position is not None)

# Stop seriye DEGIL yurutmeye ait; etiket serisi degismez.
p = trader("algograf")
p.algo_sl = 0.01
kontrol("12.11 seri uretimi stoptan etkilenmez",
        len(p._build_signal_series(candles, "5m")) == len(candles))

# ==================================================================
print("13) ALGO-GRAF kismi kar bankasi (10$ dilim, pozisyon devam)")
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
kontrol("13.1 pozisyon boyu 40 adet (4000$ / 100$)",
        p.position is not None and abs(p.position.qty - 40.0) < 1e-9)
kontrol("13.2 varsayilan banka esigi 10$",
        abs(p.algo_bank_usd - 10.0) < 1e-9 and
        abs(p.position.bank_next_usd - 10.0) < 1e-9)
p._algograf(100.2, "5m", "AL")
kontrol("13.3 esik altinda (8$) banka YOK", p.position is not None
        and abs(p.position.qty - 40.0) < 1e-9
        and p.banked_profit == 0.0)
bakiye0 = p.balance
p._algograf(100.3, "5m", "AL")
kontrol("13.4 kar 10$'i gecti -> dilim satildi, pozisyon ACIK",
        p.position is not None and p.position.qty < 40.0)
kontrol("13.5 banka 100,25$ seviyesinden (10$ nominal dilim)",
        abs((p.position.qty + 10.0 / 100.25) - 40.0) < 1e-9)
kontrol("13.6 kar cuzdana yazildi", p.balance > bakiye0
        and p.banked_profit > 0.0)
kontrol("13.7 giris ve stop DEGISMEDI",
        abs(p.position.entry - 100.0) < 1e-9)
kontrol("13.8 sonraki esik 20$", abs(p.position.bank_next_usd - 20.0) < 1e-9)
kontrol("13.9 tam kapanis gibi trade yazilmadi", len(p.trades) == 0)
p._algograf(100.6, "5m", "AL")
kontrol("13.10 her +10$ adiminda tekrar banka",
        abs(p.position.bank_next_usd - 30.0) < 1e-9)
kontrol("13.11 hacim elbette kuculmeye devam etti", p.position.qty < 39.9)

# Banka kapali: 0 -> hic dokunmaz.
p = trader("algograf")
p.algo_sl = 0.0
p.algo_bank_usd = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(110.0, "5m", "AL")
kontrol("13.12 algo_bank_usd=0 -> banka yok",
        p.position is not None and abs(p.position.qty - 40.0) < 1e-9
        and p.banked_profit == 0.0)

# SHORT yonunde de calisir.
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "SAT")
p._algograf(99.7, "5m", "SAT")
kontrol("13.13 SHORT'ta da dilim bankalanir",
        p.position is not None and p.position.side == SHORT
        and p.position.qty < 40.0 and p.banked_profit > 0.0)

# Geriye donuk testte bar ici zirve esigi tetikler.
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(100.1, "5m", "AL", 99.9, 100.4)
kontrol("13.14 bar ici zirve (100,4) esigi tetikledi",
        p.position is not None and p.position.qty < 40.0
        and abs(p.position.bank_next_usd - 20.0) < 1e-9)

# Maker komisyon: 10$ dilimde ~0,002$ (taker 0,005$ degil).
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
kom0 = p.commission_paid
p._algograf(100.3, "5m", "AL")
kontrol("13.15 banka dilimi maker komisyonlu",
        abs((p.commission_paid - kom0) - 10.0 * p.maker_rate) < 1e-9)

# Fiyat tek adimda cok sicrarsa 10/20/30$ dilimleri sirayla bankalanir.
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(100.9, "5m", "AL")
kontrol("13.16 sicrama -> uc dilim (esik 40$)",
        p.position is not None
        and abs(p.position.bank_next_usd - 40.0) < 1e-9)

# ==================================================================
print()
print(f"SONUC: {_GECEN} gecti, {_KALAN} kaldi")
if _KALAN:
    sys.exit(1)

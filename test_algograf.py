# -*- coding: utf-8 -*-
"""ALGO-GRAF — GRAFİK ÇİZGİ SIRALAMA testi (2026-11-13).

Kullanıcı kuralı (5 dk, 4 çizgi — EMA200/SMA200 grafikte yok):
  * Çizgiler: MAVİ=EMA50, YEŞİL=VWMA20, TURUNCU=EMA20, PEMBE=HULL9.
  * SHORT: MAVİ en üstte, PEMBE en altta (turuncu/yeşil arada) -> SHORT
    aç ve pozisyonda kal.
  * SHORT KAPAT (2026-11-15): iki kuraldan hangisi önce olursa kapat:
      1) SHORT dizilimi bozulursa (MAVİ en üst / PEMBE en alt /
         EMA20 > VWMA20 koşullarından biri biterse),
      2) HULL satırı AL DURUMUNDAYSA (fiyat HULL9 üstünde).
    HULL AL iken yeni SHORT açılmaz; NÖTR beklenir.
  * Yalnız SHORT (algograf_short, 2026-11-22): giriş için SHORT çizgi
    dizilimi VE HULL SAT (fiyat HULL9 altında) BİRLİKTE gerekir; HULL
    NÖTR veya AL iken yeni SHORT açılmaz. Dizilim bozulunca veya HULL AL
    olunca (bar kapanışı beklenmeden) kapanır. Net zarar
    `PAPER_ALGOGRAF_LOSS_USD` (varsayılan 10$) tutarına ulaşınca da
    kapanır (zarar freni).
  * LONG: PEMBE en üstte, MAVİ en altta olduğu aralıkta LONG açık kalır.
  * LONG KAPAT: YEŞİL, PEMBE'nin üstüne çıkınca kapat.
  * Yalnız LONG (algograf_long, giriş 2026-11-23): PEMBE/HULL9 diğer üç
    çizginin üstünde VE HULL AL birlikte gerekir (MAVİ'nin en altta
    olması beklenmez); HULL NÖTR veya SAT iken yeni LONG açılmaz.
    HULL & VWMA ikisi de AL ise YEŞİL > PEMBE kapatmaz (both-AL).
    YEŞİL > PEMBE (both-AL yokken) veya HULL SAT -> kapat; HULL SAT bar
    kapanışı beklenmeden canlı fiyatla yakalanır. Net zarar
    `PAPER_ALGOGRAF_LOSS_USD` tutarına ulaşınca da kapanır.
  * NÖTR: YEŞİL en üstte, PEMBE en altta -> pozisyon NÖTR.
  * Kararsızlıkta NÖTR.
  * Varyantlar: algograf (iki yön), algograf_long (yalnız LONG),
    algograf_short (yalnız SHORT).
  * Kâr bankası: açık kâr tutar eşiğine ulaşınca kâr cüzdana yazılır ve
    pozisyon AYNI yönde, AYNI ana para × kaldıraç notional ile yeniden
    açılır (pozisyon kaybolmaz, bileşik büyüme yok).

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
print("2) SHORT: MAVI ust + PEMBE alt -> ac/koru; dizilim bozulur veya HULL=AL kapatir")
seri = algograf.series(ma([R1, R1, R1B]))
kontrol("2.1 giris SAT", seri[0] == "SAT")
kontrol("2.2 pozisyonda kal (SAT)", seri[1] == "SAT")
# 2026-11-15: SHORT dizilimi bozulunca (PEMBE, TURUNCU'nun ustune cikti)
# SHORT kapanir.
kontrol("2.3 dizilim bozuldu (PEMBE>TURUNCU) -> SAT-KAPAT",
        seri[2] == "SAT-KAPAT")

# Kural 1a: TURUNCU (EMA20) YESIL'in (VWMA20) altina indi -> kapat.
seri = algograf.series(ma([R1, (99.0, 104.0, 98.0, 100.0)]))
kontrol("2.4 EMA20 < VWMA20 -> SAT-KAPAT", seri[1] == "SAT-KAPAT")

# Kural 1b: TURUNCU YESIL ile cakisiyor (esit) -> kapat.
seri = algograf.series(ma([R1, (100.0, 104.0, 98.0, 100.0)]))
kontrol("2.5 EMA20 ~ VWMA20 (cakisma) -> SAT-KAPAT",
        seri[1] == "SAT-KAPAT")

# TURUNCU YESIL'in ustunde kaldikca tutmaya devam eder.
seri = algograf.series(ma([R1, (100.5, 104.0, 98.0, 100.0)]))
kontrol("2.6 EMA20 > VWMA20 -> hala SAT", seri[1] == "SAT")

# Kural 2: HULL satiri AL DURUMUNDAYSA kapat (fiyat HULL9'un ustunde).
# R1'de PEMBE=98 -> esik 98*1,0002 = 98,0196. Bar0 fiyat 98,0 (HULL=SAT),
# bar1 fiyat 98,5 (HULL=AL) -> kapat.
m = ma([R1, R1])
seri = algograf.series(m, prices=[98.0, 98.5])
kontrol("2.7 HULL=AL durumu -> SAT-KAPAT", seri == ["SAT", "SAT-KAPAT"])

# HULL AL'de kaldikca SHORT kapali kalir (NOTR); HULL SAT'a donunce
# dizilim hala gecerliyse yeniden girer.
seri = algograf.series(ma([R1, R1, R1, R1]),
                       prices=[97.5, 98.5, 99.0, 97.5])
kontrol("2.8 HULL AL boyunca NOTR, SAT'a donunce yeniden SAT",
        seri == ["SAT", "SAT-KAPAT", "NÖTR", "SAT"])

# Giris aninda HULL zaten AL ise SHORT ACILMAZ (NOTR bekle).
seri = algograf.series(ma([R1, R1, R1]), prices=[100.0, 100.0, 100.0])
kontrol("2.8b giriste HULL=AL -> SHORT acilmaz (NOTR)",
        seri == ["NÖTR", "NÖTR", "NÖTR"])

# Giriş koşulu kapatma kuralıyla çelişmemeli: EMA20 ≤ VWMA20 iken
# SHORT AÇILMAZ (yoksa her bar aç-kapa döngüsü oluşuyordu).
kontrol("2.9 EMA20 <= VWMA20 iken giris yok (cakisma yok)",
        algograf.series(ma([(99.0, 104.0, 98.0, 100.0)])) == ["NÖTR"])
kontrol("2.10 EMA20 = VWMA20 iken giris yok",
        algograf.series(ma([(100.0, 104.0, 98.0, 100.0)])) == ["NÖTR"])

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
print("5) Acik pozisyonda notr dizilim")
seri = algograf.series(ma([R3, RN]))
kontrol("5.1 LONG iken NOTR -> AL-KAPAT", seri[1] == "AL-KAPAT")
# 2026-11-15: SHORT'ta NÖTR/LONG dizilimi de kapatir (dizilim bozuldu).
# RN'de MAVİ(98) en üstte değil -> çıkış.
seri = algograf.series(ma([R1, RN]))
kontrol("5.2 SHORT iken NÖTR dizilimi -> SAT-KAPAT", seri[1] == "SAT-KAPAT")

# ==================================================================
print("6) Karsilikli dizilimler")
seri = algograf.series(ma([R3, R1]))
kontrol("6.1 LONG iken SHORT dizilimi -> AL-KAPAT", seri[1] == "AL-KAPAT")
# 2026-11-15: SHORT iken LONG dizilimi de kapatir (dizilim bozuldu).
seri = algograf.series(ma([R1, R3]))
kontrol("6.2 SHORT iken LONG dizilimi -> SAT-KAPAT",
        seri[1] == "SAT-KAPAT")

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
# 2026-11-15 SHORT çıkışı: R1B'de PEMBE TURUNCU'nun üstüne çıktığı için
# dizilim bozulur ve SHORT kapanır (HULL AL durumu ayrıca kapatır).
kontrol("8.1 iki yon", algograf.series(m) ==
        ["SAT", "SAT-KAPAT", "AL", "AL-KAPAT", "NÖTR"])
kontrol("8.2 yalniz LONG: short yok",
        algograf.series(m, side=1,
                        prices=[97.0, 100.0, 104.5, 104.5, 100.0]) ==
        ["NÖTR", "NÖTR", "AL", "AL-KAPAT", "NÖTR"])
kontrol("8.3 yalniz SHORT: long yok",
        algograf.series(m, side=-1,
                        prices=[97.9, 100.0, 103.0, 104.0, 101.0]) ==
        ["SAT", "SAT-KAPAT", "NÖTR", "NÖTR", "NÖTR"])
kontrol("8.4 long-only SHORT diziliminde giris yapmaz",
        algograf.series(ma([R1, R1]), side=1) == ["NÖTR", "NÖTR"])
kontrol("8.5 short-only LONG diziliminde giris yapmaz",
        algograf.series(ma([R3, R3]), side=-1) == ["NÖTR", "NÖTR"])

# YALNIZ-LONG ek kurallar (2026-11-15, giriş 2026-11-23): PEMBE/HULL9
# diğer üç çizginin üstünde VE HULL AL birlikte gerekir (MAVİ'nin en altta
# olması beklenmez); HULL NÖTR/SAT girişi engeller; HULL SAT ayrıca
# kapatır; both-AL (HULL & VWMA) YEŞİL > PEMBE kapatmasını ezer.
# Dizilim LONG değil ama both-AL: TURUNCU=100, MAVİ=98, PEMBE=99,
# YEŞİL=100,5; fiyat 101 (HULL ve VWMA'nın üstünde). 2026-11-23: giriş
# için DİZİLİM de şart -> LONG açılmaz (NÖTR).
PB = (100.0, 98.0, 99.0, 100.5)
kontrol("8.6 both-AL (dizilim yok) -> LONG acmaz",
        algograf.series(ma([PB]), side=1, prices=[101.0]) == ["NÖTR"])
# Dizilim LONG ama HULL NÖTR (fiyat = PEMBE): giriş yok.
kontrol("8.6b dizilim LONG + HULL NOTR -> giris yok",
        algograf.series(ma([R3]), side=1, prices=[104.0]) == ["NÖTR"])
kontrol("8.7 yalniz HULL=AL (VWMA SAT) -> giris yok",
        algograf.series(ma([(100.0, 98.0, 99.0, 101.5)]), side=1,
                        prices=[101.0]) == ["NÖTR"])
kontrol("8.8 both-AL varken YESIL>PEMBE kapatmaz",
        algograf.series(ma([R3, R3B]), side=1,
                        prices=[105.0, 106.0]) == ["AL", "AL"])
kontrol("8.9 YESIL>PEMBE + both-AL yok -> AL-KAPAT",
        algograf.series(ma([R3, R3B]), side=1,
                        prices=[105.0, 104.5]) == ["AL", "AL-KAPAT"])
kontrol("8.10 HULL SAT -> AL-KAPAT",
        algograf.series(ma([R3, R3]), side=1,
                        prices=[105.0, 100.0]) == ["AL", "AL-KAPAT"])
kontrol("8.11 HULL SAT iken giris yok",
        algograf.series(ma([R3]), side=1, prices=[100.0]) == ["NÖTR"])
kontrol("8.12 HULL olu bandi (NOTR) giris engeller",
        algograf.series(ma([R3]), side=1, prices=[103.99]) == ["NÖTR"])
kontrol("8.12b HULL olu bandin ustu (AL) -> AL",
        algograf.series(ma([R3]), side=1, prices=[104.03]) == ["AL"])
kontrol("8.13 SHORT dizilimi + both-AL LONG'u kapatmaz",
        algograf.series(ma([R3, R1]), side=1,
                        prices=[105.0, 102.0]) == ["AL", "AL"])
kontrol("8.14 iki yon modu degismedi (both-AL kapati degistirmez)",
        algograf.series(ma([R3, R3B]), prices=[105.0, 106.0]) ==
        ["AL", "AL-KAPAT"])

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
print("13) ALGO-GRAF kâr bankası (kâr cüzdana + AYNI ana para x kaldıraç)")
# --- 13A: bankadan sonra pozisyon AYNI notional ile devam eder -----
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
kontrol("13.1 pozisyon boyu 40 adet (4000$ / 100$)",
        p.position is not None and abs(p.position.qty - 40.0) < 1e-9)
kontrol("13.2 varsayilan banka tutari 10$ ve ilk esik 10$",
        abs(p.algo_bank_usd - 10.0) < 1e-9 and
        abs(p.position.bank_next_usd - 10.0) < 1e-9)
p._algograf(100.2, "5m", "AL")
kontrol("13.3 esik altinda (8$ kar) banka YOK", p.position is not None
        and abs(p.position.qty - 40.0) < 1e-9
        and p.banked_profit == 0.0)
bakiye0 = p.balance
# 100,75 -> kar 30$ (>=10$): pozisyon kapanir, kar cüzdana yazilir ve
# AYNI 4000$ (= ana para x kaldıraç) notional ile yeniden girilir.
p._algograf(100.75, "5m", "AL")
kontrol("13.4 banka sonrasi pozisyon ACIK (kaybolmaz)",
        p.position is not None and p.position.side == LONG)
kontrol("13.5 yeniden giris AYNI notional (ana para x kaldıraç)",
        abs(p.position.notional - 4000.0) < 1e-6
        and abs(p.position.eff_leverage - 10.0) < 1e-9)
kontrol("13.6 adet = 4000$ / 100,75$ (pozisyon kuculmez)",
        abs(p.position.qty - 4000.0 / 100.75) < 1e-6)
kontrol("13.7 kar cüzdana yazildi (net ~28,39$)",
        p.balance > bakiye0 and abs(p.banked_profit - 28.394) < 1e-6)
kontrol("13.8 yeni giris banka dolum fiyatindan (100,75)",
        abs(p.position.entry - 100.75) < 1e-9)
kontrol("13.9 esik taze 10$ kar (bank_next_usd = 10)",
        abs(p.position.bank_next_usd - 10.0) < 1e-9)
kontrol("13.10 banka kapanisi islem kaydina yazildi",
        len(p.trades) == 1
        and "kâr bankası" in p.trades[0].exit_reason)
p._algograf(100.75, "5m", "AL")
kontrol("13.11 ayni fiyatta tekrar banka YOK",
        abs(p.position.qty - 4000.0 / 100.75) < 1e-6)
p._algograf(101.125, "5m", "AL")
kontrol("13.12 taze +10$ karda tekrar banka + yeniden giris",
        len(p.trades) == 2 and abs(p.position.entry - 101.125) < 1e-9)
kontrol("13.13 ikinci banka da cüzdana yazildi", p.banked_profit > 41.0)

# --- 13B: kar TAM esige esitse yine banka + yeniden giris ----------
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(100.25, "5m", "AL")
kontrol("13.14 kar tam 10$ -> banka + yeni giris (pozisyon ACIK)",
        p.position is not None and len(p.trades) == 1
        and abs(p.trades[0].exit - 100.25) < 1e-9
        and abs(p.position.entry - 100.25) < 1e-9)
kontrol("13.15 net banka kari (komisyon dusulmus) pozitif",
        abs(p.banked_profit - 8.398) < 1e-6)

# --- 13C: 0 = kapali ----------------------------------------------
p = trader("algograf")
p.algo_sl = 0.0
p.algo_bank_usd = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(110.0, "5m", "AL")
kontrol("13.16 algo_bank_usd=0 -> banka yok",
        p.position is not None and abs(p.position.qty - 40.0) < 1e-9
        and p.banked_profit == 0.0)

# --- 13D: SHORT yonunde de calisir --------------------------------
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "SAT")
p._algograf(99.25, "5m", "SAT")
kontrol("13.17 SHORT'ta banka + ayni notional ile devam",
        p.position is not None and p.position.side == SHORT
        and abs(p.position.notional - 4000.0) < 1e-6
        and abs(p.position.qty - 4000.0 / 99.25) < 1e-6
        and p.banked_profit > 0.0)

# --- 13E: bar ici zirve tetikler, seviyeden (kotu olmayan) dolar ---
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(100.1, "5m", "AL", 99.9, 100.4)
kontrol("13.18 bar ici zirve esigi tetikledi, seviyeden doldu",
        len(p.trades) == 1 and abs(p.trades[0].exit - 100.25) < 1e-9
        and p.position is not None
        and abs(p.position.entry - 100.25) < 1e-9)

# --- 13F: maker komisyon (kapanis + yeni giris) -------------------
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
kom0 = p.commission_paid
p._algograf(100.75, "5m", "AL")
beklenen = 40.0 * 100.75 * p.maker_rate + 4000.0 * p.maker_rate
kontrol("13.19 banka kapanisi + yeni giris maker komisyonlu",
        abs((p.commission_paid - kom0) - beklenen) < 1e-9)

# --- 13G: Uygula -> acik pozisyona ANINDA yeni tutar --------------
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(100.1, "5m", "AL")
kontrol("13.20 4$ karda banka yok (esik 10$)",
        abs(p.position.qty - 40.0) < 1e-9 and p.banked_profit == 0.0)
p.configure(algo_bank_usd=2.0)
kontrol("13.21 tutar degisti -> esik sifirlandi (aninda uygula)",
        abs(p.algo_bank_usd - 2.0) < 1e-9
        and p.position.bank_next_usd == 0.0)
p._algograf(100.1, "5m", "AL")
kontrol("13.22 yeni tutar acik pozisyona hemen uygulandi (banka + giris)",
        abs(p.position.entry - 100.1) < 1e-9
        and abs(p.position.notional - 4000.0) < 1e-6
        and p.banked_profit > 0.0)

p.configure(algo_bank_usd=0.0)
kontrol("13.23 0 yapilinca esik kapanir",
        p.algo_bank_usd == 0.0 and p.position.bank_next_usd == 0.0)
qty0 = p.position.qty
p._algograf(120.0, "5m", "AL")
kontrol("13.24 0 iken acik pozisyon bankalanmaz",
        abs(p.position.qty - qty0) < 1e-9)

# Ayni tutar tekrar gonderilirse esik BOZULMAZ (spurious sifirlama yok).
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(100.75, "5m", "AL")
esik0 = p.position.bank_next_usd
p.configure(algo_bank_usd=10.0)
kontrol("13.25 ayni tutar -> esik korunur",
        abs(p.position.bank_next_usd - esik0) < 1e-9)

# --- 13H: koruyucu stop mesafesi bankadan sonra KORUNUR -----------
p = trader("algograf")
p.algo_sl = 0.01
p._algograf(100.0, "5m", "AL")
kontrol("13.26 acilis stopu %1 altta",
        abs(p.position.stop_price - 99.0) < 1e-9)
p._algograf(100.5, "5m", "AL")
kontrol("13.27 banka sonrasi stop mesafesi korunur (%1)",
        p.position is not None
        and abs(p.position.stop_price - 100.5 * 0.99) < 1e-9)

# --- 13I: banka islemleri ARAYUZ LOGUNA da yazilir ----------------
p = trader("algograf")
p.algo_sl = 0.0
olaylar = []
p._quiet = False                 # testte log kapali; burada acalim
p._on_event = lambda kind, msg: olaylar.append((kind, msg))
p._algograf(100.0, "5m", "AL")
p._algograf(100.75, "5m", "AL")
metin = " | ".join(m for _k, m in olaylar)
kontrol("13.28 banka kapanisi logda",
        "kâr bankası" in metin and "cüzdana" in metin)
kontrol("13.29 yeniden giris logda",
        "yeniden giriş" in metin and "ana para" in metin)
kontrol("13.30 banka ozeti logda",
        "kâr bankalandı" in metin and "notional ile devam" in metin)
kontrol("13.31 log olaylari 'trade' tipinde",
        any(k == "trade" for k, _m in olaylar))


# ==================================================================
print("14) Yalniz SHORT: (dizilim VE HULL SAT) girisi, HULL AL aninda kapanma, zarar freni")
# 2026-11-22 kullanici kurali (yalniz algograf_short):
#   * Giris: SHORT cizgi dizilimi VE HULL "SAT" (fiyat HULL9 altinda)
#     BIRLIKTE gerekir.
#   * HULL "NOTR" (olu bant) veya "AL" iken yeni SHORT ACILMAZ.
#   * Kapat: dizilim bozulursa VEYA HULL "AL" ise (2026-11-15 kurali).
#   * Acik SHORT, canli fiyat HULL9 ustune ciktigi ANDA (bar kapanisi
#     beklenmeden) kapanir.
#   * Zarar freni: net zarar `algo_loss_usd` tutarina ulasinca kapanir.

# --- 14A: seri kurallari ------------------------------------------
NB = (100.0, 99.0, 100.0, 101.0)     # dizilim SHORT degil
kontrol("14.1 HULL SAT tek basina -> giris yok",
        algograf.series(ma([NB]), side=-1, prices=[99.9]) == ["NÖTR"])
kontrol("14.2 HULL AL tek basina -> giris yok",
        algograf.series(ma([NB]), side=-1, prices=[100.5]) == ["NÖTR"])
kontrol("14.3 dizilim SAT + HULL SAT -> SAT",
        algograf.series(ma([R1]), side=-1, prices=[97.9]) == ["SAT"])
kontrol("14.4 dizilim SAT + HULL NOTR -> giris yok",
        algograf.series(ma([R1]), side=-1, prices=[98.0]) == ["NÖTR"])
kontrol("14.5 dizilim SAT + HULL AL -> giris yok",
        algograf.series(ma([R1]), side=-1, prices=[98.5]) == ["NÖTR"])
# Acik SHORT: dizilim bozulunca kapanir (HULL SAT olsa bile).
kontrol("14.6 dizilim bozulunca SAT-KAPAT",
        algograf.series(ma([R1, NB]), side=-1,
                        prices=[97.9, 97.9]) == ["SAT", "SAT-KAPAT"])
# Acik SHORT: HULL AL -> kapanir.
kontrol("14.7 HULL AL -> SAT-KAPAT",
        algograf.series(ma([R1, R1]), side=-1,
                        prices=[97.9, 98.5]) == ["SAT", "SAT-KAPAT"])
# Acik SHORT: HULL NOTR olsa da dizilim surdukce tutulur.
kontrol("14.8 dizilim surerken HULL NOTR -> SAT kalir",
        algograf.series(ma([R1, R1]), side=-1,
                        prices=[97.9, 98.0]) == ["SAT", "SAT"])
# Iki yonlu mod bu giris kuralini ALMAZ (kapsam yalniz SHORT).
kontrol("14.9 iki yonlu modda HULL SAT tek basina giris degil",
        algograf.series(ma([NB]), prices=[99.9]) == ["NÖTR"])
kontrol("14.10 iki yonlu modda dizilim SAT (HULL NOTR) -> SAT",
        algograf.series(ma([R1]), prices=[98.0]) == ["SAT"])

# --- 14B: paper motoru, giris kapisi + HULL AL aninda kapanma ------
p = trader("algograf_short")
p.algo_sl = 0.0
# Canli fiyat HULL9'un altinda (SAT) -> giris.
p._algograf(100.0, "5m", "SAT", hull_ma=101.0)
kontrol("14.11 yalniz SHORT'ta HULL SAT ile SHORT acildi",
        p.position is not None and p.position.side == SHORT)

# Canli fiyat HULL9'un olu bandinda (NOTR) -> giris yok.
p = trader("algograf_short")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "SAT", hull_ma=100.0)
kontrol("14.12 HULL NOTR iken SHORT acilmaz", p.position is None)
# Canli fiyat HULL9'un ustunde (AL) -> giris yok.
p._algograf(100.0, "5m", "SAT", hull_ma=99.0)
kontrol("14.13 HULL AL iken SHORT acilmaz", p.position is None)

# Bar ici HULL AL -> acik SHORT aninda kapanir.
p = trader("algograf_short")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "SAT", hull_ma=101.0)
p._algograf(101.0, "5m", "SAT", hull_ma=100.0)
kontrol("14.14 HULL AL (bar ici) -> SHORT kapandi",
        p.position is None and len(p.trades) == 1)
kontrol("14.15 kapanis nedeni HULL AL",
        "HULL AL" in p.trades[0].exit_reason)
# HULL AL iken ayni tick'te yeniden giris yok.
p._algograf(101.0, "5m", "SAT", hull_ma=100.0)
kontrol("14.16 HULL AL sonrasi ayni yonde giris yok",
        p.position is None)
# Fiyat HULL9 altina donunce (HULL SAT) yeniden SHORT acilir.
p._algograf(99.0, "5m", "SAT", hull_ma=100.0)
kontrol("14.17 HULL SAT'a donunce yeniden SHORT",
        p.position is not None and p.position.side == SHORT)

# Iki yonlu modda bu bar ici kapanma UYGULANMAZ.
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "SAT")
p._algograf(101.0, "5m", "SAT", hull_ma=100.0)
kontrol("14.18 iki yonlu modda bar ici HULL kapatmasi yok",
        p.position is not None)

# --- 14C: zarar freni ---------------------------------------------
p = trader("algograf_short")
p.algo_sl = 0.0
kontrol("14.19 varsayilan zarar freni 10$",
        abs(p.algo_loss_usd - 10.0) < 1e-9)
p._algograf(100.0, "5m", "SAT", hull_ma=101.0)
p._algograf(100.1, "5m", "SAT", hull_ma=101.0)
kontrol("14.20 esik altinda (net ~2$) kapatmaz",
        p.position is not None)
# Maker komisyonla NET ~10,4$ -> esik asilir.
p._algograf(100.3, "5m", "SAT", hull_ma=101.0)
kontrol("14.21 esikte (net ~10,4$) kapatir",
        p.position is None and len(p.trades) == 1)
kontrol("14.22 kapanis nedeni zarar freni",
        "zarar freni" in p.trades[0].exit_reason)

# Tutar degisince ANINDA uygulanir.
p = trader("algograf_short")
p.configure(algo_loss_usd=50.0)
p.algo_sl = 0.0
kontrol("14.23 configure tutari hemen uygular",
        abs(p.algo_loss_usd - 50.0) < 1e-9)
p._algograf(100.0, "5m", "SAT", hull_ma=101.0)
p._algograf(100.2, "5m", "SAT", hull_ma=101.0)
kontrol("14.24 50$ esik altinda kapatmaz", p.position is not None)
p.configure(algo_loss_usd=10.0)
p._algograf(100.3, "5m", "SAT", hull_ma=101.0)
kontrol("14.25 10$'a inince aninda kapatir", p.position is None)

# 0 = kapali (HULL AL kapanisi da tetiklenmesin diye HULL uzakta).
p = trader("algograf_short")
p.configure(algo_loss_usd=0.0)
p.algo_sl = 0.0
p._algograf(100.0, "5m", "SAT", hull_ma=130.0)
kontrol("14.26 HULL SAT ile SHORT acildi", p.position is not None)
p._algograf(120.0, "5m", "SAT", hull_ma=130.0)
kontrol("14.27 0 -> zarar freni kapali", p.position is not None)

# Kapsam: iki yonlu modda zarar freni calismaz.
p = trader("algograf")
p.configure(algo_loss_usd=10.0)
p.algo_sl = 0.0
p._algograf(100.0, "5m", "SAT")
p._algograf(120.0, "5m", "SAT")
kontrol("14.28 iki yonlu modda zarar freni yok", p.position is not None)

# Durum ozeti tutari tasir.
p = trader("algograf_short")
kontrol("14.29 state algo_loss_usd tasir",
        abs(p.state(100.0)["algo_loss_usd"] - 10.0) < 1e-9)

# Arayuz logu.
p = trader("algograf_short")
p.algo_sl = 0.0
olaylar = []
p._quiet = False
p._on_event = lambda kind, msg: olaylar.append((kind, msg))
p._algograf(100.0, "5m", "SAT", hull_ma=101.0)
p._algograf(100.3, "5m", "SAT", hull_ma=101.0)
metin = " | ".join(m for _k, m in olaylar)
kontrol("14.30 zarar freni logda",
        "zarar freni" in metin and "kapandı" in metin)
kontrol("14.31 log olayi 'trade' tipinde",
        any(k == "trade" for k, _m in olaylar))


# ==================================================================
print("15) Yalniz LONG: (dizilim VE HULL AL) girisi, HULL SAT aninda kapanma, zarar freni")
# 2026-11-23 kullanici kurali (yalniz algograf_long):
#   * Giris: PEMBE ust + MAVI alt dizilimi VE HULL "AL" birlikte gerekir.
#   * HULL "NOTR" veya "SAT" iken yeni LONG ACILMAZ.
#   * Kapat: YESIL>PEMBE (both-AL degilken) VEYA HULL "SAT".
#   * Acik LONG, canli fiyat HULL9 altina indigi ANDA (bar kapanisi
#     beklenmeden) kapanir.
#   * Zarar freni: net zarar `algo_loss_usd` tutarina ulasinca kapanir.

# --- 15A: seri kurallari ------------------------------------------
kontrol("15.1 dizilim LONG + HULL AL -> AL",
        algograf.series(ma([R3]), side=1, prices=[105.0]) == ["AL"])
# PEMBE tum cizgilerin ustunde; MAVI en altta DEGIL -> yine AL.
kontrol("15.1b PEMBE tum cizgilerin ustunde (MAVI altta degil) -> AL",
        algograf.series(ma([(101.0, 100.0, 104.0, 99.0)]), side=1,
                        prices=[105.0]) == ["AL"])
kontrol("15.2 dizilim LONG + HULL NOTR -> giris yok",
        algograf.series(ma([R3]), side=1, prices=[104.0]) == ["NÖTR"])
kontrol("15.3 dizilim LONG + HULL SAT -> giris yok",
        algograf.series(ma([R3]), side=1, prices=[100.0]) == ["NÖTR"])
kontrol("15.4 HULL SAT -> AL-KAPAT",
        algograf.series(ma([R3, R3]), side=1,
                        prices=[105.0, 100.0]) == ["AL", "AL-KAPAT"])
kontrol("15.5 YESIL>PEMBE + both-AL -> AL kalir",
        algograf.series(ma([R3, R3B]), side=1,
                        prices=[105.0, 106.0]) == ["AL", "AL"])
kontrol("15.6 YESIL>PEMBE + both-AL yok -> AL-KAPAT",
        algograf.series(ma([R3, R3B]), side=1,
                        prices=[105.0, 104.5]) == ["AL", "AL-KAPAT"])

# --- 15B: paper motoru, giris kapisi + HULL SAT aninda kapanma -----
p = trader("algograf_long")
p.algo_sl = 0.0
# Canli fiyat HULL9'un ustunde (AL) -> giris.
p._algograf(100.0, "5m", "AL", hull_ma=99.0)
kontrol("15.7 yalniz LONG'ta HULL AL ile LONG acildi",
        p.position is not None and p.position.side == LONG)

# Canli fiyat HULL9'un olu bandinda (NOTR) -> giris yok.
p = trader("algograf_long")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL", hull_ma=100.0)
kontrol("15.8 HULL NOTR iken LONG acilmaz", p.position is None)
# Canli fiyat HULL9'un altinda (SAT) -> giris yok.
p._algograf(100.0, "5m", "AL", hull_ma=101.0)
kontrol("15.9 HULL SAT iken LONG acilmaz", p.position is None)

# Bar ici HULL SAT -> acik LONG aninda kapanir.
p = trader("algograf_long")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL", hull_ma=99.0)
p._algograf(98.0, "5m", "AL", hull_ma=100.0)
kontrol("15.10 HULL SAT (bar ici) -> LONG kapandi",
        p.position is None and len(p.trades) == 1)
kontrol("15.11 kapanis nedeni HULL SAT",
        "HULL SAT" in p.trades[0].exit_reason)
# HULL SAT iken ayni tick'te yeniden giris yok.
p._algograf(98.0, "5m", "AL", hull_ma=100.0)
kontrol("15.12 HULL SAT sonrasi ayni yonde giris yok",
        p.position is None)
# Fiyat HULL9 ustune donunce yeniden LONG acilir.
p._algograf(102.0, "5m", "AL", hull_ma=100.0)
kontrol("15.13 HULL AL'a donunce yeniden LONG",
        p.position is not None and p.position.side == LONG)

# Iki yonlu modda bu bar ici kapanma UYGULANMAZ.
p = trader("algograf")
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(98.0, "5m", "AL", hull_ma=100.0)
kontrol("15.14 iki yonlu modda bar ici HULL kapatmasi yok",
        p.position is not None)

# --- 15C: zarar freni ---------------------------------------------
p = trader("algograf_long")
p.algo_sl = 0.0
kontrol("15.15 varsayilan zarar freni 10$",
        abs(p.algo_loss_usd - 10.0) < 1e-9)
p._algograf(100.0, "5m", "AL", hull_ma=99.0)
p._algograf(99.8, "5m", "AL", hull_ma=99.0)
kontrol("15.16 esik altinda (net ~9,6$) kapatmaz",
        p.position is not None)
p._algograf(99.7, "5m", "AL", hull_ma=99.0)
kontrol("15.17 esikte (net ~10,4$) kapatir",
        p.position is None and len(p.trades) == 1)
kontrol("15.18 kapanis nedeni zarar freni",
        "zarar freni" in p.trades[0].exit_reason)

# Tutar degisince ANINDA uygulanir.
p = trader("algograf_long")
p.configure(algo_loss_usd=50.0)
p.algo_sl = 0.0
kontrol("15.19 configure tutari hemen uygular",
        abs(p.algo_loss_usd - 50.0) < 1e-9)
p._algograf(100.0, "5m", "AL", hull_ma=99.0)
p._algograf(99.8, "5m", "AL", hull_ma=99.0)
kontrol("15.20 50$ esik altinda kapatmaz", p.position is not None)
p.configure(algo_loss_usd=10.0)
p._algograf(99.7, "5m", "AL", hull_ma=99.0)
kontrol("15.21 10$'a inince aninda kapatir", p.position is None)

# 0 = kapali (HULL SAT kapanisi tetiklenmesin diye HULL uzakta).
p = trader("algograf_long")
p.configure(algo_loss_usd=0.0)
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL", hull_ma=90.0)
kontrol("15.22 HULL AL ile LONG acildi", p.position is not None)
p._algograf(95.0, "5m", "AL", hull_ma=90.0)
kontrol("15.23 0 -> zarar freni kapali", p.position is not None)

# Kapsam: iki yonlu modda zarar freni calismaz.
p = trader("algograf")
p.configure(algo_loss_usd=10.0)
p.algo_sl = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(80.0, "5m", "AL")
kontrol("15.24 iki yonlu modda zarar freni yok", p.position is not None)

# Arayuz logu.
p = trader("algograf_long")
p.algo_sl = 0.0
olaylar = []
p._quiet = False
p._on_event = lambda kind, msg: olaylar.append((kind, msg))
p._algograf(100.0, "5m", "AL", hull_ma=99.0)
p._algograf(99.7, "5m", "AL", hull_ma=99.0)
metin = " | ".join(m for _k, m in olaylar)
kontrol("15.25 zarar freni logda",
        "zarar freni" in metin and "kapandı" in metin)
kontrol("15.26 log olayi 'trade' tipinde",
        any(k == "trade" for k, _m in olaylar))


# ==================================================================
print()
print(f"SONUC: {_GECEN} gecti, {_KALAN} kaldi")
if _KALAN:
    sys.exit(1)

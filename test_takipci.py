# -*- coding: utf-8 -*-
"""TAKİPÇİ — PEMBE (HULL 9) çizgi sıralaması testi (2026-11-25).

Kullanıcı kuralı (5 dk, 4 çizgi — EMA200/SMA200 kullanılmaz):
  * Çizgiler: PEMBE=HULL9, MAVİ=EMA50, YEŞİL=VWMA20, TURUNCU=EMA20.
  * SHORT: PEMBE, EMA50 + VWMA20 + EMA20 ÜÇÜNÜN DE ALTINDA iken aç/koru.
  * SHORT KAPAT: PEMBE dipten yükselip EMA20/VWMA20'den YAKIN olanına
    değince kapat (min(EMA20, VWMA20)).
  * LONG: PEMBE, üçünün de ÜSTÜNDE iken aç/koru.
  * LONG KAPAT: PEMBE tepeden dönüp EMA20/VWMA20'den YAKIN olanına değince
    kapat (max(EMA20, VWMA20)).
  * NÖTR: PEMBE üçlünün dışında değilken bekle.
  * Varyantlar: takipci (iki yön), takipci_long, takipci_short.
  * Zarar freni: net zarar 5$ (varsayılan) -> kapanır; sonrası "Min.
    bekleme" kadar yeni giriş yok (0 = bekleme yok).
  * Kâr bankası: açık kâr eşiğe ulaşınca kapanır, kâr cüzdana yazılır ve
    YENİ pozisyon beklenir (aynı yönde anında yeniden girilmez).
  * Koruyucu stop TAKİPÇİ'de kapalıdır.

Çalıştırma:
    python test_takipci.py
"""
import os
import sys

sys.path.insert(0, ".")

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

try:                        # Windows konsolu: Turkce karakterler
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:           # noqa: BLE001
    pass

import numpy as np   # noqa: E402

from core import takipci   # noqa: E402
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


def trader(mode="takipci"):
    p = PaperTrader("BTCUSDT")
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode)
    p.running = True
    p._quiet = True
    return p


# Hazır dizilimler (fiyat ~100):
#   (TURUNCU, MAVI, PEMBE, YESIL)
RS = (101.0, 104.0, 98.0, 100.0)      # PEMBE en altta -> SHORT
RS_KAL = (101.0, 104.0, 98.5, 100.0)  # hala en altta -> SAT
RS_KAPAT = (101.0, 104.0, 100.0, 100.0)  # PEMBE min(101,100)=100 -> kapat
RL = (99.0, 97.0, 104.0, 100.0)       # PEMBE en ustte -> LONG
RL_KAL = (99.0, 97.0, 100.5, 100.0)   # hala en ustte -> AL
RL_KAPAT = (99.0, 97.0, 100.0, 100.0)  # PEMBE max(99,100)=100 -> kapat
RN = (101.0, 104.0, 102.0, 100.0)     # PEMBE arada -> NOTR

# ==================================================================
print("1) Mod ailesi ve cizgi eslemesi")
s = takipci.summary()
kontrol("1.1 uc varyant",
        sorted(s["modes"]) == ["takipci", "takipci_long",
                               "takipci_short"])
kontrol("1.2 PEMBE=HULL9 (hma)", takipci.LINE_KEYS["PEMBE"] == "hma")
kontrol("1.3 MAVI=EMA50", takipci.LINE_KEYS["MAVİ"] == "ema50")
kontrol("1.4 YESIL=VWMA20", takipci.LINE_KEYS["YEŞİL"] == "vwma")
kontrol("1.5 TURUNCU=EMA20", takipci.LINE_KEYS["TURUNCU"] == "ema20")
kontrol("1.6 EMA200/SMA200 kullanilmiyor",
        "ema200" not in takipci.LINE_KEYS.values()
        and "sma200" not in takipci.LINE_KEYS.values())
kontrol("1.7 mod tanima",
        takipci.is_takipci_mode("takipci")
        and takipci.is_takipci_mode("takipci_long")
        and takipci.is_takipci_mode("takipci_short")
        and not takipci.is_takipci_mode("algograf"))
kontrol("1.8 yon eslemesi",
        takipci.side_for_mode("takipci_long") == 1
        and takipci.side_for_mode("takipci_short") == -1
        and takipci.side_for_mode("takipci") is None)

# ==================================================================
print("2) SHORT: PEMBE ucunun de altinda -> ac/koru; EMA20/VWMA20'ye değince kapat")
seri = takipci.series(ma([RS, RS_KAL, RS_KAPAT]))
kontrol("2.1 giris SAT", seri[0] == "SAT")
kontrol("2.2 pozisyonda kal (SAT)", seri[1] == "SAT")
kontrol("2.3 PEMBE EMA20/VWMA20'ye degdi -> SAT-KAPAT",
        seri[2] == "SAT-KAPAT")

# EMA50'nin altinda ama EMA20'nin ustunde: giris YOK.
seri = takipci.series(ma([(101.0, 97.0, 98.0, 100.0)]))
kontrol("2.4 ucunun de altinda degilse SHORT acilmaz",
        seri[0] == "NÖTR")

# Cikis icin YAKIN cizgi: EMA20 (101) > VWMA20 (100) iken esik 100.
seri = takipci.series(ma([RS, (101.0, 104.0, 99.5, 100.0)]))
kontrol("2.5 min(EMA20,VWMA20)=VWMA20 altinda -> SAT kalir",
        seri[1] == "SAT")

# ==================================================================
print("3) LONG: PEMBE ucunun de ustunde -> ac/koru; EMA20/VWMA20'ye değince kapat")
seri = takipci.series(ma([RL, RL_KAL, RL_KAPAT]))
kontrol("3.1 giris AL", seri[0] == "AL")
kontrol("3.2 pozisyonda kal (AL)", seri[1] == "AL")
kontrol("3.3 PEMBE EMA20/VWMA20'ye degdi -> AL-KAPAT",
        seri[2] == "AL-KAPAT")

# EMA20'nin ustunde ama EMA50'nin altinda: giris YOK.
seri = takipci.series(ma([(99.0, 105.0, 104.0, 100.0)]))
kontrol("3.4 ucunun de ustunde degilse LONG acilmaz",
        seri[0] == "NÖTR")

# Cikis icin YAKIN cizgi: EMA20 (99) < VWMA20 (100) iken esik 100.
seri = takipci.series(ma([RL, (99.0, 97.0, 100.5, 100.0)]))
kontrol("3.5 max(EMA20,VWMA20)=VWMA20 ustunde -> AL kalir",
        seri[1] == "AL")

# ==================================================================
print("4) NOTR ve varyantlar")
seri = takipci.series(ma([RN]))
kontrol("4.1 PEMBE arada -> NOTR", seri[0] == "NÖTR")
seri = takipci.series(ma([(100.0, 100.0, 100.0, 100.0)]))
kontrol("4.2 tam cakisma -> NOTR", seri[0] == "NÖTR")

seri = takipci.series(ma([RS]), side=1)
kontrol("4.3 takipci_long SHORT diziliminde NOTR", seri[0] == "NÖTR")
seri = takipci.series(ma([RL]), side=-1)
kontrol("4.4 takipci_short LONG diziliminde NOTR", seri[0] == "NÖTR")
seri = takipci.series(ma([RL]), side=1)
kontrol("4.5 takipci_long LONG diziliminde AL", seri[0] == "AL")
seri = takipci.series(ma([RS]), side=-1)
kontrol("4.6 takipci_short SHORT diziliminde SAT", seri[0] == "SAT")

# Iki yon: once SHORT, kapanista sonra LONG ancak bir sonraki barda acilir.
seri = takipci.series(ma([RS, RS_KAPAT, RL]))
kontrol("4.7 iki yon: SAT -> SAT-KAPAT -> AL",
        seri == ["SAT", "SAT-KAPAT", "AL"])

# ==================================================================
print("5) Yurutme: TAKIPCI iki yon acar (HULL fiyat onayi GEREKMEZ)")
p = trader("takipci")
p._algograf(100.0, "5m", "AL")
kontrol("5.1 AL -> LONG acildi",
        p.position is not None and p.position.side == LONG)
kontrol("5.2 notional ana para x kaldiraç (tk_fraction ile)",
        abs(p.position.notional - 4000.0) < 1e-6)
kontrol("5.3 TAKIPCI'de koruyucu stop YOK", p.position.stop_price == 0.0)

p = trader("takipci")
p._algograf(100.0, "5m", "SAT")
kontrol("5.4 SAT -> SHORT acildi",
        p.position is not None and p.position.side == SHORT)

p = trader("takipci_long")
p._algograf(100.0, "5m", "SAT")
kontrol("5.5 yalniz-LONG varyanti SHORT acmaz", p.position is None)
p = trader("takipci_short")
p._algograf(100.0, "5m", "AL")
kontrol("5.6 yalniz-SHORT varyanti LONG acmaz", p.position is None)

# ==================================================================
print("6) Zarar freni (varsayilan -5$) ve Min. bekleme")
p = trader("takipci")
p.min_hold_bars = 0
p._algograf(100.0, "5m", "AL")
p._algograf(99.9, "5m", "AL")
kontrol("6.1 net zarar 5$ -> pozisyon kapandi",
        p.position is None and len(p.trades) == 1)
kontrol("6.2 Min. bekleme 0 -> bekleme yok",
        p._algo_loss_pause_until <= p._algo_simdi_ms())
p._algograf(99.9, "5m", "AL")
kontrol("6.3 bekleme 0 iken ayni yonde hemen yeniden girer",
        p.position is not None)

p = trader("takipci")
p.min_hold_bars = 3
p._algograf(100.0, "5m", "AL")
p._algograf(99.9, "5m", "AL")
kontrol("6.4 zarar freni kapatti", p.position is None)
p._algograf(99.9, "5m", "AL")
kontrol("6.5 Min. bekleme 3 -> yeni giris engellendi",
        p.position is None
        and p._algo_loss_pause_until > p._algo_simdi_ms())

# ==================================================================
print("7) Kâr bankasi: kapat, cuzdana yaz, YENI pozisyon bekle")
p = trader("takipci")
p.algo_bank_usd = 10.0
p.min_hold_bars = 0
p._algograf(100.0, "5m", "AL")
bakiye0 = p.balance
p._algograf(100.25, "5m", "AL", None, 100.30)
kontrol("7.1 esik -> pozisyon kapandi",
        p.position is None and len(p.trades) == 1)
kontrol("7.2 kar cuzdana yazildi",
        p.banked_profit > 0.0 and p.balance > bakiye0)
p._algograf(100.30, "5m", "AL")
kontrol("7.3 ayni yonde aninda yeniden GIRMEZ",
        p.position is None and len(p.trades) == 1)
p._algograf(100.30, "5m", "NÖTR")
p._algograf(100.30, "5m", "AL")
kontrol("7.4 kural sifirlaninca yeni pozisyon acilir",
        p.position is not None)

# ==================================================================
print("8) Kural kapanisi ve Min. bekleme")
p = trader("takipci")
p.min_hold_bars = 2
p.algo_bank_usd = 0.0
p._algograf(100.0, "5m", "AL")
p._algograf(100.5, "5m", "AL-KAPAT")
kontrol("8.1 AL-KAPAT LONG'u kapatti",
        p.position is None and len(p.trades) == 1)
kontrol("8.2 kapanis sonrasi bekleme basladi",
        p._algo_loss_pause_until > p._algo_simdi_ms())
p._algograf(100.5, "5m", "AL")
kontrol("8.3 bekleme sirasinda yeni giris yok", p.position is None)

p = trader("takipci")
p.min_hold_bars = 0
p.algo_bank_usd = 0.0
p._algograf(100.0, "5m", "SAT")
p._algograf(99.5, "5m", "SAT-KAPAT")
kontrol("8.4 Min. bekleme 0 -> kapanistan sonra bekleme yok",
        p._algo_loss_pause_until <= p._algo_simdi_ms())

# ==================================================================
print()
print(f"SONUC: {_GECEN} gecti, {_KALAN} kaldi")
if _KALAN:
    sys.exit(1)

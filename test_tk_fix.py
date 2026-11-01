# -*- coding: utf-8 -*-
"""TK canli-zarar duzeltmesi testleri (2026-10-31).

Uc knop:
  1) PAPER_TK_FRACTION  — pozisyon boyu cuzdan fraksiyonunun yarisina
     iner (stop kaybi yariya; banka hedefi bakiyenin %2,5'i kalir).
  2) PAPER_TK_BANK_RR   — banka esigi EN AZ stop riski x RR olur.
  3) PAPER_TK_PAUSE_BARS— zarar sonrasi ayni yonde K bar yeni giris yok.

Calistirma: python test_tk_fix.py
"""
from __future__ import annotations

import config
from core.paper import PaperTrader

GECEN = []


def kontrol(ad: str, kosul: bool) -> None:
    if not kosul:
        raise AssertionError("GECMEDI: " + ad)
    GECEN.append(ad)
    print("  GECTI  " + ad)


class C:
    def __init__(s, t, close, open_):
        s.closed = True
        s.open = open_
        s.open_time = t
        s.close = close
        s.high = max(open_, close) * 1.001
        s.low = min(open_, close) * 0.999


def duz_mumlar(n: int = 40, px: float = 0.1):
    return [C(i * 60_000, px, px) for i in range(n)]


def tk(**kw):
    p = PaperTrader(kw.pop("symbol", "DOGEUSDT"))
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.running = True
    p.tk_after_ms = 0.0
    # Bu testler pozisyon boyu / banka / bekleme mekanizmalarini olcer;
    # giris tetigi ve trend zorunlulugu ayri testlerde (7, 8) sinanir.
    kw.setdefault("tk_entry_offset", 0.0)
    kw.setdefault("tk_require_trend", False)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def tk_varsayilan(**kw):
    """config varsayilanlariyla (pullback + trend zorunlulugu) trader."""
    p = PaperTrader(kw.pop("symbol", "DOGEUSDT"))
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.running = True
    p.tk_after_ms = 0.0
    for k, v in kw.items():
        setattr(p, k, v)
    return p


# ------------------------------------------------------------------
# 1) POZISYON BOYU: notional = fraksiyon * teminat * kaldirac
# ------------------------------------------------------------------
m = duz_mumlar()
p = tk()
ev = p.on_price(0.1, m, "1m", "AL")
kontrol("1 fraksiyon varsayilani 0,50", abs(p.tk_fraction - 0.50) < 1e-9)
beklenen = 0.50 * 0.80 * 1000.0 * 10.0          # 4000$
kontrol("1 notional fraksiyonla kisildi (~4000$)",
        p.position is not None and
        abs(p.position.notional - beklenen) < 1.0)
kontrol("1 pozisyon LONG", p.position.side == "LONG")

# ------------------------------------------------------------------
# 2) BANKA R:R TABANI: stop uzaksa esik bakiye yuzdesini asar
#    entry 0.1, stop %3 uzak, qty 40000 -> risk 120$, x1.8 = 216$
#    (bakiye %2,5 = ~25$) -> banka ancak fiyat +%5,4'te.
# ------------------------------------------------------------------
entry = float(p.position.entry)
# Banka R:R testini ayri mekanizmalardan izole et: ATR stop kapali,
# risk-BE kapali yoksa stop BE'ye cekilince banka esigi kayar.
p.tk_sl_atr = 0.0
p.tk_be_risk = 0.0
p.position.tk_stop = entry * 0.97
p.position.tk_tp = 0.0
ev = p.on_price(entry * 1.01, m, "1m", "AL")
kontrol("2 +%1 kârda banka YOK (R:R tabani uzak hedef)",
        p.position is not None)
ev = p.on_price(entry * 1.06, m, "1m", "AL")
kontrol("2 +%6 kârda banka kapandi (R:R tabani)",
        p.position is None and ev is not None and "banka" in ev.lower())

# ------------------------------------------------------------------
# 3) ZARAR SONRASI BEKLEME: ayni yonde 3 bar giris yok
# ------------------------------------------------------------------
m3 = duz_mumlar()
p3 = tk(tk_sar=False, tk_ribbon=False, tk_pause_bars=3)
p3.on_price(0.1, m3, "1m", "AL")
kontrol("3 LONG acildi", p3.position is not None and
        p3.position.side == "LONG")
p3.position.tk_stop = 0.099
ev = p3.on_price(0.0989, m3, "1m", "AL")     # stop (canli tik)
kontrol("3 stop zarari islendi", p3.position is None and
        p3._tk_kayip_t > 0 and p3._tk_kayip_yon == 1)
ev = p3.on_price(0.0989, m3, "1m", "AL")
kontrol("3 ayni yonde hemen giris ENGELLENDI", p3.position is None)
T = int(m3[-1].open_time)
for i in range(1, 3):
    T += 60_000
    m3.append(C(T, 0.0989, 0.0989))
    ev = p3.on_price(0.0989, m3, "1m", "AL")
    kontrol(f"3 {i}. bar sonrasi hala ENGELLI", p3.position is None)
T += 60_000
m3.append(C(T, 0.0989, 0.0989))
ev = p3.on_price(0.0989, m3, "1m", "AL")
kontrol("3 3 bar sonra ayni yonde giris ACIK",
        p3.position is not None and p3.position.side == "LONG")

# ------------------------------------------------------------------
# 4) TERS YON MUAFIYETI: zarar sonrasi karsi yon serbest (trend donusu)
# ------------------------------------------------------------------
m4 = duz_mumlar()
p4 = tk(tk_sar=False, tk_ribbon=False, tk_pause_bars=3)
p4.on_price(0.1, m4, "1m", "AL")
p4.position.tk_stop = 0.099
p4.on_price(0.0989, m4, "1m", "AL")         # zararli stop
m4.append(C(int(m4[-1].open_time) + 60_000, 0.0988, 0.0989))
p4._tk_hist_y1 = "SAT"
p4._tk_hist_y2 = "SAT"
p4.tk_hedef = -1
p4.tk_hedef_kaynak = "SAT"
ev = p4.on_price(0.0988, m4, "1m", "SAT")
kontrol("4 karsi yon (SHORT) girisi MUAF",
        p4.position is not None and p4.position.side == "SHORT")

# ------------------------------------------------------------------
# 5) OLU BANT (deadband): EMA20/EMA50 farki cok kucukse kesisme yok
# ------------------------------------------------------------------
m5 = []
px5 = 0.1
for i in range(300):
    op5 = px5
    px5 = px5 + 1e-7                   # ~0,0001%/bar: mikro fark
    m5.append(C(i * 60_000, px5, op5))
p5 = tk(tk_rib_confirm=1, tk_rib_deadband=0.0)
kontrol("5 olu bant kapali: yon +1", p5._tk_ribbon(m5) == 1)
p5b = tk(tk_rib_confirm=1, tk_rib_deadband=0.0002)
kontrol("5 mikro fark olu bantta 0 (kesisme sayilmaz)",
        p5b._tk_ribbon(m5) == 0)

# ------------------------------------------------------------------
# 6) TEYIT (confirm=2): tek bar donusu yon degistirmez (sticky)
# ------------------------------------------------------------------
m6 = []
px6 = 0.1
for i in range(300):
    op6 = px6
    px6 = op6 * 1.0005
    m6.append(C(i * 60_000, px6, op6))
p6 = tk(tk_rib_confirm=2, tk_rib_deadband=0.0)
kontrol("6 yukselis 2 bar onayli: +1", p6._tk_ribbon(m6) == 1)
T6 = int(m6[-1].open_time) + 60_000
op6 = px6
px6 = op6 * 0.80                       # tek sert dusus bari
m6.append(C(T6, px6, op6))
kontrol("6 tek dusus bari yonu DEGISTIRMEZ (sticky)",
        p6._tk_ribbon(m6) == 1)
T6 += 60_000
op6 = px6
px6 = op6 * 0.98                       # ikinci dusus: onay tamam
m6.append(C(T6, px6, op6))
kontrol("6 2. dusus bari yonu -1 yapar", p6._tk_ribbon(m6) == -1)

# ------------------------------------------------------------------
# 7) GIRIS TETIGI: varsayilan PULLBACK (sinyal fiyatinin %0,05 gerisi)
#    Canli desen (2026-10-31): aninda girisler donus tepelerine denk
#    geliyordu. Artik pasif limit sinyal fiyatinin ALTINA konur; fiyat
#    geri dokunursa daha iyi fiyattan dolar, dokunmazsa giris olmaz.
# ------------------------------------------------------------------
m7 = []
px7 = 0.1
for i in range(300):                   # yukselis: rib +1 (trend var)
    op7 = px7
    px7 = op7 * 1.002
    m7.append(C(i * 60_000, px7, op7))
p7 = tk_varsayilan()
kontrol("7 giris tetigi varsayilani -%0,10 (pullback)",
        abs(p7.tk_entry_offset + 0.001) < 1e-12)
ev = p7.on_price(px7, m7, "1m", "AL")
kontrol("7 aninda giris YOK (pasif limit bekliyor)",
        p7.position is None and p7.tk_pend_entry is not None)
L7 = px7 * (1.0 - 0.001)
kontrol("7 limit sinyal fiyatinin %0,10 ALTINDA",
        abs(p7.tk_pend_entry[1] - L7) < 1e-12)
ev = p7.on_price(px7 * 1.003, m7, "1m", "AL")
kontrol("7 fiyat yukselince limit KOVALANMAZ (seviye sabit)",
        p7.position is None and p7.tk_pend_entry is not None and
        abs(p7.tk_pend_entry[1] - L7) < 1e-12)
ev = p7.on_price(L7 * 0.9999, m7, "1m", "AL")
kontrol("7 limit seviyesine dokununca LONG doldu",
        p7.position is not None and p7.position.side == "LONG")
kontrol("7 dolum LIMIT seviyesinden (daha iyi fiyat)",
        abs(p7.position.entry - L7) < 1e-12)

# ------------------------------------------------------------------
# 8) TREND ZORUNLULUGU: rib==0 (EMA'lar ayrismamis) -> giris yok
# ------------------------------------------------------------------
m8 = duz_mumlar()                      # yatay: EMA20==EMA50 -> rib 0
p8 = tk_varsayilan(tk_entry_offset=0.0)
ev = p8.on_price(0.1, m8, "1m", "AL")
kontrol("8 trend yok (rib=0) -> giris YOK",
        p8.position is None and p8.tk_pend_entry is None)
p8b = tk_varsayilan(tk_entry_offset=0.0)
ev = p8b.on_price(px7, m7, "1m", "AL")  # yukselis: rib +1
kontrol("8 trend varken (rib=+1) giris ACIK",
        p8b.position is not None and p8b.position.side == "LONG")

# ------------------------------------------------------------------
# 9) SEVIYE HAFIZASI: zarar edilen giris seviyesine yakin AYNI yon
#    giremez (ENA: 0,1945/0,1944/0,1946 -> hepsi stop)
# ------------------------------------------------------------------
m9 = duz_mumlar()
p9 = tk(tk_sar=False, tk_ribbon=False, tk_pause_bars=0,
        tk_streak_n=0, tk_level_ban=0.002, tk_level_bars=15)
p9.on_price(0.1000, m9, "1m", "AL")
p9.position.tk_stop = 0.0999
p9.on_price(0.09989, m9, "1m", "AL")         # stop-out (entry 0,1000)
kontrol("9 1. LONG stop oldu", p9.position is None and
        p9._tk_kayip_giris > 0)
m9.append(C(int(m9[-1].open_time) + 60_000, 0.10001, 0.09995))
ev = p9.on_price(0.10001, m9, "1m", "AL")    # %0,02 uzakta: YASAK
kontrol("9 kayip seviyesine yakin giris ENGELLENDI",
        p9.position is None and p9.tk_pend_entry is None)
ev = p9.on_price(0.1020, m9, "1m", "AL")     # %0,20+ uzak: serbest
kontrol("9 seviyeden uzakta giris ACIK", p9.position is not None)

# ------------------------------------------------------------------
# 10) SERI FRENI: arka arkaya 2 zarar -> TUM yonlerde 10 bar fren
# ------------------------------------------------------------------
m10 = duz_mumlar()
p10 = tk(tk_sar=False, tk_ribbon=False, tk_pause_bars=0,
         tk_streak_n=2, tk_streak_bars=10, tk_level_ban=0.0)
p10.on_price(0.1000, m10, "1m", "AL")
p10.position.tk_stop = 0.0999
p10.on_price(0.09989, m10, "1m", "AL")       # zarar 1
p10.on_price(0.09989, m10, "1m", "AL")       # tekrar giris
kontrol("10 yeniden giris acildi", p10.position is not None)
p10.position.tk_stop = 0.0999
p10.on_price(0.09989, m10, "1m", "AL")       # zarar 2
kontrol("10 iki zarar sonrasinda seri freni AKTIF",
        p10._tk_seri >= 2 and p10._tk_seri_t > 0)
ev = p10.on_price(0.1020, m10, "1m", "MARKET:AL")
kontrol("10 seri frende giris ENGELLENDI", p10.position is None)
for i in range(11):
    m10.append(C(int(m10[-1].open_time) + 60_000, 0.1020, 0.1020))
kontrol("10 10 bar sonra temiz sayfa (sayac sifir)",
        p10.on_price(0.1020, m10, "1m", "AL") is not None and
        p10.position is not None and p10._tk_seri == 0)

# ------------------------------------------------------------------
# 11) ATR STOP: stop = max(SL, ATR14 * kat)
# ------------------------------------------------------------------
m11 = []
px11 = 0.1
for i in range(300):                         # yukselis
    op11 = px11
    px11 = op11 * 1.002
    m11.append(C(i * 60_000, px11, op11))
p11 = tk(tk_sl_atr=2.0, tk_entry_offset=0.0)
ev = p11.on_price(px11, m11, "1m", "AL")
d11 = abs(p11.position.entry - p11.position.tk_stop) / p11.position.entry
kontrol("11 ATR stop tabandan WIDE (0,4% > %0,3)", d11 > 0.003)

# ------------------------------------------------------------------
# 12) RISK-BE: acik kar stop mesafesinin katina ulasirsa stop girise
# ------------------------------------------------------------------
m12 = duz_mumlar()
p12 = tk(tk_be_risk=0.9, tk_entry_offset=0.0, tk_tp=0.0)
p12.on_price(0.1000, m12, "1m", "AL")
rd12 = p12.position.tk_risk_d
kontrol("12 risk mesafesi kaydedildi", rd12 > 0)
ev = p12.on_price(0.1006, m12, "1m", "AL")   # +%0,6 >= 0,9*rd (+%0,27)
be12 = 0.1 * (1.0 + p12.maker_rate * 2.0)
kontrol("12 BE kondu (stop girise cekildi)",
        getattr(p12.position, "tk_be_armed", False) and
        abs(p12.position.tk_stop - be12) < 1e-9)
ev = p12.on_price(0.0999, m12, "1m", "AL")   # geri donus: BE'de kapanir
kontrol("12 BE sonrasi geri donus kayibsiz kapanir",
        p12.position is None)

# ------------------------------------------------------------------
# 13) ZAMAN STOPU: K bar sonuca ulasmayan islem kapanir
# ------------------------------------------------------------------
m13 = duz_mumlar()
p13 = tk(tk_time_bars=3, tk_entry_offset=0.0)
T13 = int(m13[-1].open_time)
p13.on_price(0.1000, m13, "1m", "AL")
for i in range(4):
    T13 += 60_000
    m13.append(C(T13, 0.1000, 0.1000))
ev = p13.on_price(0.1000, m13, "1m", "AL")
kontrol("13 3 bar sonra sonuca ulasmayan islem KAPANDI",
        p13.position is None and ev is not None and
        "zaman" in ev.lower())

print("-" * 62)
print(f"{len(GECEN)}/{len(GECEN)} TK duzeltme testi gecti")
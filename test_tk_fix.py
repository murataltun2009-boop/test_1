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

print("-" * 62)
print(f"{len(GECEN)}/{len(GECEN)} TK duzeltme testi gecti")

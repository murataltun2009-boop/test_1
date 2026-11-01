# -*- coding: utf-8 -*-
"""TK butunluk sanity: canli tik yuvarla-kac senaryolari (hizli kontrol).

Adimlar giris/gri-TERS/stop/seri/seviye/banka/BE/zaman-stop yuvarlak
masasi. Calistirma: python tools/sanity_tk.py
"""
import sys
sys.path.insert(0, ".")
from core.paper import PaperTrader   # noqa: E402


class C:
    def __init__(s, t, close, open_):
        s.closed = True
        s.open = open_
        s.open_time = t
        s.close = close
        s.high = max(open_, close) * 1.001
        s.low = min(open_, close) * 0.999


def yatay(n=40, px=0.100, t0=0):
    return [C(t0 + i * 60_000, px, px) for i in range(n)]


def tk(**kw):
    p = PaperTrader("DOGEUSDT")
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk", risk_pct=0.03)
    p.running = True
    p.tk_after_ms = 0.0
    # Bu dosya giris/yuvarlak-masa kurallarini sinar; agar alan testli
    # (test_tk_fix) mekanizmalari izole eder.
    kw.setdefault("tk_entry_offset", 0.0)
    kw.setdefault("tk_require_trend", False)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def yukselen(n=300, px=0.1):
    m = []
    for i in range(n):
        op = px
        px = op * 1.002
        m.append(C(i * 60_000, px, op))
    return m


adim = 0


def kontrol(ad, kosul):
    global adim
    adim += 1
    if not kosul:
        raise AssertionError(f"GECMEDI adim {adim}: {ad}")
    print(f"  ADIM {adim:2d} GECTI: {ad}")


# 1) AL yildiz -> LONG acilir
p = tk()
m = yatay()
p.on_price(0.1, m, "1m", "AL")
kontrol("AL yildiz LONG", p.position is not None and p.position.side == "LONG")

# 2) mum-yildiz uyusmazligi gate: kirmiziloyd mum + AL yildiz
p2 = tk(tk_sar=False, tk_ribbon=False)
m2 = yatay()
p2.on_price(0.1, m2, "1m", "AL")
p2.position.tk_stop = 0.09
m2[-1] = C(m2[-1].open_time, 0.098, 0.102)      # son kapali mum kirmizi
ev = p2.on_price(0.0981, m2, "1m", "AL")
kontrol("hata mumda AL yildiz yeni poz degismez", p2.position is not None)

# 3) banka kapanisi awards: kâr muhr yazilir
p3 = tk(tk_sl_atr=0.0)
m3 = yatay()
p3.on_price(0.1, m3, "1m", "AL")
p3.position.tk_stop = 0.0999                     # risk ~%0,3
p3.position.tk_tp = 0.0
p3.tk_be_risk = 0.0
ev = p3.on_price(0.1040, m3, "1m", "AL")
kontrol("banka kapandi ve cuzdana yaz",
        p3.position is None and ev is not None and "banka" in ev.lower() and
        p3.commission_paid > 0)

# 4) stop -> sonra seri/seviye kayitlari
p4 = tk(tk_sar=False, tk_ribbon=False, tk_pause_bars=0, tk_streak_n=2,
        tk_streak_bars=10, tk_level_ban=0.002, tk_level_bars=15)
m4 = yatay()
p4.on_price(0.1, m4, "1m", "AL")
p4.position.tk_stop = 0.0999
p4.on_price(0.09989, m4, "1m", "AL")
kontrol("stop sonrasi seviye hafizasi", p4._tk_kayip_giris == 0.1)
kontrol("stop sonrasi seviyeye yakin giris yok", p4.position is None)

# 5) BE risk: kazanca dokunmadan korunur
p5 = tk(tk_be_risk=0.9, tk_tp=0.0, tk_sl_atr=0.0)
m5 = yatay()
p5.on_price(0.1, m5, "1m", "AL")
p5.on_price(0.1006, m5, "1m", "AL")
kontrol("BE arm edildi", getattr(p5.position, "tk_be_armed", False))
p5.on_price(0.0999, m5, "1m", "AL")
kontrol("BE sonrasi geri donus pozisyonu kapatti", p5.position is None)

# 6) zaman stopu
p6 = tk(tk_time_bars=3, tk_sl_atr=0.0)
m6 = yatay()
p6.on_price(0.1, m6, "1m", "AL")
T = m6[-1].open_time
for i in range(4):
    m6.append(C(T + (i + 1) * 60_000, 0.1, 0.1))
ev = p6.on_price(0.1, m6, "1m", "AL")
kontrol("zaman stopu kapatti", p6.position is None)

# 7) cizgi dizilimi yukari iken SAT giris yok (ribbon)
m7 = yukselen(300)
p7 = tk(tk_require_trend=True, tk_streak_n=0, tk_level_ban=0.0)
assert p7._tk_ribbon(m7) == 1
p7.on_price(m7[-1].close, m7, "1m", "SAT")
kontrol("yukselis diziliminde SAT giris yok (ribbon)", p7.position is None)
p7.on_price(m7[-1].close, m7, "1m", "AL")
kontrol("yukselis diziliminde AL giris acildi (offset 0)",
        p7.position is not None and p7.position.side == "LONG")

# 8) pullback: m7 offset -%0.10 -> pasif limit bekler
p8 = tk(tk_require_trend=True, tk_streak_n=0, tk_level_ban=0.0,
        tk_entry_offset=-0.001)
px8 = m7[-1].close
ev = p8.on_price(px8, m7, "1m", "AL")
kontrol("pullback aninda giris yapmaz", p8.position is None and
        p8.tk_pend_entry is not None)
ev = p8.on_price(px8 * 0.999 * 0.9999, m7, "1m", "AL")  # limite dokundu
be8 = None
if p8.position is not None:
    be8 = p8.position.entry
kontrol("pullback dolumu daha iyi fiyattan", be8 is not None and
        be8 < px8 and abs(be8 - px8 * 0.999) <= px8 * 0.0001)

print(f"SANITY TAMAM: {adim} adim")

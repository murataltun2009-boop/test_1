# -*- coding: utf-8 -*-
"""TİK2 — YALNIZ-SHORT yildiz durum makinesi testi (2026-11-02).

Kullanici kurali:
  * Kirmizi yildiz (SAT/GÜÇLÜ SAT): SHORT ac / kirmizi surekli SHORT'ta kal.
  * Gri yildiz (NÖTR): pozisyonu KAPATIR (kirmizi-dogumlu short).
  * Yesil yildiz (AL/GÜÇLÜ AL): islem ACMAZ, bekler.
  * Yesilden SONRA gri gelirse: SHORT acar.
  * HICBIR kosulda LONG acilmaz.
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
        s.high = max(open_, close) * 1.0001
        s.low = min(open_, close) * 0.9999


def kontrol(ad, kosul):
    if not kosul:
        raise AssertionError("GECMEDI: " + ad)
    print("  GECTI ", ad)


def tk(**kw):
    p = PaperTrader("DOGEUSDT")
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
    p.tk_on = True
    p.tk_tp = 0.0
    p.tk_be = False
    p.tk_require_trend = False      # yildiz-kurali testleri izole
    p.tk_entry_offset = 0.0         # aninda giris (tik testi)
    p.tk_pause_bars = 0
    p.tk_streak_n = 0
    p.tk_level_ban = 0.0
    p.tk_bank_pct = 0.0
    p.tk_be_risk = 0.0
    p.tk_time_bars = 0
    p.tk_after_ms = 0.0
    p.running = True
    for k, v in kw.items():
        setattr(p, k, v)
    return p


# Bar matrisi: T_i = i daki bar; her "Adim icinde bir bar kapanir".
T0 = 0


def barlar(n):
    # KIRMIZI mumlar (close < open): mum-yonu kapisi SHORT girişini
    # engellemesin izole-test amaçlı.
    m = [C(i * 60_000, 0.1, 0.1002) for i in range(60)]
    return m


def yildiz_var(p, m, yildiz, also_mum=None):
    """Yeni bar kapandi: yerlesen yildizi gunceller, tik verir."""
    t = int(m[-1].open_time) + 60_000
    px = float(m[-1].close) if also_mum is None else float(also_mum)
    op = px * 1.0002
    m.append(C(t, px, op))
    return p.on_price(px, m, "1m", yildiz)


# ------------------------------------------------------------------
# 1) Kirmizi -> SHORT acilir
# ------------------------------------------------------------------
p1 = tk()
m1 = barlar(60)
ev = yildiz_var(p1, m1, "SAT")
kontrol("1 kirmizi yildiz SHORT acti",
        p1.position is not None and p1.position.side == "SHORT")

# ------------------------------------------------------------------
# 2) Kirmizi devam -> SHORT'ta KALIR (yeni islem acilmaz)
# ------------------------------------------------------------------
n2 = len(p1.trades)
ev = yildiz_var(p1, m1, "GÜÇLÜ SAT")
kontrol("2 kirmizi devami: pozisyon KALDI",
        p1.position is not None and p1.position.side == "SHORT")
kontrol("2 kirmizi devami: YENI islem acilmadi", len(p1.trades) == n2)

# ------------------------------------------------------------------
# 3) Gri -> pozisyon KAPATIR; ters (LONG) acilmaz
# ------------------------------------------------------------------
ev = yildiz_var(p1, m1, "NÖTR")
kontrol("3 gri: pozisyon kapandi", p1.position is None)
kontrol("3 gri: islem kapanis kaydi SHORT", len(p1.trades) == n2 + 1 and
        p1.trades[-1].side == "SHORT")
mask = [t.side for t in p1.trades]
kontrol("3 gri: HIC LONG yok", all(s == "SHORT" for s in mask))

# ------------------------------------------------------------------
# 4) Yesil (pozisyon yok) -> islem acmaz, bekler
# ------------------------------------------------------------------
n4 = len(p1.trades)
ev = yildiz_var(p1, m1, "AL")
kontrol("4 yesil: pozisyon yok", p1.position is None)
ev = yildiz_var(p1, m1, "GÜÇLÜ AL")
kontrol("4 yesil devami: islem acilmadi", len(p1.trades) == n4 and
        p1.position is None)
kontrol("4 yesil devami: gri-TERS kurali CALISMAZ",
        p1.tk_hedef == 0)

# ------------------------------------------------------------------
# 5) Yesil -> gri: SHORT acar
# ------------------------------------------------------------------
ev = yildiz_var(p1, m1, "NÖTR")
kontrol("5 yesil→gri: SHORT acildi",
        p1.position is not None and p1.position.side == "SHORT")
# gri dizisi boyunca gri-dogumlu short KALIR
ev = yildiz_var(p1, m1, "NÖTR")
kontrol("5 gri-dogumlu gri devami: KALDI", p1.position is not None)
# yesil geri gelir: gri-dogumlu short kapanir
ev = yildiz_var(p1, m1, "AL")
kontrol("5 yesil geri geldi: gri-dogumlu short kapandi",
        p1.position is None)
# sonra tekrar gri: yesil→gri kacisi → SHORT tekrar acilir
ev = yildiz_var(p1, m1, "NÖTR")
kontrol("5 tekrar yesil→gri: SHORT acildi",
        p1.position is not None and p1.position.side == "SHORT")

# ------------------------------------------------------------------
# 6) LONG garantisi: kirmizi-dogumlu short kapanip yesil+gri
#    dizisinden gecse bile tum islemler SHORT
# ------------------------------------------------------------------
p6 = tk()
m6 = barlar(60)
yildiz_var(p6, m6, "GÜÇLÜ SAT")          # short
yildiz_var(p6, m6, "NÖTR")               # kapandi
yildiz_var(p6, m6, "GÜÇLÜ AL")           # yesil: bekler
yildiz_var(p6, m6, "NÖTR")               # yesil→gri: SHORT acar
kontrol("6 son giris SHORT", p6.position is not None and
        p6.position.side == "SHORT")
mask6 = [t.side for t in p6.trades]
kontrol("6 hic LONG yok", all(s == "SHORT" for s in mask6))
kontrol("6 geleneksel gri-TERS hedefi YOK (+1 kurulmaz)",
        p6.tk_hedef <= 0)

# ------------------------------------------------------------------
# 7) Ribbon pin TİK2 hedefe DOKUNMAZ (+1 kurmaz); ama trend-yön
#    kapısı YÜKSELİŞ diziliminde kırmızı-short girişini yine engeller
#    (koruma, TİK1 ile aynı)
# ------------------------------------------------------------------
p7 = tk()
m7 = []
px7 = 0.1
for i in range(300):
    op = px7
    px7 = op * 1.002
    m7.append(C(i * 60_000, px7, op))
assert p7._tk_ribbon(m7) == 1          # yukselis dizilimi
ev = yildiz_var(p7, m7, "SAT")
kontrol("7 ribbon pin calismaz (hedef +1 DEGIL)", p7.tk_hedef <= 0)
kontrol("7 yukselis diziliminde kirmizi giris ENGELLENDI (koruma)",
        p7.position is None)
kontrol("7 ribbon flip kapali", p7.tk_ribbon_flip is False)
# dusus dizilimine gectikten sonra kirmizi giris acilir
for i in range(60):
    opc = px7
    px7 = opc * 0.985
    m7.append(C(int(m7[-1].open_time) + 60_000, px7, opc))
assert p7._tk_ribbon(m7) == -1
ev = yildiz_var(p7, m7, "SAT")
kontrol("7 dusus diziliminde kirmizi: SHORT acildi",
        p7.position is not None and p7.position.side == "SHORT")
ev = yildiz_var(p7, m7, "NÖTR")
kontrol("7 gri: short kapandi; LONG'a cevrilmedi", p7.position is None)

# ------------------------------------------------------------------
# 8) SAR: stop-out sonrasi ters cevirme LONG acamaz (düz kapanis)
# ------------------------------------------------------------------
p8 = tk()
m8 = barlar(60)
ev = yildiz_var(p8, m8, "SAT")
p8.position.tk_stop = 0.0999
ev = yildiz_var(p8, m8, "SAT", also_mum=0.09989)   # stop dogar
kontrol("8 stop sonrasi pozisyon kapandi", p8.position is None)
kontrol("8 stop ters cevirme engelli (SAR yok)",
        p8.tk_sar is False and p8.tk_hedef != 1)
mask8 = [t.side for t in p8.trades]
kontrol("8 stop sonrasi hic LONG yok", all(s == "SHORT" for s in mask8))

# ------------------------------------------------------------------
# 9) Varlik: banka kapanisi hala calisir (cuzdana yazar)
# ------------------------------------------------------------------
p9 = tk(tk_bank_pct=0.035)
m9 = barlar(60)
ev = yildiz_var(p9, m9, "SAT")
p9.position.tk_stop = 0.0999
p9.position.tk_tp = 0.0
ev = yildiz_var(p9, m9, "SAT", also_mum=0.0960)    # SHORT kâr: fiyat DUSER
kontrol("9 banka kapanisi calisir", p9.position is None and
        any("bank" in (t.exit_reason or "").lower()
            for t in p9.trades))

# ------------------------------------------------------------------
# 10) Kirmizi MUM dokumende short, gri mum: mum-yon capasi SHORT
#     girisini mum-uyusmazligina teslim eder (taze-ST gate): kirmizi
#     yildiz + yukselen mum -> giris BEKLETILIR (TK1 hattinin kapisi)
# ------------------------------------------------------------------
p10 = tk()
m10 = barlar(60)
t10 = int(m10[-1].open_time) + 60_000
m10.append(C(t10, 0.1001, 0.1000))    # yukselen mum
ev = p10.on_price(0.1001, m10, "1m", "SAT")
kontrol("10 yesil mume kirmizi yildiz: giris ertelendi (poz yok)",
        p10.position is None and p10.tk_pend_entry is None)
t10 += 60_000
m10.append(C(t10, 0.1000, 0.1002))    # kirmizi mum: uyusuma tamam
ev = p10.on_price(0.1000, m10, "1m", "SAT")
kontrol("10 kirmizi mume kirmizi yildiz: SHORT acildi",
        p10.position is not None and p10.position.side == "SHORT")

# ------------------------------------------------------------------
# 11) GIRIS DOLUMU (2026-11-06): TİK2 aninda girer (offset 0), TK1
#     pullback limitini korur. Yildiz hesabi degismez.
# ------------------------------------------------------------------
import config as _cfg   # noqa: E402

p11 = PaperTrader("BTCUSDT")
p11.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
              wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
kontrol("11 TİK2 giris offseti 0 (aninda)",
        abs(p11.tk_entry_offset) < 1e-12)
kontrol("11 TİK2 offseti config'ten bagimsiz 0",
        float(getattr(_cfg, "PAPER_TK2_ENTRY_OFFSET", 0.0)) == 0.0)

p11b = PaperTrader("BTCUSDT")
p11b.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
               wallet_fraction=0.8, mode="tk", risk_pct=0.03)
kontrol("11 TK1 pullback offseti KORUNDU (-0.001)",
        abs(p11b.tk_entry_offset - float(_cfg.PAPER_TK_ENTRY_OFFSET)) < 1e-12)

print("-" * 62)
print(f"TAMAM — TİK2 senaryolari gecti")

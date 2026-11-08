# -*- coding: utf-8 -*-
"""TİK2 — KULLANICI KURAL LİSTESİ testi (2026-11-06).

Kullanıcı kuralı:
  * Karar kaynağı `core/tk2_rules.py` kural tablosudur: her satırda
    osilatör(ler) + hareketli ortalama(lar) AYNI yönde ise sinyal.
  * AL = LONG, SAT = SHORT, NÖTR = pozisyonu kapat.
  * Satırlar arası VEYA; aynı barda AL+SAT çakışırsa NÖTR.
  * Pozisyon aç/kapa sonrası bekleme YOK (2026-11-07 kullanıcı kararı).
  * Giriş/çıkış LIMIT (maker) — komisyon düşük.
  * Gösterge hesapları ve grafik üretimi DEĞİŞMEZ.

Not: Bu dosya pytest değil, düz Python betiğidir:
    python test_tk2.py
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, ".")

import numpy as np   # noqa: E402

import config        # noqa: E402
from core import tk2_rules   # noqa: E402
from core.analysis import (OSCILLATOR_LABELS, analyze,   # noqa: E402
                           ma_labels)
from core.paper import PaperTrader   # noqa: E402

_GECEN = 0
_KALAN = 0


class C:
    def __init__(s, t, close, open_):
        s.closed = True
        s.open = open_
        s.open_time = t
        s.close = close
        s.high = max(open_, close) * 1.0001
        s.low = min(open_, close) * 0.9999
        s.volume = 1.0
        s.close_time = t + 59_999


def kontrol(ad, kosul):
    global _GECEN, _KALAN
    if kosul:
        _GECEN += 1
        print("  GECTI ", ad)
    else:
        _KALAN += 1
        print("  KALDI ", ad)


def tk(**kw):
    p = PaperTrader("DOGEUSDT")
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
    p.tk_on = True
    p.tk_tp = 0.0
    p.tk_be = False
    p.tk_require_trend = True       # TİK2'de kapı BYPASS edilmeli
    p.tk_entry_offset = 0.0
    p.tk_pause_bars = 0
    p.tk_streak_n = 0
    p.tk_level_ban = 0.0
    p.tk_bank_pct = 0.0
    p.tk_be_risk = 0.0
    p.tk_time_bars = 0
    p.tk_after_ms = 0.0
    # Yön testleri HAM davranışı ölçer; minimum tutma ayrı bölümde test
    # edilir (bölüm 11).
    p._tk2_min_hold = 0
    p.running = True
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def barlar(n):
    return [C(i * 60_000, 0.1, 0.1002) for i in range(n)]


def yildiz_var(p, m, yildiz, also_mum=None):
    """Yeni bar kapat + tick ver (canlı akış)."""
    t = int(m[-1].open_time) + 60_000
    px = float(m[-1].close) if also_mum is None else float(also_mum)
    m.append(C(t, px, px * 1.0002))
    return p.on_price(px, m, "1m", yildiz)


# ==================================================================
# 1) KURAL TABLOSU: 74 satır, 25 AL / 49 SAT, etiketler geçerli
# ==================================================================
print("1) Kural tablosu")
s = tk2_rules.summary()
kontrol("1.1 74 satır", s["rows"] == 74)
kontrol("1.2 25 AL / 49 SAT", s["al"] == 25 and s["sat"] == 49)
kontrol("1.3 tüm osilatör etiketleri analysis ile uyumlu",
        all(o in OSCILLATOR_LABELS for o in s["oscillators"]))
kontrol("1.4 tüm MA etiketleri analysis ile uyumlu",
        all(m in ma_labels() for m in s["mas"]))
kontrol("1.5 HAREKETLİ HEPSİ = 15 MA",
        len(tk2_rules.MA_GROUPS["ALL"]) == 15)
kontrol("1.6 USTEL+BASIT+HULL = 13 MA",
        len(tk2_rules.MA_GROUPS["EMA"]) +
        len(tk2_rules.MA_GROUPS["SMA"]) +
        len(tk2_rules.MA_GROUPS["HULL"]) == 13)


# ==================================================================
# 2) KURAL SERİSİ: AL / SAT / NÖTR / çakışma
# ==================================================================
print("2) Kural serisi")


def seri(osc_up=(), osc_dn=(), ma_up=(), ma_dn=()):
    """Sentetik kod serisi: verilen kısa adları +1 / -1 yapar."""
    n = 4
    osc = {lab: np.zeros(n, dtype=np.int8) for lab in OSCILLATOR_LABELS}
    ma = {lab: np.zeros(n, dtype=np.int8) for lab in ma_labels()}
    for ad in osc_up:
        osc[tk2_rules.OSC_BY_ALIAS[ad]] = np.full(n, 1, dtype=np.int8)
    for ad in osc_dn:
        osc[tk2_rules.OSC_BY_ALIAS[ad]] = np.full(n, -1, dtype=np.int8)
    for ad in ma_up:
        for lab in tk2_rules.MA_GROUPS[tk2_rules.MA_GROUP_BY_ALIAS[ad]]:
            ma[lab] = np.full(n, 1, dtype=np.int8)
    for ad in ma_dn:
        for lab in tk2_rules.MA_GROUPS[tk2_rules.MA_GROUP_BY_ALIAS[ad]]:
            ma[lab] = np.full(n, -1, dtype=np.int8)
    return tk2_rules.series(osc, ma)


kontrol("2.1 boş kodlar -> NÖTR", seri() == ["NÖTR"] * 4)
kontrol("2.2 EMTIA+HULL sat -> SAT",
        seri(osc_dn=("EMTIA",), ma_dn=("HULL",)) == ["SAT"] * 4)
kontrol("2.3 EMTIA+HULL al -> AL",
        seri(osc_up=("EMTIA",), ma_up=("HULL",)) == ["AL"] * 4)
# Satır 1 (SAT MACD + EMA/SMA/HULL) ile satır 46 (SAT MOMENTUM/MACD + VWMA)
# aynı anda tutabilir; VWMA tek başına yön belirler.
kontrol("2.4 SAT çoklu MA (EMA+SMA+HULL) -> SAT",
        seri(osc_dn=("MACD",),
             ma_dn=("USTEL HAREKETLI", "BASIT HAREKETLI", "HULL"))
        == ["SAT"] * 4)
# ÇAKIŞMA: satır 6 (AL STOKR+WILLIAMS+HULL) ve satır 46 (SAT
# MOMENTUM+MACD+VWMA) aynı barda tutar -> NÖTR.
kontrol("2.5 AL+SAT çakışması -> NÖTR",
        seri(osc_up=("STOKASTIK RSI HIZLI", "WILLIAMS"),
             osc_dn=("MOMENTUM", "MACD"),
             ma_up=("HULL",), ma_dn=("HACIM AGIRLIKLI",))
        == ["NÖTR"] * 4)
# AL satırı eksik bileşen (yalnız HULL) tutmaz.
kontrol("2.6 eksik bileşen -> NÖTR",
        seri(ma_up=("HULL",)) == ["NÖTR"] * 4)


# ==================================================================
# 3) MOTOR: AL=LONG, SAT=SHORT, NÖTR=kapat
# ==================================================================
print("3) Motor yönleri")
p3 = tk()
m3 = barlar(60)
yildiz_var(p3, m3, "AL")
kontrol("3.1 AL -> LONG açıldı",
        p3.position is not None and p3.position.side == "LONG")
n3 = len(p3.trades)
yildiz_var(p3, m3, "AL")
kontrol("3.2 AL devamı: yeni işlem yok",
        len(p3.trades) == n3 and p3.position is not None)
yildiz_var(p3, m3, "SAT")
kontrol("3.3 SAT -> LONG kapandı", p3.position is None)
kontrol("3.4 kapanış kaydı LONG",
        len(p3.trades) == n3 + 1 and p3.trades[-1].side == "LONG")
yildiz_var(p3, m3, "SAT")
kontrol("3.5 SAT -> SHORT açıldı",
        p3.position is not None and p3.position.side == "SHORT")
yildiz_var(p3, m3, "NÖTR")
kontrol("3.6 NÖTR -> SHORT kapandı", p3.position is None)
kontrol("3.7 NÖTR ters pozisyon (LONG) açmadı",
        len(p3.trades) == n3 + 2 and p3.trades[-1].side == "SHORT")


# ==================================================================
# 4) BEKLEME YOK (kullanıcı kararı 2026-11-07)
# ==================================================================
print("4) Bekleme yok (kapatma beklemesi kaldırıldı)")
p4c = PaperTrader("DOGEUSDT")
p4c.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
              wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
kontrol("4.1 configure tk2 -> bekleme 0 sn",
        p4c.tk_after_ms == 0.0 ==
        config.PAPER_TK2_AFTER_SEC * 1000.0)
p4 = tk()
m4 = barlar(60)
yildiz_var(p4, m4, "AL")              # LONG aç (bar T)
kontrol("4.2 ilk LONG açıldı", p4.position is not None)
yildiz_var(p4, m4, "SAT")             # T+1: bekleme yok -> ANINDA kapat
kontrol("4.3 açılıştan 1 dk sonra SAT ANINDA kapatır",
        p4.position is None)
yildiz_var(p4, m4, "SAT")             # T+2: kapanıştan 1 dk sonra
kontrol("4.4 kapanıştan sonraki ilk barda SHORT açıldı",
        p4.position is not None and p4.position.side == "SHORT")


# ==================================================================
# 5) LİMİT (maker) GİRİŞ/ÇIKIŞ: komisyon maker oranında
# ==================================================================
print("5) Maker komisyon")
p5 = tk()
m5 = barlar(60)
yildiz_var(p5, m5, "AL")
fee_bek = p5.position.qty * p5.position.entry * config.PAPER_MAKER_RATE
kontrol("5.1 giriş maker komisyonu",
        abs(p5.position.fee_open - fee_bek) < 1e-9)
yildiz_var(p5, m5, "NÖTR")
t5 = p5.trades[-1]
fee_cik = t5.qty * t5.exit * config.PAPER_MAKER_RATE
kontrol("5.2 çıkış maker komisyonu", abs(t5.fee_close - fee_cik) < 1e-9)


# ==================================================================
# 6) RİBBON/TREND/MUM KAPILARI TİK2'DE BYPASS (kural tek kaynak)
# ==================================================================
print("6) Filtre kapıları bypass")
p6 = tk()
m6 = []
px6 = 0.1
for i in range(300):                  # yükseliş dizilimi (ribbon +1)
    op = px6
    px6 = op * 1.002
    m6.append(C(i * 60_000, px6, op))
kontrol("6.1 ribbon yükseliş", p6._tk_ribbon(m6) == 1)
yildiz_var(p6, m6, "SAT")
kontrol("6.2 yükselişte SAT -> SHORT açılır (kapı yok)",
        p6.position is not None and p6.position.side == "SHORT")
yildiz_var(p6, m6, "AL")              # önce SHORT'u kapatır
kontrol("6.3a AL -> SHORT kapandı", p6.position is None)
yildiz_var(p6, m6, "AL")              # sonraki tick: LONG açar
kontrol("6.3 düşen mumda AL -> LONG açılır (mum kapısı yok)",
        p6.position is not None and p6.position.side == "LONG")


# ==================================================================
# 7) GERİYE DÖNÜK TEST SERİSİ = KURAL SERİSİ (bileşik skor DEĞİL)
# ==================================================================
print("7) Backtest serisi kural kaynağından")
m7 = []
px7 = 100.0
for i in range(320):
    px7 = px7 * (1.0 + 0.0018 * math.sin(i / 7.0) + 0.0003)
    op = m7[-1].close if m7 else px7 * 0.999
    m7.append(C(i * 60_000, px7, op))
res7 = analyze(
    symbol="TESTUSDT", timeframe="1m",
    open_times=[c.open_time for c in m7],
    o=[c.open for c in m7], h=[c.high for c in m7],
    l=[c.low for c in m7], c=[c.close for c in m7],
    v=[c.volume for c in m7],
    close_times=[c.close_time for c in m7])
beklenen = tk2_rules.series_stable(res7.osc_codes, res7.ma_codes)
p7 = tk()
gelen = p7._build_signal_series(m7, "1m")
kontrol("7.1 seri uzunluğu eşit", len(gelen) == len(beklenen))
kontrol("7.2 seri stabilize kural motoruyla birebir aynı", gelen == beklenen)
kontrol("7.3 seride AL ve SAT üretildi",
        "AL" in gelen and "SAT" in gelen)
kontrol("7.4 geçersiz etiket yok",
        all(x in ("AL", "SAT", "NÖTR") for x in gelen))


# ==================================================================
# 8) İZLEME PANELİ EŞLEMESİ: kural kararı grafik sinyaline döner
# ==================================================================
print("8) İzleme eşlemesi")
from core.analysis import Signal            # noqa: E402
from core.service import _LABEL_TO_SIGNAL   # noqa: E402
kontrol("8.1 AL -> BUY", _LABEL_TO_SIGNAL["AL"] is Signal.BUY)
kontrol("8.2 SAT -> SELL", _LABEL_TO_SIGNAL["SAT"] is Signal.SELL)
kontrol("8.3 NÖTR -> NEUTRAL",
        _LABEL_TO_SIGNAL["NÖTR"] is Signal.NEUTRAL)


# ==================================================================
# 9) CANLI SERVİS: mode_signal_series + bar_info TİK2 kuralını gösterir
# ==================================================================
print("9) Canlı servis entegrasyonu")
from core.binance_client import Candle            # noqa: E402
from core.service import MarketService            # noqa: E402

n9 = 90
c9 = np.linspace(100.0, 130.0, n9)
o9 = c9 - 0.4
h9 = c9 + 0.6
l9 = c9 - 0.8
v9 = np.full(n9, 10.0)
ot9 = (np.arange(n9) * 3_600_000).astype(np.int64)
ct9 = ot9 + 3_599_999
res9 = analyze("BTCUSDT", "1h", ot9, o9, h9, l9, c9, v9, ct9)
mums9 = [Candle(open_time=int(ot9[i]), open=float(o9[i]), high=float(h9[i]),
                low=float(l9[i]), close=float(c9[i]), volume=float(v9[i]),
                close_time=int(ct9[i]), closed=True) for i in range(n9)]
svc9 = MarketService(config.Settings(), None)
svc9.paper = PaperTrader("BTCUSDT")
svc9.paper.configure(balance=1000.0, leverage=10, mode="tk2",
                     wallet_fraction=0.8, risk_pct=0.03)
svc9._analyses["1h"] = res9
svc9._buffers["1h"] = mums9
svc9._versions["1h"] = 1
seri9 = svc9.mode_signal_series("1h")
beklenen9 = tk2_rules.series_stable(res9.osc_codes, res9.ma_codes)
kontrol("9.1 mode_signal_series kural serisiyle aynı",
        [x.value for x in seri9] == beklenen9)
bilgi9 = svc9.bar_info("1h", int(ot9[75]))
kontrol("9.2 bar_info tıklanan barın TİK2 kararını verir",
        bilgi9 is not None and bilgi9["mode_signal"] == beklenen9[75])
canli9 = svc9._signal_for_mode(res9, mums9)
kontrol("9.3 canlı sinyal son KAPALI barın kararı",
        canli9 == beklenen9[len(mums9) - 2])
kontrol("9.4 canlı sinyal geçerli etiket",
        canli9 in ("AL", "SAT", "NÖTR"))
canli9b = svc9._signal_for_mode(res9, mums9, "1h")
kontrol("9.5 cache'li seri yolu aynı kararı verir", canli9b == canli9)


# ==================================================================
# 10) HULL GİRİŞ KAPISI (stabilizasyon, 2026-11-07)
# ==================================================================
print("10) HULL giriş kapısı")
kontrol("10.0 HULL etiketi ma_codes ile uyumlu",
        tk2_rules.HULL_LABEL == "Hull Hareketli Ortalama (9)")

# HULL tersken yeni AL açılmaz; HULL aynı yöne dönünce açılır.
_raw10 = ["AL", "AL", "AL", "AL"]
_hull10 = [-1, -1, 1, 1]
_gate10 = tk2_rules.stabilize(_raw10, _hull10, hull_entry_veto=True)
kontrol("10.1 HULL tersken AL girişi engellendi",
        _gate10 == ["NÖTR", "NÖTR", "AL", "AL"])

# HULL nötrken giriş serbesttir (yön belirlemez, engellemez).
kontrol("10.2 HULL nötrken giriş serbest",
        tk2_rules.stabilize(["SAT"], [0], hull_entry_veto=True)
        == ["SAT"])

# Açık pozisyonun çıkışı HULL yüzünden geciktirilmez.
_out10 = tk2_rules.stabilize(["AL", "AL", "NÖTR", "SAT"],
                             [1, 1, -1, -1], hull_entry_veto=True)
kontrol("10.3 çıkış/ters giriş HULL kapısından etkilenmez",
        _out10 == ["AL", "AL", "NÖTR", "SAT"])

# Tam veto (varsayılan kapalı) açık pozisyonu da kapatır: farkı göster.
kontrol("10.4 tam HULL vetosu açık pozisyonu kapatır",
        tk2_rules.stabilize(["AL", "AL", "SAT"], [1, -1, -1],
                            hull_entry_veto=True, hull_veto=True)
        == ["AL", "NÖTR", "SAT"])

# series_stable, kapı kapatılınca ham kural serisine döner.
_ham10 = tk2_rules.series(res7.osc_codes, res7.ma_codes)
_stab10 = tk2_rules.series_stable(res7.osc_codes, res7.ma_codes,
                                  hull_entry_veto=False)
kontrol("10.5 kapı kapalıyken seri ham kural serisine eşit",
        _stab10 == _ham10)


# ==================================================================
# 11) MİNİMUM TUTMA: ters sinyal ilk barda kapatmaz (stop hariç)
# ==================================================================
print("11) Minimum tutma")
p11a = PaperTrader("DOGEUSDT")
p11a.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
               wallet_fraction=0.8, mode="tk2", risk_pct=0.03)
kontrol("11.1 varsayılan minimum tutma 0 (bekleme yok)",
        p11a._tk2_min_hold == 0 == config.PAPER_TK2_MIN_HOLD)

# Ters sinyal (SAT): 1. ve 2. barda pozisyon korunur, 3. barda kapanır.
p11 = tk(_tk2_min_hold=3)
m11 = barlar(60)
yildiz_var(p11, m11, "AL")
kontrol("11.2 LONG açıldı", p11.position is not None)
yildiz_var(p11, m11, "SAT")            # bars_held=1
kontrol("11.3 ters sinyal 1. barda kapatmaz", p11.position is not None)
yildiz_var(p11, m11, "SAT")            # bars_held=2
kontrol("11.4 ters sinyal 2. barda kapatmaz", p11.position is not None)
yildiz_var(p11, m11, "SAT")            # bars_held=3
kontrol("11.5 ters sinyal 3. barda kapatır", p11.position is None)

# NÖTR de aynı kapıya tabidir.
p11b = tk(_tk2_min_hold=3)
m11b = barlar(60)
yildiz_var(p11b, m11b, "AL")
yildiz_var(p11b, m11b, "NÖTR")
kontrol("11.6 NÖTR 1. barda kapatmaz", p11b.position is not None)
yildiz_var(p11b, m11b, "NÖTR")
kontrol("11.7 NÖTR 2. barda kapatmaz", p11b.position is not None)
yildiz_var(p11b, m11b, "NÖTR")
kontrol("11.8 NÖTR 3. barda kapatır", p11b.position is None)

# STOP minimum tutmayı DELER: koruyucu çıkış her zaman anında çalışır.
p11c = tk(_tk2_min_hold=3, tk_sl=0.001, tk_sl_atr=0.0, tk_bank_pct=0.0)
m11c = barlar(60)
yildiz_var(p11c, m11c, "AL")
_t11 = int(m11c[-1].open_time) + 60_000
_px11 = float(m11c[-1].close) * 0.997          # stopun altına düş
m11c.append(C(_t11, _px11, _px11 * 1.0002))
_ev11 = p11c.on_price(_px11, m11c, "1m", "SAT")
kontrol("11.9 stop minimum tutmayı deler (anında kapanır)",
        p11c.position is None and "stop" in (_ev11 or ""))


# ==================================================================
# 12) İŞLEM GÜNLÜĞÜ (logs/islemler.csv)
# ==================================================================
print("12) İşlem günlüğü (CSV)")
_tmp12 = tempfile.mkdtemp(prefix="tik2log_")
_eski_log = config.TRADE_LOG_FILE
config.TRADE_LOG_FILE = os.path.join(_tmp12, "islemler.csv")
try:
    p12 = tk()
    p12.trade_log = True                        # günlüğü zorla aç
    m12 = barlar(60)
    yildiz_var(p12, m12, "AL")
    yildiz_var(p12, m12, "SAT")                 # kapat -> satır yazılmalı
    kontrol("12.1 kapanan canlı işlem dosyaya yazıldı",
            os.path.exists(config.TRADE_LOG_FILE))
    with open(config.TRADE_LOG_FILE, encoding="utf-8") as fh:
        _satirlar = [ln.rstrip("\n").split(";") for ln in fh if ln.strip()]
    kontrol("12.2 başlık + 1 satır", len(_satirlar) == 2)
    _h = _satirlar[0]
    kontrol("12.3 başlıkta yön/giriş/çıkış/kar/komisyon/zaman var",
            all(k in _h for k in ("kapanis_zamani", "acilis_zamani", "yon",
                                  "giris", "cikis", "net_kar", "komisyon")))
    _r = _satirlar[1]
    kontrol("12.4 yön LONG kaydedildi", _r[4] == "LONG")
    kontrol("12.5 zamanlar dolu", len(_r[0]) == 19 and len(_r[1]) == 19)
    kontrol("12.6 komisyon > 0 ve net sayısal",
            float(_r[9]) > 0 and abs(float(_r[10])) >= 0)
    kontrol("12.7 sonuç etiketi geçerli",
            _r[11] in ("KAR", "ZARAR", "BASABAS"))
    # Geriye dönük test / sessiz mod günlüğe YAZMAMALI.
    _once = len(_satirlar)
    p12b = tk()
    p12b._quiet = True                          # backtest bu bayrağı açar
    m12b = barlar(60)
    yildiz_var(p12b, m12b, "AL")
    yildiz_var(p12b, m12b, "SAT")
    with open(config.TRADE_LOG_FILE, encoding="utf-8") as fh:
        _son = len([ln for ln in fh if ln.strip()])
    kontrol("12.8 canlı olmayan işlem günlüğe yazılmaz",
            _son == _once)
finally:
    config.TRADE_LOG_FILE = _eski_log
    try:
        for _f in os.listdir(_tmp12):
            os.remove(os.path.join(_tmp12, _f))
        os.rmdir(_tmp12)
    except OSError:
        pass


print("-" * 60)
print(f"TAMAM — {_GECEN} geçti, {_KALAN} kaldı")
if _KALAN:
    sys.exit(1)

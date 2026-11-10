# -*- coding: utf-8 -*-
"""TİK2 — KULLANICI KURAL TABLOSU testi (2026-11-10).

Kullanıcı kuralı (`list3.xlsx`, BTCUSDT 5m, 158 satır):
  * Karar kaynağı `core/tk2_rules.py` kural tablosudur: her satırda
    osilatör ve hareketli ortalamaların DURUMLARI yazılıdır.
  * AL = LONG aç/koru, SAT = SHORT aç/koru,
    AL-KAPAT = açık LONG'u kapat, SAT-KAPAT = açık SHORT'u kapat.
  * KAPAT satırı yalnızca AYNI yöndeki pozisyon varken uygulanır;
    ters yönde pozisyon açmaz/kapatmaz. Pozisyon yokken atlanır.
  * Satır, yazılan TÜM durumlar aynen sağlandığında geçerlidir;
    yazılmayan göstergeler serbesttir.
  * Birden çok satır tutarsa en çok gösterge belirten (en özel) satır
    kazanır; eşitlikte SONRAKİ satır.
  * Hiçbir satır tutmuyorsa NÖTR.
  * HULL nötr yasağı ve VWMA/HULL birleşik kuralı KAPALI; tablo tek
    karar kaynağıdır.
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
# 1) KURAL TABLOSU: 158 satır (list3.xlsx),
#    50 AL / 54 SAT / 25 AL-KAPAT / 29 SAT-KAPAT
# ==================================================================
print("1) Kural tablosu")
s = tk2_rules.summary()
kontrol("1.1 158 satır", s["rows"] == 158)
kontrol("1.2 50 AL / 54 SAT", s["al"] == 50 and s["sat"] == 54)
kontrol("1.2b 25 AL-KAPAT / 29 SAT-KAPAT",
        s["al_kapat"] == 25 and s["sat_kapat"] == 29)
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
kontrol("1.7 her satırda açık DURUM yazılı", s["state_rules"] == 158)
kontrol("1.8 özgüllük 4..14 gösterge",
        s["specificity"]["min"] == 4 and s["specificity"]["max"] == 14)
kontrol("1.9 tabloda HULL ve HACIM AGIRLIKLI var",
        tk2_rules.HULL_LABEL in s["mas"]
        and tk2_rules.VWMA_LABEL in s["mas"])
kontrol("1.10 NÖTR durumu ayrıştırıldı",
        tk2_rules.RULES[0].ma_pairs()[1]
        == (tk2_rules.HULL_LABEL, 0))
# Excel satır 29: WILLIAMS YUZDE(AL), WILLIAMS(NOTR) aynı gösterge;
# parser son durumu (NÖTR) korur.
kontrol("1.11 aynı gösterge iki kez yazılırsa son durum kazanır",
        (tk2_rules.OSC_BY_ALIAS["WILLIAMS"], 0)
        in tk2_rules.RULES[27].osc_pairs())
# İlk 85 satır (list2.xlsx) korunur; yeni bölüm 87. Excel satırında
# AL-KAPAT ile başlar.
kontrol("1.12 ilk 85 satır korunmuş (sonuncusu AL)",
        tk2_rules.RULES[84].label == "AL")
kontrol("1.13 yeni bölüm KAPAT satırlarıyla başlar",
        tk2_rules.RULES[85].label == "AL-KAPAT"
        and tk2_rules.RULES[87].label == "SAT-KAPAT"
        and tk2_rules.RULES[157].label == "AL-KAPAT")
# Yeni gösterge adları / yazım varyantları çözümlenir.
_osc_alias = tk2_rules.OSC_BY_ALIAS
_ma_alias = tk2_rules.MA_GROUP_BY_ALIAS
kontrol("1.14 GÖRECELİ GÜÇ / ORTALAMA YÖNSEL alias",
        _osc_alias["GORECELI GUC"] in OSCILLATOR_LABELS
        and _osc_alias["ORTALAMA YONSEL"] in OSCILLATOR_LABELS)
kontrol("1.15 ICHIMOKU + tek periyotlu SMA alias",
        _ma_alias["ICHIMOKU"] == "ICHIMOKU"
        and _ma_alias["BASIT HAREKETLI ORTALAMA100"] == "SMA100"
        and _ma_alias["BASIT HAREKTLI ORTALAMA10"] == "SMA10"
        and _ma_alias["BASIT HAREKTLI ORTALAMA200"] == "SMA200")
kontrol("1.16 KAPAT satırları yalnız kendi yönünü kapatır",
        tk2_rules.decide_target("AL-KAPAT", 1) == 0
        and tk2_rules.decide_target("AL-KAPAT", -1) == -1
        and tk2_rules.decide_target("SAT-KAPAT", -1) == 0
        and tk2_rules.decide_target("SAT-KAPAT", 1) == 1
        and tk2_rules.decide_target("AL-KAPAT", 0) == 0)


# ==================================================================
# 2) KURAL SERİSİ: durum eşleşmesi, özgüllük, eşitlikte son satır
# ==================================================================
print("2) Kural serisi")


def kural_kodlari(rule, n=1):
    """Bir kuralın yazdığı durumları koda çevirir; diğerleri NÖTR (0)."""
    osc = {lab: np.zeros(n, dtype=np.int8) for lab in OSCILLATOR_LABELS}
    ma = {lab: np.zeros(n, dtype=np.int8) for lab in ma_labels()}
    for lab, st in rule.osc_pairs():
        osc[lab] = np.full(n, st, dtype=np.int8)
    for lab, st in rule.ma_pairs():
        ma[lab] = np.full(n, st, dtype=np.int8)
    return osc, ma


def seri_kural(rule, n=1, **degistir):
    osc, ma = kural_kodlari(rule, n)
    for lab, st in degistir.items():
        d = osc if lab in osc else ma
        d[lab] = np.full(n, st, dtype=np.int8)
    return tk2_rules.series(osc, ma)


osc_bos = {lab: np.zeros(4, dtype=np.int8) for lab in OSCILLATOR_LABELS}
ma_bos = {lab: np.zeros(4, dtype=np.int8) for lab in ma_labels()}
kontrol("2.1 boş kodlar -> NÖTR",
        tk2_rules.series(osc_bos, ma_bos) == ["NÖTR"] * 4)
# Satır 1: AL | MOMENTUM(AL), MACD(AL) | VWMA(AL), HULL(NÖTR)
kontrol("2.2 satır 1 kendi durumlarıyla AL",
        seri_kural(tk2_rules.RULES[0]) == ["AL"])
# Yazılan durum AYNEN aranır: MOMENTUM SAT yapılırsa satır 1 tutmaz.
kontrol("2.3 yazılan durum bozulunca satır tutmaz",
        seri_kural(tk2_rules.RULES[0],
                   **{tk2_rules.OSC_BY_ALIAS["MOMENTUM"]: -1}) == ["NÖTR"])
# EN ÖZEL SATIR: Excel satır 3 (AL, 5 gösterge) ile satır 56 (SAT, 10
# gösterge) aynı anda tutar; daha özel olan SAT kazanır.
_kontrol3 = tk2_rules.series(*kural_kodlari(tk2_rules.RULES[1]))
kontrol("2.4 en özel satır kazanır (5 AL < 10 SAT)",
        _kontrol3 == ["SAT"])
# EŞİTLİKTE SON SATIR: 79/81/83 aynı deseni paylaşır (SAT, AL, AL);
# aynı özgüllükte sonuncu (AL) kazanır.
kontrol("2.5 eşit özgüllükte son satır kazanır",
        seri_kural(tk2_rules.RULES[79]) == ["AL"])
# Öncelik sırası: özgüllük büyük olan üstte, eşitlikte büyük index üstte.
_prio = tk2_rules._rule_priority()
_ok_prio = True
for _i, _ri in enumerate(tk2_rules.RULES):
    for _j, _rj in enumerate(tk2_rules.RULES):
        if _ri.specificity < _rj.specificity and not _prio[_i] < _prio[_j]:
            _ok_prio = False
        if _ri.specificity == _rj.specificity and _i < _j \
                and not _prio[_i] < _prio[_j]:
            _ok_prio = False
kontrol("2.6 öncelik: özgüllük, eşitlikte satır sırası", _ok_prio)
# Yazılmayan göstergeler serbest: RSI tabloda yok, değişmesi sonucu bozmaz.
kontrol("2.7 yazılmayan göstergeler serbest (wildcard)",
        seri_kural(tk2_rules.RULES[0],
                   **{OSCILLATOR_LABELS[0]: -1}) == ["AL"])


def kural_dizisi(rules):
    """Birden çok kuralı bar bar birleştirir (yazılmayanlar 0)."""
    n = len(rules)
    osc = {lab: np.zeros(n, dtype=np.int8) for lab in OSCILLATOR_LABELS}
    ma = {lab: np.zeros(n, dtype=np.int8) for lab in ma_labels()}
    for i, rule in enumerate(rules):
        for lab, st in rule.osc_pairs():
            osc[lab][i] = st
        for lab, st in rule.ma_pairs():
            ma[lab][i] = st
    return osc, ma


# AL-KAPAT satırı ham (pozisyonsuz) seride etiketini korur.
_osc_k, _ma_k = kural_kodlari(tk2_rules.RULES[85])
kontrol("2.8 ham seride AL-KAPAT etiketi korunur",
        tk2_rules.series(_osc_k, _ma_k) == ["AL-KAPAT"])
# Pozisyon yokken KAPAT satırı uygulanmaz (yeni girişi kilitlemez).
kontrol("2.9 pozisyon yokken AL-KAPAT uygulanmaz",
        tk2_rules.series(_osc_k, _ma_k,
                         track_position=True)[0] != "AL-KAPAT")
# Önce LONG aç, sonra AL-KAPAT koşulu: pozisyon duyarlı seri kapatır.
_osc_k2, _ma_k2 = kural_dizisi([tk2_rules.RULES[0], tk2_rules.RULES[85]])
kontrol("2.10 LONG açıkken AL-KAPAT uygulanır",
        tk2_rules.series(_osc_k2, _ma_k2,
                         track_position=True) == ["AL", "AL-KAPAT"])
# Ters yönde (SHORT) AL-KAPAT uygulanmaz; seri SHORT durumunu korur.
_osc_ks, _ma_ks = kural_dizisi([tk2_rules.RULES[11],
                                tk2_rules.RULES[85]])
_seri_ks = tk2_rules.series(_osc_ks, _ma_ks, track_position=True)
kontrol("2.11 SHORT açıkken AL-KAPAT uygulanmaz",
        _seri_ks[0] == "SAT" and _seri_ks[1] != "AL-KAPAT")


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
# 3b) ÇIKIŞ KARARLARI: AL-KAPAT / SAT-KAPAT (list3.xlsx)
# ==================================================================
print("3b) Kapanış kararları")
p3b = tk()
m3b = barlar(60)
yildiz_var(p3b, m3b, "AL")
kontrol("3b.1 LONG açıldı", p3b.position is not None
        and p3b.position.side == "LONG")
yildiz_var(p3b, m3b, "AL-KAPAT")
kontrol("3b.2 AL-KAPAT açık LONG'u kapattı", p3b.position is None)
kontrol("3b.3 kapanış LONG kaydı",
        len(p3b.trades) == 1 and p3b.trades[-1].side == "LONG")
_n3b = len(p3b.trades)
yildiz_var(p3b, m3b, "AL-KAPAT")
kontrol("3b.4 düz pozisyonda AL-KAPAT yeni işlem açmaz",
        p3b.position is None and len(p3b.trades) == _n3b)
yildiz_var(p3b, m3b, "SAT")
kontrol("3b.5 SHORT açıldı", p3b.position is not None
        and p3b.position.side == "SHORT")
yildiz_var(p3b, m3b, "AL-KAPAT")
kontrol("3b.6 AL-KAPAT açık SHORT'u kapatmaz/ters çevirmez",
        p3b.position is not None and p3b.position.side == "SHORT"
        and len(p3b.trades) == _n3b)
yildiz_var(p3b, m3b, "SAT-KAPAT")
kontrol("3b.7 SAT-KAPAT açık SHORT'u kapattı", p3b.position is None)
kontrol("3b.8 kapanış SHORT kaydı",
        len(p3b.trades) == _n3b + 1 and p3b.trades[-1].side == "SHORT")
_n3b2 = len(p3b.trades)
yildiz_var(p3b, m3b, "AL")
yildiz_var(p3b, m3b, "SAT-KAPAT")
kontrol("3b.9 SAT-KAPAT açık LONG'u kapatmaz",
        p3b.position is not None and p3b.position.side == "LONG"
        and len(p3b.trades) == _n3b2)
yildiz_var(p3b, m3b, "AL-KAPAT")
kontrol("3b.10 AL-KAPAT açık LONG'u kapattı", p3b.position is None)
kontrol("3b.11 KAPAT kararları ters pozisyon açmadı",
        all(t.side in ("LONG", "SHORT") for t in p3b.trades))


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
        all(x in tk2_rules.LABELS for x in gelen))


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
kontrol("8.4 AL-KAPAT -> SELL (LONG kapanışı)",
        _LABEL_TO_SIGNAL["AL-KAPAT"] is Signal.SELL)
kontrol("8.5 SAT-KAPAT -> BUY (SHORT kapanışı)",
        _LABEL_TO_SIGNAL["SAT-KAPAT"] is Signal.BUY)


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
        [x.value for x in seri9]
        == [_LABEL_TO_SIGNAL[k].value for k in beklenen9])
kontrol("9.1b ham TİK2 etiketleri servis cache'inde korunur",
        svc9.tk2_labels("1h") == beklenen9)
bilgi9 = svc9.bar_info("1h", int(ot9[75]))
kontrol("9.2 bar_info tıklanan barın TİK2 kararını verir",
        bilgi9 is not None and bilgi9["mode_signal"]
        == _LABEL_TO_SIGNAL[beklenen9[75]].value)
canli9 = svc9._signal_for_mode(res9, mums9)
kontrol("9.3 canlı sinyal son KAPALI barın kararı",
        canli9 == beklenen9[len(mums9) - 2])
kontrol("9.4 canlı sinyal geçerli TİK2 etiketi",
        canli9 in tk2_rules.LABELS)
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

# series_stable, kapılar kapatılınca ham kural serisine döner.
_ham10 = tk2_rules.series(res7.osc_codes, res7.ma_codes,
                          track_position=True)
_stab10 = tk2_rules.series_stable(res7.osc_codes, res7.ma_codes,
                                  hull_entry_veto=False,
                                  hull_neutral_block=False,
                                  vwma_hull_long=False,
                                  vwma_hull_long_neutral=False,
                                  vwma_hull_short=False)
kontrol("10.5 kapılar kapalıyken seri ham kural serisine eşit",
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


# ==================================================================
# 13) KATMANLAR KAPALI: TABLO TEK KARAR KAYNAĞI (2026-11-09)
# ==================================================================
print("13) HULL/VWMA katmanı kapalı")
kontrol("13.1 config: stabilizasyon kapalı",
        not bool(config.PAPER_TK2_STAB_ON))
kontrol("13.2 config: HULL giriş ve nötr kapıları kapalı",
        not bool(config.PAPER_TK2_STAB_HULL_ENTRY)
        and not bool(config.PAPER_TK2_STAB_HULL_NEUTRAL_BLOCK))
kontrol("13.3 config: VWMA/HULL birleşik kuralı kapalı",
        not bool(config.PAPER_TK2_STAB_VWMA_HULL_LONG)
        and not bool(config.PAPER_TK2_STAB_VWMA_HULL_LONG_NEUTRAL)
        and not bool(config.PAPER_TK2_STAB_VWMA_HULL_HOLD)
        and not bool(config.PAPER_TK2_STAB_VWMA_HULL_ALWAYS)
        and not bool(config.PAPER_TK2_STAB_VWMA_HULL_SHORT))

# Production serisi = ham kural serisi (başka katman karar değiştirmez).
_ham13 = tk2_rules.series(res7.osc_codes, res7.ma_codes,
                          track_position=True)
_ser13p = tk2_rules.series_stable(res7.osc_codes, res7.ma_codes)
kontrol("13.4 production serisi ham kural serisine eşit",
        _ser13p == _ham13)
kontrol("13.5 seride AL ve SAT üretildi",
        "AL" in _ham13 and "SAT" in _ham13)

# HULL(NÖTR) satırları artık tablonun kendisinde tanımlı.
_hull0 = [r for r in tk2_rules.RULES
          if (tk2_rules.HULL_LABEL, 0) in r.ma_pairs()]
kontrol("13.6 HULL(NOTR) satırları tabloda var (AL ve SAT)",
        any(r.direction > 0 for r in _hull0)
        and any(r.direction < 0 for r in _hull0))

# Mekanizma kodu duruyor (test/araştırma); açıkça istenirse çalışır.
_g13 = tk2_rules.stabilize(["AL", "AL", "AL", "AL"], [0, 0, 1, 1],
                           hull_entry_veto=True, hull_neutral_block=True)
kontrol("13.7 HULL nötr kapısı mekanizma olarak çalışıyor",
        _g13 == ["NÖTR", "NÖTR", "AL", "AL"])


# ==================================================================
# 14) HULL + VWMA: KAPALI, MEKANİZMA TESTLERİ
# ==================================================================
print("14) HULL + VWMA birlikte (kapalı)")
# Osilatör çoğunluğu: NÖTR kodlar sayılmaz.
_osc14 = {
    "a": np.asarray([1, 1, 0, 0], dtype=np.int8),
    "b": np.asarray([1, -1, 0, 0], dtype=np.int8),
    "c": np.asarray([0, -1, 0, 0], dtype=np.int8),
}
kontrol("14.1 osilatör çoğunluğu (nötr hariç): AL/SAT/eşit",
        tk2_rules.oscillator_majority(_osc14, 4) == [1, -1, 0, 0])

# Mekanizma: osilatör çoğunluğu AL, HULL SAT, VWMA AL -> SHORT değil LONG.
_raw14 = ["SAT", "NÖTR", "NÖTR", "NÖTR"]
_hull14 = [-1, -1, -1, -1]
_vwma14 = [1, 1, 1, 1]
_omaj14 = [1, 1, 1, 1]
_ov14 = tk2_rules.stabilize(
    _raw14, _hull14, osc_major=_omaj14, vwma=_vwma14,
    vwma_hull_long=True, hull_entry_veto=True)
kontrol("14.2 HULL SAT + VWMA AL + osilatör AL -> LONG",
        _ov14[0] == "AL")
kontrol("14.3 kural kapalıyken ham SAT korunur",
        tk2_rules.stabilize(
            _raw14, _hull14, osc_major=_omaj14, vwma=_vwma14,
            vwma_hull_long=False, hull_entry_veto=True)[0] == "SAT")
kontrol("14.4 osilatör çoğunluğu AL değilse LONG'a çevrilmez",
        tk2_rules.stabilize(
            _raw14, _hull14, osc_major=[0, 0, 0, 0], vwma=_vwma14,
            vwma_hull_long=True, hull_entry_veto=True)[0] == "SAT")
kontrol("14.5 VWMA AL ama HULL NÖTR -> giriş yok (tehlikeli)",
        tk2_rules.stabilize(
            ["AL", "AL", "AL", "AL"], [0, 0, 0, 0],
            osc_major=_omaj14, vwma=_vwma14,
            vwma_hull_long=True, hull_neutral_block=True)
        == ["NÖTR", "NÖTR", "NÖTR", "NÖTR"])

# Production serisi bu birleşik kuralı UYGULAMAZ: ham tablo ne diyorsa o.
_n14 = 4
_osc14p = {lab: np.full(_n14, 1, dtype=np.int8)
           for lab in OSCILLATOR_LABELS}
_osc14p["Emtia Kanal Endeksi(CCI) (20)"] = np.full(
    _n14, -1, dtype=np.int8)
_osc14p[tk2_rules.OSC_BY_ALIAS["MOMENTUM"]] = np.full(
    _n14, -1, dtype=np.int8)
_ma14p = {lab: np.full(_n14, 1, dtype=np.int8) for lab in ma_labels()}
_ma14p[tk2_rules.HULL_LABEL] = np.full(_n14, -1, dtype=np.int8)
_ma14p[tk2_rules.VWMA_LABEL] = np.full(_n14, 1, dtype=np.int8)
kontrol("14.6 production serisi ham tablo serisine eşit",
        tk2_rules.series_stable(_osc14p, _ma14p)
        == tk2_rules.series(_osc14p, _ma14p, track_position=True))


print("-" * 60)
print(f"TAMAM — {_GECEN} geçti, {_KALAN} kaldı")
if _KALAN:
    sys.exit(1)

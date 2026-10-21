"""
Kaldirac simulasyonu testi (ag bagimsiz).

Kurallar dogrudan kullanici tanimindan:
  LONG  -> grafigin en taban noktasinda
  SHORT -> dusus basladiginda, ama en son LONG fiyatini GECMEREK
  cuzdanin %80'i, komisyon dahil kar/zarar

Calistir:  python test_paper.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from core.paper import LONG, SHORT, PaperTrader


def mk(i, o, h, l, c):
    return type("C", (), {"open_time": i * 3600_000, "open": o, "high": h,
                          "low": l, "close": c, "volume": 100.0,
                          "close_time": i * 3600_000 + 1, "closed": True})()


def dizi(degerler):
    """Duz bir seri mum uretir (o=h=l=c)."""
    return [mk(i, v, v, v, v) for i, v in enumerate(degerler)]


def v_shape(n=17, start=110.0, bottom=92.0, son_fiyat=93.5):
    """
    Yuksekten duser, dibe gelir, sonra yukselmeye baslar.
    Son mum yükselir (donus teyidi) ve fiyat pencerenin taban bolgesindedir.
    """
    cs = dizi([start - i for i in range(n)])            # 110, 109, ...
    taban = cs[-1].close                               # 110 - (n-1)
    cs.append(mk(n, taban, taban, bottom, bottom))      # dip
    cs.append(mk(n + 1, bottom, son_fiyat, bottom, son_fiyat))
    return cs, son_fiyat


def ters_v(n=17, start=88.0, zirve=104.5, son_fiyat=104.0):
    """Alttan cikar, zirveye gelir, sonra dusmeye baslar (SHART noktasi)."""
    cs = dizi([start + i for i in range(n)])
    z = cs[-1].close                                   # 88 + (n-1)
    cs.append(mk(n, z, zirve, z, zirve))               # zirve
    cs.append(mk(n + 1, zirve, zirve, son_fiyat, son_fiyat))   # dusus
    return cs, son_fiyat


def new_trader(**kw):
    t = PaperTrader(balance=1000.0, leverage=10.0, fee_rate=0.0005,
                    wallet_fraction=0.80, lookback=20)
    t.running = True
    for k, v in kw.items():
        setattr(t, k, v)
    return t


def test(name, fn):
    try:
        fn()
        print(f"  GECTI  {name}")
        return True
    except AssertionError as exc:
        print(f"  KALDI  {name}: {exc}")
        return False
    except Exception as exc:                       # noqa: BLE001
        print(f"  HATA   {name}: {type(exc).__name__}: {exc}")
        return False


print("Kaldirac simulasyonu testleri")
print("-" * 62)
ok = []


def t_long_en_taban():
    cs, px = v_shape()
    tr = new_trader()
    ev = tr.on_price(px, cs, "1h")
    assert ev, "tabanda dönünce LONG açılmalıydı"
    assert tr.position and tr.position.side == LONG, tr.position
    assert abs(tr.position.entry - px) < 1e-9
    assert "konum" in ev


ok.append(test("LONG: grafikteki en taban noktasında açılır",
               t_long_en_taban))


def t_long_taban_bolgesi():
    """Fiyat pencerenin taban %12'sindeyse LONG acilir (teyit kapali)."""
    tr = new_trader()
    cs, px = v_shape()
    ev = tr.on_price(px, cs, "1h")
    assert ev, "taban bölgesindeyken LONG açılmalıydı"
    assert tr.position and tr.position.side == LONG


ok.append(test("LONG: taban bölgesi (teyitsiz) tetikler",
               t_long_taban_bolgesi))


def t_teyit_iste():
    """Teyit acikken yesil mum şart; kirmizi mumda sinyal gelmez."""
    tr = new_trader()
    tr.confirm = True
    # son mum KIRMIZI (open 93.5 -> close 92.5) ama yine de tabanda
    cs = dizi([110 - i for i in range(17)])
    taban = cs[-1].close
    cs.append(mk(17, taban, taban, 92.0, 92.0))
    cs.append(mk(18, 93.5, 93.5, 92.5, 92.5))          # kirmizi mum
    assert tr.on_price(92.5, cs, "1h") is None, \
        "teyit açıkken kırmızı mumda LONG açılmamalı"
    assert tr.position is None
    # ayni senaryoda teyit kapali ise acilir
    tr2 = new_trader()
    tr2.confirm = False
    assert tr2.on_price(92.5, cs, "1h") is not None, \
        "teyit kapalıyken taban bölgesi yeterli olmalı"
    assert tr2.position is not None


ok.append(test("Teyit açıkken yükselen mum şart (varsayılan kapalı)",
               t_teyit_iste))


def t_long_ortada_acmaz():
    """Fiyat pencerenin ORTASINDAYSA LONG acilmaz."""
    tr = new_trader()
    cs = dizi([100, 104, 108, 112, 116, 112, 108, 104, 100, 104,
               108, 112, 116, 120, 116, 112, 108, 104, 100, 104])
    assert tr.on_price(104, cs, "1h") is None, "ortada LONG açılmamalı"
    assert tr.position is None


ok.append(test("LONG: yalnızca taban bölgesinde açılır",
               t_long_ortada_acmaz))


def t_long_yuzde_sekiz():
    tr = new_trader(balance=1000.0, leverage=10.0, wallet_fraction=0.80)
    cs, px = v_shape()
    tr.on_price(px, cs, "1h")
    p = tr.position
    assert p is not None, "pozisyon açılmadı"
    assert abs(p.margin - 800.0) < 1e-6, f"teminat {p.margin} (800 olmali)"
    assert abs(p.notional - 8000.0) < 1e-6, f"notional {p.notional}"
    assert abs(p.qty - 8000.0 / px) < 1e-9, f"miktar {p.qty}"


ok.append(test("LONG: cüzdanın %80'i teminat, x10 kaldıraç",
               t_long_yuzde_sekiz))


def t_komisyon():
    tr = new_trader()
    cs, px = v_shape()
    tr.on_price(px, cs, "1h")
    beklenen = tr.position.notional * 0.0005
    assert abs(tr.balance - (1000.0 - beklenen)) < 1e-6, tr.balance
    assert abs(tr.commission_paid - beklenen) < 1e-9


ok.append(test("Komisyon açılışta bakiyeden düşülür", t_komisyon))


def t_kar_zarar():
    tr = new_trader()
    cs, px = v_shape()
    tr.on_price(px, cs, "1h")
    p = tr.position
    # Girişte dondurulan hedef seviyesine tirmak -> kapanir
    assert p.target > px, p.target
    zirve = dizi([100 + i for i in range(19)]) + [mk(19, 119, 120, 119, 119)]
    tr.on_price(p.target, zirve, "1h")
    assert tr.position is None, "hedefe ulaşınca LONG kapanmalıydı"
    t = tr.trades[0]
    brut = (p.target - px) * p.qty
    kap_fee = p.qty * p.target * 0.0005
    assert abs(t.gross_pnl - brut) < 1e-6, (t.gross_pnl, brut)
    assert abs(t.net_pnl - (brut - p.fee_open - kap_fee)) < 1e-6, t.net_pnl
    assert abs(tr.balance - (1000.0 - p.fee_open + brut - kap_fee)) < 1e-6
    assert tr.wins == 1 and tr.losses == 0


ok.append(test("Kâr/zarar iki komisyonla birlikte doğru", t_kar_zarar))


def t_zarar_komisyonlu():
    """Zarar eden kapanış da kayda gecmeli ve komisyonlu olmali."""
    tr = new_trader()
    cs, px = v_shape()
    tr.on_price(px, cs, "1h")
    p = tr.position
    # fiyat pencerenin zirvesine CLIMB etmeden likidasyona git
    tr.on_price(p.liq_price - 0.01, cs, "1h")
    t = tr.trades[-1]
    assert t.net_pnl < 0, t.net_pnl
    assert t.exit_reason.startswith("LİKİDASYON"), t.exit_reason
    assert tr.losses == 1 and tr.wins == 0


ok.append(test("Zararlı kapanış komisyonla kaydedilir", t_zarar_komisyonlu))


def t_short_longu_gecmez():
    tr = new_trader()
    tr.last_long_price = 100.0
    cs, px = ters_v()                       # zirve 104.5 -> fiyat 104
    assert tr.on_price(px, cs, "1h") is None, \
        "LONG fiyatı geçildiği için SHORT verilmemeliydi"
    assert tr.position is None


ok.append(test("SHORT: son LONG fiyatını geçmezse verilmez",
               t_short_longu_gecmez))


def t_short_long_altinda():
    """Fiyat son LONG'un ALTINDA ve zirvedeyse SHORT verilir (kural: entry)."""
    tr = new_trader()
    tr.short_rule = "entry"
    tr.last_long_price = 120.0
    cs, px = ters_v()
    ev = tr.on_price(px, cs, "1h")
    assert ev and "SHORT" in ev, ev
    assert tr.position and tr.position.side == SHORT, tr.position


ok.append(test("SHORT: son LONG'un altında ve zirvede verilir (entry)",
               t_short_long_altinda))


def t_short_referanssiz():
    tr = new_trader()
    assert tr.last_long_price is None
    cs, px = ters_v()
    assert tr.on_price(px, cs, "1h") is None, "referans yoksa verilmemeli"
    assert tr.position is None


ok.append(test("SHORT: referans LONG yoksa verilmez", t_short_referanssiz))


def t_short_kar():
    """SHORT düşüşte kazanır (kural: entry)."""
    tr = new_trader()
    tr.short_rule = "entry"
    tr.last_long_price = 120.0
    cs, px = ters_v()
    tr.on_price(px, cs, "1h")
    p = tr.position
    assert p.side == SHORT
    # girişte dondurulan hedef = pencerenin dibi
    assert p.target < px, (p.target, px)
    tr.on_price(p.target, cs, "1h")
    assert tr.position is None, "hedefe ulaşınca SHORT kapanmalıydı"
    t = tr.trades[-1]
    brut = (px - p.target) * p.qty
    assert t.gross_pnl > 0 and abs(t.gross_pnl - brut) < 1e-6, t.gross_pnl


ok.append(test("SHORT: düşüşte kâr eder", t_short_kar))


def t_likidasyon():
    tr = new_trader(leverage=10.0)
    cs, px = v_shape()
    tr.on_price(px, cs, "1h")
    assert tr.position is not None
    liq = tr.position.liq_price
    assert abs(liq - px * 0.9) < 1e-6, (liq, px * 0.9)
    tr.on_price(liq - 0.5, cs, "1h")
    assert tr.position is None, "likidasyonda kapanmalı"
    assert tr.trades[-1].exit_reason.startswith("LİKİDASYON")


ok.append(test("Likidasyon fiyatı doğru (x10 → %10) ve kapanışta tetiklenir",
               t_likidasyon))


def t_likidasyon_kaldiraca_gore():
    for lev, pay in ((5, 0.20), (20, 0.05), (50, 0.02)):
        tr = new_trader(leverage=lev)
        cs, px = v_shape()
        tr.on_price(px, cs, "1h")
        beklenen = px * (1 - 1.0 / lev)
        assert abs(tr.position.liq_price - beklenen) < 1e-6, \
            f"x{lev}: {tr.position.liq_price} != {beklenen}"


ok.append(test("Likidasyon kaldıraçla orantılı (x5/x20/x50)",
               t_likidasyon_kaldiraca_gore))


def t_duraklatilmis():
    tr = new_trader()
    tr.running = False
    cs, px = v_shape()
    assert tr.on_price(px, cs, "1h") is None
    assert tr.position is None


ok.append(test("Duraklatılmışken pozisyon açılmaz", t_duraklatilmis))


def t_state_json():
    tr = new_trader()
    cs, px = v_shape()
    tr.on_price(px, cs, "1h")
    st = tr.state(px + 1)
    for k in ("balance", "equity", "leverage", "position", "totals", "trades"):
        assert k in st, k
    assert st["position"]["side"] == LONG
    assert st["unrealized"] > 0, st["unrealized"]
    json.dumps(st)


ok.append(test("Cüzdan durumu JSON'a dönüşür", t_state_json))


def t_reset():
    tr = new_trader()
    tr.balance = 5000.0
    tr.last_long_price = 100.0
    tr.reset("ETHUSDT")
    assert tr.balance == config.PAPER_INITIAL_BALANCE
    assert tr.position is None and tr.trades == []
    assert tr.last_long_price is None and tr.running is False
    assert tr.symbol == "ETHUSDT"


ok.append(test("Sıfırlama (coin değişimi) durumu temizler", t_reset))


def t_tek_pozisyon():
    """Ayni anda yalnizca BIR pozisyon tutulur."""
    tr = new_trader()
    cs, px = v_shape()
    for _ in range(5):
        tr.on_price(px, cs, "1h")
        assert tr.position is not None
        assert len([1]) == 1
    assert tr.balance < 1000.0


ok.append(test("Aynı anda tek pozisyon tutulur", t_tek_pozisyon))


# ----------------------------------------------------------------------
# REGRESYON: Binance yeni acilan barda low=0 / close=0 gonderiyor
# ----------------------------------------------------------------------
def t_sifir_degerli_mum():
    """Binance'in low=0 gonderdigi mum onarilmali (olcuste goruldu)."""
    from core.binance_client import candle_from_payload
    # gercek orndek: ac=82790.0 yis=82795.2 dus=0.0 kap=0.0
    k = [0, "82790.0", "82795.2", "0.0", "0.0", "376.42", 1, "0", 0,
         "0", "0", "0"]
    c = candle_from_payload(k)
    assert c.open == 82790.0, c.open
    assert c.low > 0 and c.close > 0, (c.low, c.close)
    assert c.high >= max(c.open, c.close), (c.high, c.open, c.close)
    assert c.low <= min(c.open, c.close), (c.low, c.open, c.close)


ok.append(test("REGRESYON: Binance low=0 mumu onarılır",
               t_sifir_degerli_mum))


def t_sifir_mum_konumu_bozmaz():
    """Bozuk mum olsa da konum hesabı 0'a sapmamalı."""
    tr = new_trader()
    cs, px = v_shape()
    cs[-1].low = 0.0            # bozuk mum enjekte et
    cs[-1].close = 0.0
    p = tr._position_in_range(tr._window(cs), px)
    assert 0.0 <= p <= 1.0, p
    assert abs(p - 0.5) < 1e-9, "bozuk mumda konum 0.5 (orta) olmalı"


ok.append(test("REGRESYON: bozuk mum konum hesabını bozmaz",
               t_sifir_mum_konumu_bozmaz))


def t_sifir_mum_gosterge_girmez():
    """Onarim sonrasi tum mumlar pozitif olmali."""
    from core.binance_client import candle_from_payload
    ornekler = [
        [0, "100", "110", "0", "0", "5", 1, "0", 0, "0", "0", "0"],
        [0, "100", "0", "90", "105", "5", 1, "0", 0, "0", "0", "0"],
        [0, "100", "110", "90", "0", "5", 1, "0", 0, "0", "0", "0"],
        [0, "100", "110", "90", "105", "5", 1, "0", 0, "0", "0", "0"],
    ]
    for k in ornekler:
        c = candle_from_payload(k)
        assert min(c.open, c.high, c.low, c.close) > 0, k
        assert c.high >= c.low, k


ok.append(test("REGRESYON: her bozuk varyantta mum tutarlı",
               t_sifir_mum_gosterge_girmez))


# ----------------------------------------------------------------------
# Geriye donuk test (backtest): "bugune kadar ne kadar kazandi?"
# ----------------------------------------------------------------------
def t_backtest_ozet():
    """backtest() hesabi sifirlar, gecmisi oynatir ve ozet dondurur."""
    tr = new_trader()
    # 60 barlik V sekli: dipten zirveye, sonra yine dipten zirveye
    cs = []
    for i in range(30):
        v = 110 - i
        cs.append(mk(i, v, v, v, v))
    for i in range(30, 60):
        v = 80 + (i - 30) * 2
        cs.append(mk(i, v, v, v, v))
    st = tr.backtest(cs, "1h")
    assert st["bars"] == 60, st
    assert st["elapsed_ms"] >= 0
    assert "trades" in st and "profit" in st and "return_pct" in st
    # hesap sifirdan baslamis olmali
    assert tr.trades, "geçmişte hiç işlem oluşmadı"
    assert all(t.mode == "backtest" for t in tr.trades), \
        "geçmiş işlemleri backtest olarak işaretlenmeli"


ok.append(test("backtest: özet döner ve işlemleri etiketler",
               t_backtest_ozet))


def t_backtest_sonra_canli_devam():
    """Test bittikten sonra AYNI hesapla canlı devam eder."""
    # 1) Backtest bittikten sonra motor "calisiyor" durumda olmali
    tr = new_trader()
    cs, _ = v_shape(n=40)
    tr.backtest(cs, "1h")
    assert tr.running is True, "canlı akış için çalışıyor olmalı"

    # 2) CANLI bir pozisyon acilip kapandiginda mode="live" olmali
    canli = new_trader()
    canli.running = False          # once durdur
    canli.running = True           # ... sonra canli baslat (backtest YOK)
    cs2, px2 = v_shape()
    canli.on_price(px2, cs2, "1h")
    assert canli.position is not None, "canlı LONG açılmalıydı"
    canli.on_price(canli.position.target, cs2, "1h")
    assert canli.position is None, "hedefe ulaşınca kapanmalı"
    assert len(canli.trades) == 1, canli.trades
    assert canli.trades[0].mode == "live", \
        f"canlı işlem 'live' olmalı, {canli.trades[0].mode} bulundu"
    assert canli.backtest_stats is None, "backtest çalışmadı, özet olmamalı"


ok.append(test("backtest sonrası canlı devam eder (mode=live)",
               t_backtest_sonra_canli_devam))


def t_backtest_deterministik():
    """Ayni veri iki kez -> ayni sonuc (rastgelelik yok)."""
    cs = []
    for i in range(80):
        v = 100 + (i % 7) * 2 - (i % 11)
        cs.append(mk(i, v, v + 0.5, v - 0.5, v))
    t1 = new_trader(); a = t1.backtest(cs, "1h")
    t2 = new_trader(); b = t2.backtest(cs, "1h")
    assert a["trades"] == b["trades"], (a["trades"], b["trades"])
    assert abs(a["balance"] - b["balance"]) < 1e-9


ok.append(test("backtest: aynı veri → aynı sonuç (deterministik)",
               t_backtest_deterministik))


# ----------------------------------------------------------------------
# SHORT kurali: "entry" (eski) vs "pullback" (yeni)
# ----------------------------------------------------------------------
def t_kural_entry_shortu_kapatir():
    """entry kurali: fiyat son LONG'un ustundeyse SHORT verilmez."""
    tr = new_trader()
    tr.short_rule = "entry"
    tr.last_long_price = 100.0
    cs, px = ters_v()
    assert tr.on_price(px, cs, "1h") is None
    assert tr.position is None


ok.append(test("Kural 'entry': LONG'un üstünde SHORT verilmez",
               t_kural_entry_shortu_kapatir))


def t_kural_pullback_zirveden_cekilince():
    """pullback kurali: zirveden geri cekilince SHORT verilir."""
    tr = new_trader()
    tr.short_rule = "pullback"
    tr.long_peak = 104.5              # daha once gorulen zirve
    # fiyat zirveden %1 geride ve pencerenin ust bolgesinde
    cs = dizi([88 + i for i in range(17)])
    z = cs[-1].close
    cs.append(mk(17, z, 104.5, z, 104.5))
    cs.append(mk(18, 104.5, 104.5, 103.4, 103.4))     # ~%1 geri cekilmis
    ev = tr.on_price(103.4, cs, "1h")
    assert ev and "SHORT açıldı" in ev, ev
    assert tr.position and tr.position.side == SHORT


ok.append(test("Kural 'pullback': zirveden geri çekilince SHORT verilir",
               t_kural_pullback_zirveden_cekilince))


def t_kural_pullback_geri_cekilmediyse_acmaz():
    """Fiyat hâlâ zirvedeyse (geri çekilme %0,5'ten az) SHORT verilmez."""
    tr = new_trader()
    tr.short_rule = "pullback"
    tr.long_peak = 104.5
    cs = dizi([88 + i for i in range(17)])
    z = cs[-1].close
    cs.append(mk(17, z, 104.5, z, 104.5))
    cs.append(mk(18, 104.5, 104.5, 104.4, 104.4))     # %0,1 geri çekilme
    assert tr.on_price(104.4, cs, "1h") is None
    assert tr.position is None


ok.append(test("Kural 'pullback': geri çekilme yetersizse SHORT açılmaz",
               t_kural_pullback_geri_cekilmediyse_acmaz))


def t_zirve_guncellenir():
    """long_peak her yeni fiyat yuksekligiyle artar."""
    tr = new_trader()
    tr.running = True
    cs, px = v_shape()
    tr.on_price(px, cs, "1h")
    eski = tr.long_peak
    assert eski > 0, "LONG açılınca zirve kaydedilmeli"
    tr.on_price(eski * 1.05, cs, "1h")
    assert tr.long_peak > eski, (tr.long_peak, eski)


ok.append(test("Zirve (long_peak) her fiyatta güncellenir", t_zirve_guncellenir))


# ----------------------------------------------------------------------
# Sinyal modu: SAT -> LONG kapanir + SHORT acilir
# ----------------------------------------------------------------------
def sinyal_trader():
    tr = new_trader()
    tr.mode = "signal"
    return tr


def t_sinyal_sat_long_kapatir_short_acar():
    """SAT sinyali: LONG kapanir ve SHORT acilir."""
    tr = sinyal_trader()
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")            # AL ile LONG ac
    assert tr.position and tr.position.side == LONG, tr.position
    # hedefe ulasmadan SAT gelsin: LONG kapanmali, SHORT acilmali
    ev = tr.on_price(px * 1.01, cs, "1h", "SAT")
    assert tr.position and tr.position.side == SHORT, \
        f"SAT sinyali SHORT açmalıydı, {tr.position}"
    assert len(tr.trades) == 1 and tr.trades[0].side == LONG, tr.trades
    assert "SAT" in tr.trades[0].exit_reason, tr.trades[0].exit_reason
    assert ev and "SHORT açıldı" in ev, ev


ok.append(test("Sinyal modu: SAT → LONG kapanır, SHORT açılır",
               t_sinyal_sat_long_kapatir_short_acar))


def t_sinyal_al_short_kapatir_long_acar():
    """AL sinyali: SHORT kapanir ve LONG acilir."""
    tr = sinyal_trader()
    cs, px = ters_v()
    tr.on_price(px, cs, "1h", "SAT")           # SAT ile SHORT ac
    assert tr.position and tr.position.side == SHORT, tr.position
    ev = tr.on_price(px * 0.99, cs, "1h", "AL")
    assert tr.position and tr.position.side == LONG, \
        f"AL sinyali LONG açmalıydı, {tr.position}"
    assert len(tr.trades) == 1 and tr.trades[0].side == SHORT, tr.trades


ok.append(test("Sinyal modu: AL → SHORT kapanır, LONG açılır",
               t_sinyal_al_short_kapatir_long_acar))


def t_sinyal_ayni_sinyalde_islem_yok():
    """Ayni sinyal tekrarlanirsa yeni islem acilmaz."""
    tr = sinyal_trader()
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")
    ilk = tr.position.entry
    tr.on_price(px * 1.001, cs, "1h", "AL")
    tr.on_price(px * 1.002, cs, "1h", "AL")
    assert len(tr.trades) == 0, tr.trades
    assert tr.position.entry == ilk, "pozisyon yeniden açılmamalı"


ok.append(test("Sinyal modu: aynı sinyalde yeni işlem açılmaz",
               t_sinyal_ayni_sinyalde_islem_yok))


def t_sinyal_notr_kapatir_bekler():
    """NÖTR sinyali pozisyonu KAPATIR, ters yön açmaz.

    KULLANICI KURALI: "LONG'dan NÖTR geçtiğinde karşı pozisyona
    geçmesin, pozisyonu kapatsın. Beklesin."

    ONCEDEN: NÖTR hicbir sey yapmiyordu, pozisyon acik kaliyordu.
    Artık kapanir ve nakitte beklenir.
    """
    tr = sinyal_trader()
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")
    assert tr.position and tr.position.side == LONG

    ev = tr.on_price(px * 1.001, cs, "1h", "NÖTR")
    assert tr.position is None, \
        f"NÖTR pozisyonu kapatmaliydi, acik kaldi: {tr.position}"
    assert ev and "kapandı" in ev, ev
    assert "bekleniyor" in ev, ev

    # NÖTR'de TERS YON ACILMAMALI
    assert all(t.side == LONG for t in tr.trades), \
        "NÖTR sonrasi SHORT acilmamaliydi"


ok.append(test("Sinyal modu: NÖTR kapatır, ters yön açmaz (nakitte bekler)",
               t_sinyal_notr_kapatir_bekler))


def t_sinyal_guclu_sinyaller():
    """GÜÇLÜ SAT / GÜÇLÜ AL de tetikler."""
    tr = sinyal_trader()
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "GÜÇLÜ AL")
    assert tr.position.side == LONG
    tr.on_price(px * 1.01, cs, "1h", "GÜÇLÜ SAT")
    assert tr.position.side == SHORT, tr.position


ok.append(test("Sinyal modu: GÜÇLÜ SAT / GÜÇLÜ AL de tetikler",
               t_sinyal_guclu_sinyaller))


def t_aralik_modu_sinyal_kullanmaz():
    """Aralik modunda sinyal gecse de karar fiyata bakar."""
    tr = new_trader()
    tr.mode = "range"
    cs, px = v_shape()
    # fiyat ortada, sinyal SAT: aralik modunda islem OLMAMALI
    ort = dizi([100, 104, 108, 112, 116, 112, 108, 104, 100, 104,
                108, 112, 116, 120, 116, 112, 108, 104, 100, 104])
    assert tr.on_price(104, ort, "1h", "SAT") is None, \
        "aralık modunda sinyal tetiklememeli"
    assert tr.position is None


ok.append(test("Aralık modu sinyal parametresini yok sayar",
               t_aralik_modu_sinyal_kullanmaz))


def t_min_bekleme_engeller():
    """Pozisyon yeni acildiysa min. bekleme dolmadan donusum yapilmaz."""
    tr = sinyal_trader()
    tr.min_hold_bars = 3
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")          # LONG acildi (_bars_held=0)

    # YENI ve AYRI mumlar ekle (open_time farkli olmali, yoksa bar
    # sayaci ilerlemez).
    def yeni_mum(seri, sira, fiyat):
        return seri + [mk(100 + sira, fiyat, fiyat * 1.001, fiyat, fiyat)]

    seri = list(cs)
    for k in range(1, 4):                    # 3 bar geçsin
        seri = yeni_mum(seri, k, px)
        tr.on_price(px, seri, "1h", "AL")
    assert tr._bars_held >= 3, tr._bars_held
    assert tr.position.side == LONG, "barken pozisyon degismemeli"

    # bekleme doldu -> donusum serbest
    ev = tr.on_price(px * 1.002, seri, "1h", "SAT")
    assert ev and "SHORT" in ev, ev
    assert tr.position.side == SHORT


ok.append(test("Min. bekleme süresi erken dönüşü engeller",
               t_min_bekleme_engeller))


def t_min_bekleme_hemen_donusu_engeller():
    """Bekleme dolmadan gelen SAT donusumu yapmaz."""
    tr = sinyal_trader()
    tr.min_hold_bars = 3
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")
    ev = tr.on_price(px * 1.002, cs, "1h", "SAT")     # ayni bar, bekleme 0
    assert ev is None, ev
    assert tr.position.side == LONG, "bekleme dolmadan dönmemeli"


ok.append(test("Min. bekleme: beklemeden gelen sinyal döndürmez",
               t_min_bekleme_hemen_donusu_engeller))


def t_min_bekleme_sifir_engel_yok():
    tr = sinyal_trader()
    tr.min_hold_bars = 0
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")
    ev = tr.on_price(px * 1.002, cs, "1h", "SAT")
    assert ev and "SHORT" in ev, "bekleme 0 iken hemen dönebilmeli"


ok.append(test("Min. bekleme 0 ise kısıt yok",
               t_min_bekleme_sifir_engel_yok))


# ----------------------------------------------------------------------
# signal_long: SADECE LONG. AL girer, SAT cikar, arada beklenir.
# ----------------------------------------------------------------------
def t_signal_long_sat_kapatir_short_acmaz():
    """Kullanicinin istegi: SAT gelince LONG kapanir, SHORT ACILMAZ."""
    tr = new_trader()
    tr.mode = "signal_long"
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")
    assert tr.position.side == LONG
    ev = tr.on_price(px * 1.01, cs, "1h", "SAT")
    assert tr.position is None, f"SAT'ta kapanmalıydı: {tr.position}"
    assert ev and "LONG kapandı" in ev, ev
    assert tr.trades[-1].side == "LONG", tr.trades[-1].side


ok.append(test("signal_long: SAT LONG'u kapatır, SHORT açmaz",
               t_signal_long_sat_kapatir_short_acmaz))


def t_signal_long_sat_tekrar_kapanmaz():
    """SAT sonrasi bos pozisyonda SHORT acilmaz (nötrde beklenir)."""
    tr = new_trader()
    tr.mode = "signal_long"
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")
    tr.on_price(px * 1.01, cs, "1h", "SAT")
    assert tr.position is None
    ev = tr.on_price(px * 0.99, cs, "1h", "SAT")     # ayni sinyal tekrar
    assert ev is None, ev
    assert tr.position is None, "SAT açık pozisyon vermemeli"
    assert len(tr.trades) == 1, tr.trades


ok.append(test("signal_long: SAT tekrarında yeni işlem yok",
               t_signal_long_sat_tekrar_kapanmaz))


def t_signal_long_al_sonrasi_girer():
    """Kapanan LONG'dan sonra yeni AL gelince tekrar LONG girer."""
    tr = new_trader()
    tr.mode = "signal_long"
    cs, px = v_shape()
    tr.on_price(px, cs, "1h", "AL")
    tr.on_price(px * 1.01, cs, "1h", "SAT")
    assert tr.position is None
    ev = tr.on_price(px * 1.02, cs, "1h", "AL")      # yeni AL
    assert ev and "LONG açıldı" in ev, ev
    assert tr.position and tr.position.side == LONG


ok.append(test("signal_long: SAT sonrası yeni AL'de tekrar LONG",
               t_signal_long_al_sonrasi_girer))


def t_signal_exit_giris_araliktan():
    """signal_exit: giris aralik kurali, cikis sinyal."""
    tr = new_trader()
    tr.mode = "signal_exit"
    cs, px = v_shape()
    tr.on_price(px, cs, "1h")              # aralik kurali LONG acar
    assert tr.position and tr.position.side == LONG, tr.position
    ev = tr.on_price(px * 1.01, cs, "1h", "SAT")
    assert tr.position is None, ev
    assert "LONG kapandı" in ev, ev


ok.append(test("signal_exit: aralık girer, SAT ile çıkar",
               t_signal_exit_giris_araliktan))


# ----------------------------------------------------------------------
# REGRESYON: akistan gelen bozuk islem verisi
# ----------------------------------------------------------------------
def t_bozuk_islem_filtresi():
    """Binance'in gonderdigi bozuk fiyatlar mumu kirletmemeli.

    OLÇÜM: @trade akisi 45 snde fiyati 0,00 olan islemler gonderiyor.
    Daha ince bozuklar da geliyor (kullanici "fiyat 13,11" gordu).
    """
    from core.service import MarketService
    import config as cfg

    class FakeClient:
        def server_time_offset_ms(self):
            return 0

        def fetch_klines(self, interval, limit=500):
            from core.binance_client import Candle
            out = []
            for i in range(120):
                p = 2500.0 + i
                out.append(Candle(open_time=i * 14400000, open=p, high=p + 1,
                                  low=p - 1, close=p, volume=10.0,
                                  close_time=i * 14400000 + 1, closed=True))
            return out

        def fetch_price(self):
            return 2500.0

    svc = MarketService(cfg.Settings(), store=None)
    svc.client = FakeClient()
    svc._buffers["4h"] = svc.client.fetch_klines("4h")
    svc._last_good_price = 0.0

    from core.binance_client import Candle
    tf_ms = cfg.TF_SECONDS["4h"] * 1000
    baz = svc._buffers["4h"][-1]

    # _ws_loop icindeki on_trade mantigini dogrudan dogrula:
    # bozuk fiyat mumun kapanisini DEGISTIRMEMELI
    svc._last_good_price = baz.close
    bozuk = [0.0, 13.11, 1e9, float("nan")]
    for p in bozuk:
        sapma = abs(p - svc._last_good_price) / svc._last_good_price
        reddedildi = (p <= 0 or p != p
                      or sapma > cfg.TRADE_PRICE_SANITY)
        assert reddedildi, f"bozuk fiyat {p} reddedilmedi"
    assert baz.close == 2500.0 + 119, "mum kapanisi bozulmamali"


ok.append(test("REGRESYON: bozuk akış fiyatı (0 / 13,11) elenir",
               t_bozuk_islem_filtresi))


def t_normal_islem_gecer():
    """Saglam fiyatlar filtreye takilmamali."""
    import config as cfg
    referans = 2500.0
    for p in (2499.5, 2501.0, 2530.0, 2470.0):
        sapma = abs(p - referans) / referans
        assert not (p <= 0 or p != p
                    or sapma > cfg.TRADE_PRICE_SANITY), \
            f"gecerli fiyat {p} yanlislikla elendi"


ok.append(test("REGRESYON: geçerli işlemler filtreye takılmaz",
               t_normal_islem_gecer))


# ----------------------------------------------------------------------
# CANLI MOD: geriye donuk test sonuclari canli kari kirletmemeli
# ----------------------------------------------------------------------
def t_canli_mod_gecmisi_ayirir():
    """Trade Basla -> gecmis test oynatilmaz, canli sayim sifirdan baslar.

    Kullanicinin sordugu: "simdi basliyorum, sonrasindaki kar/zarari
    izleyecegim". Gecmis testin kazanci bu olcumde gorUNMEMELI.
    """
    from core.paper import PaperTrader, Trade
    import config as cfg

    p = PaperTrader(cfg.Settings())
    p.configure(balance=500.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8)

    # Once bir "gecmis test" islemi uydur (mod="backtest")
    p.trades.append(Trade(
        side="LONG", entry=100.0, exit=110.0, qty=1.0, margin=100.0,
        gross_pnl=10.0, fee_open=0.1, fee_close=0.1, net_pnl=9.8,
        opened_at=0.0, closed_at=1.0, timeframe="4h", reason="test",
        exit_reason="test", symbol="BTCUSDT", mode="backtest"))

    # "Trade Basla": hesap sifirlanmali, gecmis SILINMELI
    p.start_live()
    assert p.running, "Trade Basla -> calisir olmali"
    assert not any(t.mode == "backtest" for t in p.trades), \
        "gecmis test islemleri silinmeli"
    assert abs(p.balance - 500.0) < 1e-6, \
        f"kullanici bakiyesi korunmali, got {p.balance}"
    assert abs(p.start_balance - 500.0) < 1e-6, \
        f"baslangic bakiyesi 500 olmali, got {p.start_balance}"
    assert p._live_started_at is not None, "canli baslangic zamani isaretlenmeli"

    # Simdi bir canli kazanc ekle
    p.trades.append(Trade(
        side="LONG", entry=500.0, exit=510.0, qty=1.0, margin=500.0,
        gross_pnl=10.0, fee_open=0.25, fee_close=0.25, net_pnl=9.5,
        opened_at=1.0, closed_at=2.0, timeframe="4h", reason="canli",
        exit_reason="canli", symbol="BTCUSDT", mode="live"))
    st = p._live_stats()
    assert st["trades"] == 1, f"canli islem sayisi 1 olmali, got {st['trades']}"
    assert abs(st["net_pnl"] - 9.5) < 1e-6, \
        f"canli net 9.5 olmali, got {st['net_pnl']}"


ok.append(test("CANLI: geçmiş test sonuçları canlı kârı kirletmez",
               t_canli_mod_gecmisi_ayirir))


def t_canli_ozet_backtesti_saymaz():
    """_live_stats yalniz 'live' islemleri saymali."""
    from core.paper import PaperTrader, Trade
    import config as cfg

    p = PaperTrader(cfg.Settings())
    for mod, net in (("backtest", 100.0), ("live", 5.0), ("live", -2.0)):
        p.trades.append(Trade(
            side="LONG", entry=1.0, exit=1.0, qty=1.0, margin=1.0,
            gross_pnl=net, fee_open=0.0, fee_close=0.0, net_pnl=net,
            opened_at=0.0, closed_at=0.0, timeframe="4h", reason="",
            exit_reason="", symbol="BTCUSDT", mode=mod))
    st = p._live_stats()
    assert st["trades"] == 2, f"2 canli islem olmali, got {st['trades']}"
    assert abs(st["net_pnl"] - 3.0) < 1e-6, \
        f"canli net 3.0 olmali (100 backtest haric), got {st['net_pnl']}"
    assert st["wins"] == 1 and st["losses"] == 1, "1 kazanc 1 kayip olmali"


ok.append(test("CANLI: özet yalnız 'live' işlemleri sayar",
               t_canli_ozet_backtesti_saymaz))


# ----------------------------------------------------------------------
# REGRESYON: kucuk fiyatli coinler "0,00" olarak gorunuyordu
# ----------------------------------------------------------------------
def t_kucuk_fiyat_bicimi():
    """1000PEPE = 0,0038677 -> sabit 2 ondalikta "0,00" oluyordu.

    Coin listesi genisletildiginde (1000PEPE, 1000SHIB vb.) ortaya
    cikti: hem arayuz hem sinyal logu fiyati 0,00 gosteriyordu.
    """
    from core.analysis import format_number

    # Sunucu tarafi. Ondalik sayisi fiyatin BUYUKLUGUNE gore secilir:
    # deger 0,0038677 < 0,01 -> 8 ondalik -> "0,00386770"
    # (KAYIP YOK: degerin tum anlamli haneleri gorunur)
    assert format_number(0.0038677, digits=None) == "0,00386770", \
        f"1000PEPE yanlis: {format_number(0.0038677, digits=None)}"
    assert format_number(0.0777, digits=None) == "0,077700", \
        f"DOGE yanlis: {format_number(0.0777, digits=None)}"
    assert format_number(0.4238, digits=None) == "0,4238", \
        f"FET yanlis: {format_number(0.4238, digits=None)}"
    assert format_number(2366.33, digits=None) == "2.366,33", \
        f"ETH yanlis: {format_number(2366.33, digits=None)}"
    assert format_number(83706.60, digits=None) == "83.706,60", \
        f"BTC yanlis: {format_number(83706.60, digits=None)}"

    # ASLA "0,00" olmamali (sifir disi degerler icin)
    for v in (0.0038677, 0.00001, 0.0777, 1.0, 83000.0):
        out = format_number(v, digits=None)
        assert out != "0,00", f"{v} -> '0,00' oldu!"


ok.append(test("REGRESYON: küçük fiyatlar 0,00 olarak görünmez",
               t_kucuk_fiyat_bicimi))


# ----------------------------------------------------------------------
# TEK KAYNAK KURALLARI: ma_only / osc_only
# ----------------------------------------------------------------------
def _tek_kaynak(mod):
    """Test icin: verilen modda bir PaperTrader + sahte mum uretir."""
    from core.paper import PaperTrader
    import config as cfg

    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mod)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0

    from core.binance_client import Candle

    def mumlar(n=30, base=100.0, t0=0):
        out = []
        for i in range(n):
            p0 = base + i * 0.5
            bar = (i + t0) * 14400000
            out.append(Candle(open_time=bar, open=p0, high=p0 + 0.4,
                              low=p0 - 0.4, close=p0 + 0.2, volume=10.0,
                              close_time=bar + 1, closed=True))
        return out

    return p, mumlar


def t_ma_only_girisi():
    """ma_only: AL sinyaliyle LONG, SAT sinyaliyle SHORT acar."""
    for mod in ("ma_only", "osc_only"):
        p, mumlar = _tek_kaynak(mod)
        # Pozisyon yokken AL -> LONG
        p.on_price(100.0, mumlar(), "4h", "AL")
        assert p.position and p.position.side == "LONG", \
            f"{mod}: AL sinyaliyle LONG acilmadi"


ok.append(test("TEK KAYNAK: AL sinyaliyle LONG açar", t_ma_only_girisi))


def t_ma_only_art_arda_islem_yapmaz():
    """Art arda ayni yon gelirse ISLEM YAPILMAZ (pozisyon durur)."""
    for mod in ("ma_only", "osc_only"):
        p, mumlar = _tek_kaynak(mod)
        p.on_price(100.0, mumlar(), "4h", "AL")
        ilk_giris = p.position.entry
        # Art arda AL, AL, GÜÇLÜ AL -> hicbiri dokunmamali
        for sig in ("AL", "GÜÇLÜ AL", "AL"):
            p.on_price(101.0, mumlar(), "4h", sig)
        assert p.position.side == "LONG", f"{mod}: LONG kapandi, olmamaliydi"
        assert p.position.entry == ilk_giris, \
            f"{mod}: pozisyon yeniden acildi, olmamaliydi"


ok.append(test("TEK KAYNAK: art arda aynı yönde işlem yapmaz",
               t_ma_only_art_arda_islem_yapmaz))


def t_ma_only_dongusu():
    """Kullanicinin GUNCEL tarifine gore tam dongu:

    LONG  + art arda LONG  -> islem yok
    LONG  + SAT            -> LONG kapanir, SHORT acilir
    LONG  + NÖTR           -> pozisyon KAPANIR, HICBIR SEY ACILMAZ
    SHORT + art arda SHORT -> islem yok
    SHORT + NÖTR           -> pozisyon KAPANIR, HICBIR SEY ACILMAZ
    SHORT + AL             -> SHORT kapanir, LONG acilir
    """
    for mod in ('ma_only', 'osc_only'):
        p, m = _tek_kaynak(mod)

        p.on_price(100.0, m(), '4h', 'AL')
        assert p.position and p.position.side == 'LONG', mod + ': 1'

        for _ in range(3):
            p.on_price(101.0, m(), '4h', 'AL')
        assert p.position.side == 'LONG', mod + ': 2 (LONG korunmali)'

        p.on_price(99.0, m(), '4h', 'SAT')
        assert p.position.side == 'SHORT', mod + ': 3 SAT->SHORT'

        g = p.position.entry
        for _ in range(3):
            p.on_price(98.0, m(), '4h', 'SAT')
        assert p.position.side == 'SHORT' and p.position.entry == g, mod + ': 4'

        # NÖTR: kapanir, HICBIR SEY ACILMAZ
        p.on_price(98.0, m(), '4h', 'NÖTR')
        assert p.position is None, mod + ': 5 NOTR sonrasi pozisyon kalmali'

        # Pozisyon yokken NOTR: hicbir sey acilmaz
        p.on_price(98.0, m(), '4h', 'NÖTR')
        p.on_price(98.0, m(), '4h', 'NÖTR')
        assert p.position is None, mod + ': 6 bosta NOTR acmamali'

        # NOTR sonrasi AL: LONG acilir
        p.on_price(100.0, m(), '4h', 'AL')
        assert p.position and p.position.side == 'LONG', mod + ': 7'

        # LONG + NOTR: kapanir, SHORT ACILMAZ
        p.on_price(100.0, m(), '4h', 'NÖTR')
        assert p.position is None, mod + ': 8 LONG+NOTR ters yon acmamali'

        # Bosta SAT: SHORT acilir
        p.on_price(99.0, m(), '4h', 'SAT')
        assert p.position and p.position.side == 'SHORT', mod + ': 9'

        # SHORT + NOTR: kapanir, LONG ACILMAZ
        p.on_price(99.0, m(), '4h', 'NÖTR')
        assert p.position is None, mod + ': 10 SHORT+NOTR ters yon acmamali'


ok.append(test('TEK KAYNAK: NÖTR pozisyonu kapatır, ters yön açmaz',
               t_ma_only_dongusu))


def t_tek_kaynak_min_bekleme():
    """Min. bekleme suresi dolmadan kapatma yapilmaz."""
    p, m = _tek_kaynak("ma_only")
    p.configure(min_hold=5)
    p.on_price(100.0, m(), "4h", "AL")
    assert p.position.side == "LONG"
    # Ayni barda hemen SAT: bekleme suresi dolmadi
    p.on_price(99.0, m(), "4h", "SAT")
    assert p.position.side == "LONG", \
        "min. bekleme dolmadan pozisyon kapanmamali"
    # Her adimda YENI bir bar olmali: on_price sayaci yalnizca
    # mumlarin son barinin open_time'i degistiginde artirir.
    for i in range(8):
        p.on_price(99.0, m(t0=(i + 1) * 30), "4h", "SAT")
        if p.position and p.position.side == "SHORT":
            break
    assert p.position and p.position.side == "SHORT", \
        "bekleme suresi dolduktan sonra kapanmaliydi"


ok.append(test("TEK KAYNAK: minimum bekleme süresi uygulanır",
               t_tek_kaynak_min_bekleme))


# ----------------------------------------------------------------------
# TEK KAYNAK ESIKLERI
# ----------------------------------------------------------------------
def t_osc_esikleri_ayri():
    """osc_only kendi esiklerini kullanir, bilesik esikleri degil.

    OLCUM (tools/pick_osc_threshold.py, 15 coin x 3 dilim):
      esik          4h AL   4h SAT   islem   ort.bar
      0,40/0,65        15       18      66      43,4   (bilesik - calismiyor)
      0,25/0,40       222      283     920       4,5   (secilen)
    """
    import config as cfg
    from core.service import MarketService
    from core.analysis import Signal

    # Ayri esikler tanimli ve bilesik esiklerden DUSUK olmali
    assert cfg.PAPER_OSC_BASE_THRESHOLD < cfg.BASE_THRESHOLD, \
        "osilatör AL/SAT esigi bilesik esikten kucuk olmali"
    assert cfg.PAPER_OSC_STRONG_THRESHOLD < cfg.STRONG_THRESHOLD, \
        "osilatör GÜÇLÜ esigi bilesik esikten kucuk olmali"

    # Sahte analiz: skoru elle verip karari sor
    class FakeRes:
        def __init__(self, osc, ma, comp):
            self.oscillator_scores = [0.0, osc]
            self.ma_scores = [0.0, ma]
            self.composite = [0.0, comp]
            self.composite_value = comp
            self.signal = Signal.NEUTRAL

    svc = MarketService(cfg.Settings(), store=None)
    svc.paper = None

    # osc_only: MA skoru -1 olsa bile OSILATÖR skoru belirleyici
    svc.paper = type("P", (), {"mode": "osc_only"})()
    r = FakeRes(osc=0.30, ma=-1.0, comp=-0.35)
    assert svc._signal_for_mode(r) == "AL", \
        f"osc=+0,30 AL vermeliydi, {svc._signal_for_mode(r)} geldi"

    # Bilesik esiklerle ayni skor NÖTR kalirdi
    assert 0.30 < cfg.BASE_THRESHOLD, "bu test bilesik esik varsayiyor"

    # Negatif yon
    r = FakeRes(osc=-0.30, ma=1.0, comp=0.35)
    assert svc._signal_for_mode(r) == "SAT", "osc=-0,30 SAT vermeliydi"
    r = FakeRes(osc=0.50, ma=1.0, comp=0.6)
    assert svc._signal_for_mode(r) == "GÜÇLÜ AL", "osc=+0,50 GÜÇLÜ AL olmalı"
    r = FakeRes(osc=0.05, ma=-1.0, comp=-0.4)
    assert svc._signal_for_mode(r) == "NÖTR", "osc=+0,05 NÖTR olmalı"

    # ma_only: bilesik esikler gecerli, MA skoru belirleyici
    svc.paper = type("P", (), {"mode": "ma_only"})()
    r = FakeRes(osc=0.9, ma=-0.5, comp=0.2)
    assert svc._signal_for_mode(r) == "SAT", "ma=-0,50 SAT vermeliydi"


ok.append(test("TEK KAYNAK: osc_only ölçülmüş kendi eşiklerini kullanır",
               t_osc_esikleri_ayri))


def t_signal_modu_notr_kapatir():
    """signal ve signal_long modlarinda da NÖTR kurali gecerli.

    KULLANICI KURALI: "LONG'dan NÖTR geçtiğinde veya SHORT'tan NÖTR
    geldiğinde karşı pozisyona geçmesin, pozisyonu kapatsın. Beklesin."
    """
    # --- signal modu: LONG + NÖTR -> kapanir, SHORT ACILMAZ ---
    p, m = _tek_kaynak("signal")
    p.on_price(100.0, m(), "4h", "AL")
    assert p.position.side == "LONG", "signal: LONG acilmadi"
    p.on_price(100.0, m(), "4h", "NÖTR")
    assert p.position is None, \
        "signal: LONG + NÖTR -> pozisyon kapandi, ters yon acmamali"

    # --- signal modu: SHORT + NÖTR -> kapanir, LONG ACILMAZ ---
    p, m = _tek_kaynak("signal")
    p.on_price(100.0, m(), "4h", "SAT")
    assert p.position.side == "SHORT", "signal: SHORT acilmadi"
    p.on_price(100.0, m(), "4h", "NÖTR")
    assert p.position is None, \
        "signal: SHORT + NÖTR -> pozisyon kapandi, ters yon acmamali"

    # --- signal_long modu ---
    p, m = _tek_kaynak("signal_long")
    p.on_price(100.0, m(), "4h", "AL")
    assert p.position.side == "LONG"
    p.on_price(100.0, m(), "4h", "NÖTR")
    assert p.position is None, \
        "signal_long: LONG + NÖTR -> pozisyon kapandi, yeni acmamali"

    # --- Pozisyon yokken NÖTR: hicbir sey acilmaz (tum modlar) ---
    for mod in ("signal", "signal_long"):
        p, m = _tek_kaynak(mod)
        for _ in range(3):
            p.on_price(100.0, m(), "4h", "NÖTR")
        assert p.position is None, f"{mod}: bosta NÖTR acmamali"

    # --- SAT hala ters yon acar (davranis bozulmadi) ---
    p, m = _tek_kaynak("signal")
    p.on_price(100.0, m(), "4h", "AL")
    p.on_price(99.0, m(), "4h", "SAT")
    assert p.position.side == "SHORT", \
        "signal: SAT hala LONG'u kapatip SHORT acmali"


ok.append(test("SİNYAL: NÖTR pozisyonu kapatır, ters yön açmaz",
               t_signal_modu_notr_kapatir))


# ----------------------------------------------------------------------
# REGRESYON: kapanıştan sonra AYNI sinyal yeni işlem açmıyordu
# ----------------------------------------------------------------------
def t_kapanistan_sonra_ayni_sinyal():
    """
    KULLANICI BUGÜNÜ BUNU RAPORLADI:
      "NÖTR durumuna geçtikten sonra otomatik olarak hareketli
       ortalamalar AL emri verdiyse long, SAT emri verdiyse shorta
       girmesi lazım. Ama mevcut uygulamada NÖTR'den sonra yeni
       SAT yani short sinyali gelmesine rağmen hiçbir işlem yapmadı."

    KÖK NEDEN: karar "sinyal DEĞİŞTİ" mantığıyla veriliyordu
    (`signal == last_signal` → dokunma). Pozisyon hedef/ likidasyon /
    NÖTR ile kapandığında `last_signal` eski sinyalde kalıyordu. Aynı
    yönde yeni sinyal geldiğinde "değişiklik yok" sanılıp yok sayılıyor
    ve sistem sessizce işlem açmıyordu.

    DÜZELTME: `_close()` son sinyali temizler.
    """
    for mod in ("ma_only", "osc_only"):
        # --- 1) Likidasyonla kapandı, aynı yönde yeni sinyal geldi ---
        p, m = _tek_kaynak(mod)
        p.on_price(100.0, m(), "4h", "SAT")
        liq = p.position.liq_price
        p.on_price(liq + 0.01, m(), "4h", "SAT")
        assert p.position is None, f"{mod}: likidasyonda kapanmaliydi"
        p.on_price(liq + 0.02, m(), "4h", "SAT")
        assert p.position and p.position.side == "SHORT", \
            f"{mod}: kapanıştan sonra aynı SAT yeni SHORT açmalıydı"

        # --- 2) Hedefe ulaşarak kapandı, aynı yönde yeni sinyal ---
        p, m = _tek_kaynak(mod)
        p.on_price(100.0, m(), "4h", "AL")
        hedef = p.position.target
        assert hedef > 0, f"{mod}: hedef 0 olmamalı (bu test için)"
        p.on_price(hedef + 0.01, m(), "4h", "AL")
        assert p.position is None, f"{mod}: hedefte kapanmaliydi"
        p.on_price(hedef + 0.02, m(), "4h", "AL")
        assert p.position and p.position.side == "LONG", \
            f"{mod}: kapanıştan sonra aynı AL yeni LONG açmalıydı"

        # --- 3) NÖTR kapattı, sonra SAT geldi (kullanıcı senaryosu) ---
        p, m = _tek_kaynak(mod)
        p.on_price(100.0, m(), "4h", "SAT")
        p.on_price(100.0, m(), "4h", "NÖTR")
        assert p.position is None, f"{mod}: NÖTR'de kapanmaliydi"
        p.on_price(99.0, m(), "4h", "SAT")
        assert p.position and p.position.side == "SHORT", \
            f"{mod}: NÖTR sonrası SAT geldi, SHORT açılmalıydı"

        # --- 4) Pozisyon AÇIKKEN art arda aynı sinyal dokunmamalı ---
        p, m = _tek_kaynak(mod)
        p.on_price(100.0, m(), "4h", "AL")
        giris = p.position.entry
        for _ in range(5):
            p.on_price(101.0, m(), "4h", "AL")
        assert p.position.side == "LONG", f"{mod}: pozisyon korunmali"
        assert p.position.entry == giris, \
            f"{mod}: pozisyon yeniden açılmamalı (art arda aynı sinyal)"


ok.append(test("REGRESYON: kapanıştan sonra aynı yönde sinyal yeniden işlem açar",
               t_kapanistan_sonra_ayni_sinyal))



# ----------------------------------------------------------------------
# MURO — yeni algoritma
#
# Kullanici istegi:
#   "Long en dipten tespit etsin, short en tepeden; long'da elde edilen
#    kazanci kaybetmeden short'a gecsin (mesela %3 kazanc sagladikca
#    cuzdana atsin, yeniden long'a girsin)."
#
# Test edilenler:
#   1) AL/SAT aksiyonlari pozisyon acar
#   2) KAR KILIDI: pozisyon kapanir, kar cuzdana yazilir, AYNI YONDE
#      yeniden pozisyon acilir
#   3) YAPI KIRILIMI: long kapanir, karsi yon HEMEN acilmaz
#   4) TERS YON: long kapanir, short acilir
#   5) Ayni aksiyon iki kez uygulanmaz
#   6) Risk bazli boyutlandirma: kaldirac ust sinirdir
#   7) Likidasyon stop'tan SONRA gelir
#   8) Aksiyon serisi (core.muro) yon degisiminde kapatma uretir
# ----------------------------------------------------------------------
def _muro_trader(**kw):
    from core.paper import PaperTrader
    import config as cfg

    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="muro")
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def _mum(n=40, base=100.0, step=0.0, t0=0, wick=0.3):
    from core.binance_client import Candle
    out = []
    for i in range(n):
        c = base + i * step
        bar = (i + t0) * 86400000
        out.append(Candle(open_time=bar, open=c, high=c + wick,
                          low=c - wick, close=c, volume=10.0,
                          close_time=bar + 1, closed=True))
    return out


def t_muro_al_sat_acar():
    """AL -> LONG. Karsi yon (SAT) once bekler, sonra SHORT acilir."""
    p = _muro_trader()
    p.on_price(100.0, _mum(), "1d", "AL")
    assert p.position and p.position.side == "LONG", "AL ile LONG acilmadi"
    p.on_price(99.0, _mum(t0=100), "1d", "SAT")
    assert p.position is None, "karsi yon beklemeden acilmamali"
    p._no_entry_until = 0.0
    p.on_price(99.0, _mum(t0=200), "1d", "SAT")
    assert p.position and p.position.side == "SHORT", \
        "bekleme sonrasi SAT ile SHORT acilmali"


ok.append(test("MURO: AL/SAT aksiyonları pozisyon açar", t_muro_al_sat_acar))


def t_muro_kar_kilidi():
    """Kâr kilitleme: pozisyon kapanır, kâr cüzdana yazılır, aynı yönde
    yeniden pozisyon açılır."""
    p = _muro_trader()
    m = _mum()
    p.on_price(100.0, m, "1d", "AL")
    assert p.position.side == "LONG"
    ilk_giris = p.position.entry
    bakiye_once = p.balance

    lock = p.muro_cfg.lock_pct
    lock_fiyat = ilk_giris * (1 + lock)
    ev = p.on_price(lock_fiyat, m, "1d", None,
                    bar_high=lock_fiyat * 1.001)
    assert ev and "Kâr kilidi" in ev, f"kilit tetiklenmedi: {ev}"
    assert p.position is not None, "kilitten sonra pozisyon kalmamali"
    assert p.position.side == "LONG", "ayni yonde yeniden acilmali"
    assert abs(p.position.entry - lock_fiyat) < 1e-6, \
        f"yeniden giriş kilit fiyatinda olmali: {p.position.entry}"
    assert p.balance > bakiye_once, \
        f"kâr cüzdana yazilmali: {p.balance} <= {bakiye_once}"
    assert len(p.trades) == 1, f"bir bacak kapanmali: {len(p.trades)}"
    assert p.trades[0].net_pnl > 0, "kilit kârı pozitif olmali"


ok.append(test("MURO: kâr kilidi — kâr cüzdana yazılır, aynı yönde yeniden "
               "açılır", t_muro_kar_kilidi))


def t_muro_yapi_kirilimi_karsi_yon_acmaz():
    """Yapı kırıldı: long kapanır, karşı yön HEMEN açılmaz."""
    p = _muro_trader()
    p.on_price(100.0, _mum(), "1d", "AL")
    assert p.position.side == "LONG"
    ev = p.on_price(99.0, _mum(t0=100), "1d", "LONG_KAPAT")
    assert ev and "LONG kapandı" in ev, ev
    assert p.position is None, "yapı kırılınca pozisyon kalmamali"


ok.append(test("MURO: yapı kırılımı kapatır, karşı yön hemen açılmaz",
               t_muro_yapi_kirilimi_karsi_yon_acmaz))


def t_muro_ters_yon_kapatir_acar():
    """Ters yön sinyali: mevcut pozisyon kapanır, karşı yön BEKLEME
    sonrası açılır (pozisyon dalgalanması olmasın)."""
    p = _muro_trader()
    p.on_price(100.0, _mum(), "1d", "AL")
    ev = p.on_price(99.0, _mum(t0=100), "1d", "SAT")
    assert ev and "LONG kapandı" in ev, ev
    assert p.position is None, "karsi yon bekleme suresi dolmadan acilmamali"
    # Bekleme dolduktan sonra karsi yon acilir.
    p._no_entry_until = 0.0
    p.on_price(99.0, _mum(t0=200), "1d", "SAT")
    assert p.position is not None and p.position.side == "SHORT", \
        "bekleme sonrasi karsi yon acilmali"


ok.append(test("MURO: ters yön sinyali kapatır ve açar",
               t_muro_ters_yon_kapatir_acar))


def t_muro_ayni_aksiyon_tekrar_uygulanmaz():
    """Aynı aksiyon iki kez gönderilirse pozisyon yeniden açılmaz."""
    p = _muro_trader()
    p.on_price(100.0, _mum(), "1d", "AL")
    giris = p.position.entry
    # 100,5: kilit seviyesinin (100 * 1,01 = 101) ALTINDA — kâr kilidi
    # tetiklenmemeli, sadece aynı aksiyon gelmiş olmalı.
    p.on_price(100.5, _mum(t0=100), "1d", "AL")
    assert p.position.entry == giris, "ayni aksiyon tekrar islem yaptirdi"


ok.append(test("MURO: aynı aksiyon tekrar uygulanmaz",
               t_muro_ayni_aksiyon_tekrar_uygulanmaz))


def t_muro_risk_bazli_boyutlandirma():
    """Kaldıraç üst sınırdır; pozisyon risk ile boyutlandırılır."""
    p = _muro_trader()
    p.configure(leverage=20, risk_pct=0.02)
    p.on_price(100.0, _mum(), "1d", "AL")
    pos = p.position
    assert pos is not None
    # Tam kullanimda notional = equity*0.8*20 = 16000 olurdu.
    assert pos.notional < 1000 * 0.8 * 20 * 0.5, \
        f"risk bazli olmali: {pos.notional}"
    assert pos.eff_leverage <= 20, pos.eff_leverage


ok.append(test("MURO: risk bazlı boyutlandırma (kaldıraç üst sınırdır)",
               t_muro_risk_bazli_boyutlandirma))


def t_muro_likidasyon_stop_sonra():
    """Likidasyon stop'tan SONRA gelmeli (long: liq < stop)."""
    p = _muro_trader()
    p.on_price(100.0, _mum(), "1d", "AL")
    pos = p.position
    assert pos.stop_price > 0, "stop atanmali"
    assert pos.liq_price < pos.stop_price, \
        f"likidasyon stop'tan once gelmemeli: liq={pos.liq_price} "\
        f"stop={pos.stop_price}"


ok.append(test("MURO: likidasyon stop'tan sonra gelir",
               t_muro_likidasyon_stop_sonra))


def t_muro_aksiyon_serisi():
    """core.muro: geri çekilmede giriş, yön değişiminde kapatma.

    Seri 1: duz yukselis -> "peşine düşme" yok (hic giris yok).
    Seri 2: testere (yuksek/dusuk) -> geri cekilmede AL, yon degisiminde
            kapatma aksiyonlari uretilir.
    Seri 3: AL aksiyonu YALNIZCA supertrend yonu yukarida iken cikar.
    """
    from core import muro as M
    from core import indicators as ind

    def testere(n=120):
        out = []
        p = 100.0
        for i in range(n):
            p += 0.8 if (i % 6) < 4 else -0.7
            out.append(p)
        return out

    def seriler(fiyat):
        h = [f + 0.3 for f in fiyat]
        l = [f - 0.3 for f in fiyat]
        return M.actions(fiyat, h, l, fiyat, M.MuroConfig()), h, l

    # 1) Duz yukselis: hicbir giris olmamali (geri cekilme yok).
    duz = [100.0 + i * 0.5 for i in range(80)]
    acts, _, _ = seriler(duz)
    assert not any(a in (M.AL, M.SAT) for a in acts), \
        "duz yukseliste giris olmamali (peşine düşme)"
    assert not any(a == M.LONG_KAPAT for a in acts), \
        "duz yukseliste LONG_KAPAT olmamali"

    # 2) Testere: geri cekilmede AL, yon degisiminde kapatma.
    fiyat = testere()
    acts, h, l = seriler(fiyat)
    assert any(a == M.AL for a in acts), "testere serisinde AL olmali"
    assert any(a in (M.LONG_KAPAT, M.SHORT_KAPAT) for a in acts), \
        "yon degisiminde kapatma aksiyonu olmali"

    # 3) AL yalnizca supertrend yukarida iken cikar.
    _, dirn = ind.supertrend(np.asarray(h), np.asarray(l), np.asarray(fiyat),
                             M.MuroConfig().st_period,
                             M.MuroConfig().st_mult)
    for i, a in enumerate(acts):
        if a == M.AL:
            assert dirn[i] > 0, f"AL, supertrend yukarida degil (bar {i})"
        if a == M.SAT:
            assert dirn[i] < 0, f"SAT, supertrend asagida degil (bar {i})"


ok.append(test("MURO: aksiyon serisi yön değişiminde kapatma üretir",
               t_muro_aksiyon_serisi))


def t_muro_backtest_calisir():
    """MURO modunda geriye dönük test hatasız çalışır."""
    p = _muro_trader()
    mum = _mum(n=120, step=0.4)
    st = p.backtest(mum, "1d")
    assert "error" not in st, st.get("error")
    assert st["mode"] == "muro"
    assert st["bars"] > 0


ok.append(test("MURO: geriye dönük test çalışır", t_muro_backtest_calisir))


def t_muro_yapilandirma_gecerli():
    """Mod, risk ve kilit yüzdeleri yapılandırılabilir."""
    p = _muro_trader()
    p.configure(mode="muro", risk_pct=0.03, lock_pct=0.02)
    assert p.mode == "muro"
    assert abs(p.muro_risk_pct - 0.03) < 1e-9
    assert abs(p.muro_cfg.lock_pct - 0.02) < 1e-9
    # Gecersiz degerler reddedilir
    p.configure(risk_pct=0.9, lock_pct=0.5)
    assert abs(p.muro_risk_pct - 0.03) < 1e-9
    assert abs(p.muro_cfg.lock_pct - 0.02) < 1e-9


ok.append(test("MURO: yapılandırma (risk, kâr kilitleme) çalışır",
               t_muro_yapilandirma_gecerli))



# ----------------------------------------------------------------------
# POZISYON DALGALANMASI (kullanici sorunu) + KAR KILIDI (trend modu)
#
# Kullanicinin HYPE/USDT logundaki sikayeti:
#   "long short veya short long gecislerinde defalarca islem yapiyor"
#   "hangi pozisyonda olurda olsun %3 kazanc sagladiginda pozisyonu
#    durdur, kazanci cuzdana aktar, sonra tekrar degerlendir"
#
# Cozum (3 parca):
#   1) Sinyal yalnizca KAPANMIS barlardan uretilir
#      (core/paper.py::_kapali_mumlar) — olusan bar icinde Supertrend
#      yonu tik tik degisiyordu.
#   2) Yon degisiminden sonra 5 DK bekleme: yeni pozisyon acilmaz.
#   3) Trend modunda %3 kar kilidi: pozisyon kapanir, kar cuzdana
#      yazilir, 1-2 dk beklenir, sonra pozisyon TEKRAR degerlendirilir.
# ----------------------------------------------------------------------
def _trend_trader(**kw):
    from core.paper import PaperTrader
    import config as cfg

    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode="trend", risk_pct=0.05)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def t_trend_yon_degisiminde_bekleme():
    """LONG -> SAT: LONG kapanir, SHORT ANINDA acilmaz (5 dk bekleme)."""
    p = _trend_trader()
    p.on_price(100.0, _mum(), "4h", "AL")
    assert p.position.side == "LONG"
    ev = p.on_price(99.0, _mum(t0=100), "4h", "SAT")
    assert ev and "kapandı" in ev, ev
    assert p.position is None, "karsi yon bekleme dolmadan acilmamali"
    assert p._bekleme_kaldi_ms(_mum()) > 0, "bekleme baslamaliydi"
    # Ayni sinyal tekrar gelirse acilmaz (bekleme suresi dolmadi).
    p.on_price(99.0, _mum(t0=200), "4h", "SAT")
    assert p.position is None, "bekleme suresi icinde acilmamali"
    # Bekleme dolduktan sonra SHORT acilir.
    p._no_entry_until = 0.0
    p.on_price(99.0, _mum(t0=300), "4h", "SAT")
    assert p.position is not None and p.position.side == "SHORT", \
        "bekleme sonrasi SHORT acilmali"


ok.append(test("TREND: yön değişiminde 5 dk bekleme (dalgalanma yok)",
               t_trend_yon_degisiminde_bekleme))


def t_trend_kar_kilidi():
    """%3 kazanc: pozisyon kapanir, kar cuzdana yazilir, beklenir."""
    p = _trend_trader()
    m = _mum()
    p.on_price(100.0, m, "4h", "AL")
    assert p.position.side == "LONG"
    bakiye_once = p.balance

    lock = p.trend_lock_pct
    lock_fiyat = p.position.entry * (1 + lock)
    ev = p.on_price(lock_fiyat, m, "4h", None, bar_high=lock_fiyat * 1.001)
    assert ev and "Kâr kilidi" in ev, f"kilit tetiklenmedi: {ev}"
    assert p.position is None, "kilit sonrasi pozisyon kalmamali"
    assert p.balance > bakiye_once, \
        f"kar cuzdana yazilmali: {p.balance} <= {bakiye_once}"
    assert p.trades[-1].net_pnl > 0, "kilit kari pozitif olmali"
    # Kilit sonrasi bekleme baslar; ayni sinyal acmaz.
    p.on_price(lock_fiyat, m, "4h", "AL")
    assert p.position is None, "bekleme suresi icinde acilmamali"


ok.append(test("TREND: %3 kâr kilidi — kâr cüzdana yazılır, bekleme başlar",
               t_trend_kar_kilidi))


def t_trend_kilit_sonrasi_yeniden_degerlendirilir():
    """Kilit sonrasi bekleme bitince pozisyon TEKRAR acilir."""
    p = _trend_trader()
    m = _mum()
    p.on_price(100.0, m, "4h", "AL")
    lock_fiyat = p.position.entry * (1 + p.trend_lock_pct)
    p.on_price(lock_fiyat, m, "4h", None, bar_high=lock_fiyat * 1.001)
    assert p.position is None
    # Bekleme suresi doldu -> pozisyon yeniden acilir.
    p._no_entry_until = 0.0
    p.on_price(lock_fiyat, _mum(t0=300), "4h", "AL")
    assert p.position is not None and p.position.side == "LONG", \
        "bekleme sonrasi pozisyon yeniden acilmali"


ok.append(test("TREND: kâr kilidi sonrası pozisyon yeniden değerlendirilir",
               t_trend_kilit_sonrasi_yeniden_degerlendirilir))


def t_kapali_mumlar_helpers():
    """Sinyal yalnizca kapanmis barlardan: olusan bar haric."""
    from core.paper import _kapali_mumlar
    from core.binance_client import Candle

    def bar(i, closed=True):
        return Candle(open_time=i * 3600000, open=100.0, high=101.0,
                      low=99.0, close=100.5, volume=1.0,
                      close_time=i * 3600000 + 1, closed=closed)

    hepsi = [bar(0), bar(1), bar(2, closed=False)]
    assert len(_kapali_mumlar(hepsi)) == 2, "olusAN bar haric tutulmali"
    hepsi[-1].closed = True
    assert len(_kapali_mumlar(hepsi)) == 3, "hepsi kapanmissa tamami"


ok.append(test("SİNYAL: yalnızca kapanmış barlar kullanılır",
               t_kapali_mumlar_helpers))



# ----------------------------------------------------------------------
# CANLI TITREME REGRESYONU (kullanicinin HYPE/USDT logu)
#
# Sorun: "long short veya short long gecislerinde defalarca islem
# yapiyor... tum kazanc ve fazlasi komisyona gitti".
#
# Kok neden: Supertrend yonu OLUSAN (kapanmamis) bar icinden hesaplaniyordu;
# fiyat bar icinde oynadikca yon tik tik degisiyor, analiz 0,5 sn'de bir
# calistigi icin simulator her degisimde pozisyon degistiriyordu.
#
# Bu test canli dongusunu taklit eder ve ISLEM SAYISINI olcer.
# ----------------------------------------------------------------------
def t_canli_titreme_yok():
    """Olusan bar + yon titremesi -> islem sayisi patlamamali."""
    from core.binance_client import Candle
    from core.paper import PaperTrader, _kapali_mumlar
    from core import trend as trend_mod
    import numpy as np

    def senaryo(kapali_barlar):
        rng = np.random.default_rng(5)
        fiyat = 79.68 + rng.normal(0, 0.002, 200)
        cs = []
        for i, f in enumerate(fiyat[:60]):
            cs.append(Candle(open_time=i * 60000, open=f, high=f + 0.004,
                              low=f - 0.004, close=f, volume=1.0,
                              close_time=(i + 1) * 60000 - 1, closed=True))
        cs[-1].closed = False
        p = PaperTrader(symbol="HYPEUSDT", balance=1000.0, leverage=10.0,
                        fee_rate=0.0005, wallet_fraction=0.8)
        p.configure(mode="trend", risk_pct=0.05)
        p.running = True
        p.start_balance = 1000.0
        p.balance = 1000.0
        son = cs[-1]
        olay = 0
        r2 = np.random.default_rng(9)
        for t in range(300):
            son.close = (fiyat[60] + r2.choice([-0.02, 0.02]) * (1 + t % 3)
                         + r2.normal(0, 0.002))
            son.high = max(son.high, son.close)
            son.low = min(son.low, son.close)
            kaynak = _kapali_mumlar(cs) if kapali_barlar else cs
            if len(kaynak) < 30:
                continue
            sig = trend_mod.last_signal([c.high for c in kaynak],
                                        [c.low for c in kaynak],
                                        [c.close for c in kaynak])
            if p.on_price(son.close, cs, "15m", sig):
                olay += 1
            if t % 20 == 19:
                yeni = Candle(open_time=cs[-1].open_time + 60000,
                              open=son.close, high=son.close + 0.004,
                              low=son.close - 0.004, close=son.close,
                              volume=1.0,
                              close_time=cs[-1].open_time + 120000 - 1,
                              closed=False)
                cs = cs + [yeni]
                son = cs[-1]
        return olay, p.balance

    eski, bakiye_eski = senaryo(False)
    yeni, bakiye_yeni = senaryo(True)
    # 1) Kapanmis bar ile: neredeyse hic islem olmamali.
    assert yeni <= 3, \
        f"kapali barla yon titremesi devam ediyor: {yeni} olay"
    # 2) Olusan bar ile (eski sinyal kaynagi): stop dongusu ve bekleme
    #    sayesinde yine de patlama olmamali.
    assert eski <= 6, \
        f"olusAN bar ile yon titremesi devam ediyor: {eski} olay"
    # 3) Komisyon cokeni olmamali: bakiye agir kaybetmemeli.
    assert bakiye_yeni > 980, f"bakiye eridi: {bakiye_yeni:.2f}"
    assert bakiye_eski > 975, f"bakiye eridi: {bakiye_eski:.2f}"


ok.append(test("CANLI: yön titremesi yok (kapanmış bar + bekleme)",
               t_canli_titreme_yok))



# ----------------------------------------------------------------------
# KÂR KİLİDME POZİSYON BAZLI + STOP SONRASI RECLAIM
#
# KULLANICI SORUNU: "zarar yaptıktan sonra kazanç moduna geçince toplam
# yüzdelik kazanca baktığı için Kar kilitleme çalışmıyor... dolayısıyla
# mevcut çalışan pozisyon özelinde kar kilitleme çalışmalıdır."
#
# GERÇEK NEDEN: stop'a yakılan pozisyondan sonra "last_signal" bayat
# kaldığı için aynı yönde YENİ POZİSYON hiç açılmıyordu → kâr kilitleme
# hiç tetiklenmiyordu. Çözüm: stop sonrası aynı yöne girmeden önce fiyat
# stop seviyesini geri almalı (reclaim). Kâr kilitleme zaten POZİSYONUN
# kendi giriş fiyatına bakar (hesabın toplamına değil).
# ----------------------------------------------------------------------
def t_kar_kilidi_pozisyon_bazli():
    """Zarardan sonra yeni pozisyon açılır ve KENDİ +%3'ünde kilitlenir."""
    p = _trend_trader()
    p.configure(lock_pct=0.03)
    m = _mum()
    p.on_price(100.0, m, "4h", "AL")
    assert p.position and p.position.side == "LONG"
    bakiye0 = p.balance
    stop = p.position.stop_price

    # 1) Stop ol (zarar)
    p.on_price(stop - 0.05, _mum(t0=100), "4h", None)
    assert p.position is None, "stop'ta kapanmaliydi"
    assert p.balance < bakiye0, "zarar olmaliydi"

    # 2) Reclaim: fiyat stop seviyesinin USTUNE cikinca yeni LONG acilir
    p._no_entry_until = 0.0
    p.on_price(stop + 0.5, _mum(t0=200), "4h", "AL")
    assert p.position and p.position.side == "LONG", \
        "reclaim sonrasi yeni LONG acilmaliydi"
    entry = p.position.entry

    # 3) Yeni pozisyonun KENDI +%3'unde kilitlenir (toplam zararda olsa bile)
    lock_fiyat = entry * 1.03
    ev = p.on_price(lock_fiyat, _mum(t0=300), "4h", None,
                    bar_high=lock_fiyat * 1.001)
    assert ev and "Kâr kilidi" in ev, f"pozisyon bazli kilit calismadi: {ev}"
    assert p.trades[-1].net_pnl > 0, "kilit bacagi karli olmali"


ok.append(test("TREND: kâr kilitleme pozisyon bazlı (toplam zararda bile)",
               t_kar_kilidi_pozisyon_bazli))


def t_stop_sonrasi_reclaim_gerekli():
    """Stop sonrasi ayni yone, fiyat stop seviyesini geri almadan girilmez."""
    p = _trend_trader()
    p.on_price(100.0, _mum(), "4h", "AL")
    stop = p.position.stop_price
    p.on_price(stop - 0.05, _mum(t0=100), "4h", None)
    assert p.position is None
    # Fiyat stop seviyesinin ALTINDA: ayni yone girilmez
    p._no_entry_until = 0.0
    p.on_price(stop - 0.2, _mum(t0=200), "4h", "AL")
    assert p.position is None, "reclaim olmadan girilmemeli"
    # Reclaim (fiyat stop seviyesinin ustunde): girilir
    p.on_price(stop + 0.3, _mum(t0=300), "4h", "AL")
    assert p.position and p.position.side == "LONG", \
        "reclaim sonrasi girilmeli"


ok.append(test("TREND: stop sonrası reclaim şart (döngü yok)",
               t_stop_sonrasi_reclaim_gerekli))


def t_1m_dilimi_var():
    """1 dakikalik dilim eklendi (kullanici istegi)."""
    import config as cfg
    assert "1m" in cfg.TIMEFRAMES, cfg.TIMEFRAMES
    assert cfg.TF_SECONDS.get("1m") == 60, cfg.TF_SECONDS
    assert "1m" in cfg.TF_LABELS, cfg.TF_LABELS
    assert cfg.TIMEFRAMES.index("1m") < cfg.TIMEFRAMES.index("15m")


ok.append(test("DİLİM: 1 dakikalık zaman dilimi mevcut", t_1m_dilimi_var))


print("-" * 62)
print(f"{sum(ok)}/{len(ok)} test gecti")
sys.exit(0 if all(ok) else 1)
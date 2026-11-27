"""
Bot yapilandirma ayarlari.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)


@dataclass
class TradingConfig:
    # Sembol / borsa
    symbol: str = "BTC/USDT:USDT"
    display_symbol: str = "BTCUSDT"
    exchange_id: str = "binance"
    market_type: str = "future"
    timeframe: str = "1m"          # 1 dakikalik mum

    # Test cuzdani
    initial_balance: float = 100.0     # USDT
    leverage: int = 5
    max_position_pct: float = 0.20        # marjindan ne kadarini kullan
    quantity_precision: float = 0.001     # BTC

    # Risk yonetimi - 1dk olcumleri (olcum: mum ATR %0.054, std %0.044)
    # SL %1.0, TP %1.8 -> R/R 1:1.8. Komisyonun TP icindeki payi %5.6.
    # 4h denendi (ATR %1.135) ama o donemde hicbir sinyal karli cikmadi;
    # bilesik skor 1dk'da daha genis bir araliga sahip.
    stop_loss_pct: float = 0.010          # %1.0
    take_profit_pct: float = 0.018        # %1.8
    max_open_positions: int = 1

    # --- KAR KORUMA ---
    # Olcum sonucu (66 gun, esik 0.65):
    #   korumasiz              -> roi +%11.14  (49 islem)
    #   kar kilidi %10 acik    -> roi  +%8.73  (53 islem)  kazananlari kesiyor
    #   notr + karda kapatma   -> roi  -%9.79  (146 islem) komisyona yiyor
    # Bu yuzden varsayilan: BASABA KORUMA acik, kar kilidi kapali.
    # Kar kilidi kazanan pozisyonu erken kesip zarar yaziyor; basaba
    # koruma ise kazanci kesmeden geri verilmesini engelliyor.

    # +%5 ROI'a ulasinca SL, giriş fiyatina (ucretler dahil) cekilir.
    breakeven_trigger_pct: float = 0.05
    breakeven_enabled: bool = True

    # ROI hedefine ulasinca pozisyon tamamen kapanir (kullanici istegi).
    # DIKKAT: marjin ROI = fiyat yuzdesi x kaldirac.
    #   5x kaldiracta TP %1.8 fiyat = %9.0 ROI demektir; yani %10'luk
    #   bir kilit TP'den SONRA gelir ve HIC tetiklenmez.
    #   Kilit'in TP'den kucuk olmasi sarttir (asagida %8).
    # Olcum: tam kapama kazananlari kesip getiriyi dusuruyor -> KAPALI.
    profit_lock_pct: float = 0.08
    profit_lock_enabled: bool = False

    # Sinyal notre dondugunde sadece pozisyon KARDA ise kapatilir.
    # Olcumde -%9.79 -> komisyona yiyor, varsayilan KAPALI.
    exit_on_neutral_profit: bool = False

    # Ucretler (Binance futures)
    maker_fee: float = 0.0002
    taker_fee: float = 0.0005

    # Sinyal esikleri (bilesik skor -1..1)
    #
    # OLÇÜM (1dk, 66 gün gerçek veri, pivot %20 agirlikli):
    #   esik 0.65 ->  53 islem, +%9.85 ROI, pf 1.43, dd %5.9   ← BURASI
    #   esik 0.55 -> 130 islem, -%3.19 ROI, pf 0.94, dd %14.4
    #   esik 0.35 -> 443 islem, -%25.25 ROI, pf 0.56, dd %26.0
    #
    # Dusuk esik = cok islem = komisyon. 0.65 ile yalnizca guclu
    # sinyaller emir acar; ortalama islem kalitesi belirgin yuksek.
    strong_buy_threshold: float = 0.65
    strong_sell_threshold: float = -0.65
    entry_threshold: float = 0.40
    exit_threshold: float = 0.10

    # Sinyal sogumesiyle kapatma:
    #   LONG  : skor <= +exit_threshold  -> pozisyon kapanir
    #   SHORT : skor >= -exit_threshold  -> pozisyon kapanir
    #
    # UYARI - bu kural olcumde KARSIZ KALMIYOR:
    #   esik 0.65, 66 gun : sogume kapali -> +%9.85 ROI (53 islem)
    #                         sogume acik   -> -%10.52 ROI (169 islem)
    # Pozisyon +0.65'te acilip +0.10'da kapandigi icin TP'ye (%1.8 fiyat)
    # ulasamadan kapanir; kazanc orani %40 -> %21, PF 1.43 -> 0.58.
    # CANLI LOGDAKI ISLEM KAYBI: bu kural acik kaldigi icin surekli
    # "sinyal-sogudu" ile kucuk zararla cikip her seferinde 2 x komisyon
    # (pozisyon basina %0.10) odendi.
    # Istemeden aktifse False yapin.
    exit_on_decay: bool = False

    # Agirliklar (bilesik skorda normalize edilir, toplam 1.0 olmasi sart degil)
    # Pivotlar %20 agirlikla geri eklendi: osilator ve MA ayni fiyat
    # hareketinden beslendigi icin birbirini dogruluyor (korelasyon
    # yuksek), pivot bagimsiz referans saglayarak skoru seyreltiyor.
    # Olcum: pivotlu varyant walk-forward OOS testinde POZITIFTIK
    # (+%4.57); pivotsuz varyant -%24 idi.
    oscillator_weight: float = 0.40
    ma_weight: float = 0.40
    pivot_weight: float = 0.20

    # Veri (en az 3 gun: gunluk pivot hesabi icin 1dk bar gerekir)
    lookback_candles: int = 5000
    poll_seconds: int = 30

    # Canli modda iki ayri hiz:
    #   fiyat    -> anlik fiyat + mark price (emirler buradan girilir)
    #   gosterge -> yeni mum + indikator hesabi (daha pahali)
    # Olcum: fiyat sorgusu ~0.27s, YENI mum cekme ~0.31s,
    # indikator (1000 bar) ~0.4s.
    # 1dk mumda gosterge periyodu 20s: bar kapandiginda en gecik
    # 20 saniyede yakalanir, gereksiz API cagrisi olmaz.
    price_poll_seconds: int = 3
    indicator_refresh_seconds: int = 20

    # Backtest
    backtest_start: str = "2024-01-01"
    backtest_end: str = "2024-03-01"


@dataclass
class IndicatorConfig:
    rsi_period: int = 14
    cci_period: int = 20
    adx_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    ma_periods: List[int] = field(default_factory=lambda: [10, 20, 30, 50, 100, 200])
    vwma_period: int = 20
    hull_period: int = 9


TRADING_CONFIG = TradingConfig()
INDICATOR_CONFIG = IndicatorConfig()

GUI_CONFIG = {
    "title": "BTCUSDT Futures Trading Bot",
    "width": 1480,
    "height": 940,
    "theme": "dark-blue",
    "log_lines": 800,
}

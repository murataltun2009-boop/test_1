"""
BTCUSDT Canli Teknik Analiz - yapilandirma.

Tum ayarlar tek dosyada. Arayuzden degistirilebilenler icin
Settings sinifi kullanilir.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Dizinler
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "signals.db")
LOG_FILE = os.path.join(LOG_DIR, "sinyal.log")
# Islem gunlugu (2026-11-07 kullanici istegi): her kapanan islem icin
# zaman, yon, giris/cikis, brut/net kar, komisyon ve sebep. CSV (';').
TRADE_LOG_FILE = os.path.join(LOG_DIR, "islemler.csv")

# --------------------------------------------------------------------------
# Binance Futures
# --------------------------------------------------------------------------
# NOT: kullanicinin istegi dogrultusunda SPOT degil FUTURES (fapi) kullanilir.
FAPI_REST = "https://fapi.binance.com"
FAPI_WS = "wss://fstream.binance.com/stream?streams="

SYMBOL = "BTCUSDT"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT"]

# Kullanilan zaman dilimleri.
#
# Gecmis: kullanici "TEK dilim olsun, 4 saat" dedigi icin liste tek ogeye
# indirilmis ve arayuzden secici kaldiril misti. Sonra kullanicinin
# "4 saatlik disinda 15 dakika ve 1 saat de olsun, secilen dilime gore
# grafik ve AL/SAT noktalari hesaplansin" istegiyle yeniden acildi.
#
# ACTIVE_TIMEFRAME yalnizca acilista secili gelen dilimdir; arayuzden
# degistirilebilir.
ACTIVE_TIMEFRAME = "4h"
TIMEFRAMES: list[str] = ["1m", "5m", "15m", "1h", "4h", "1d"]

# Odak disi dilimler bu kadar daha seyrek yeniden hesaplanir. analyze()
# 500 bar icin ~55 ms surer; uc dilimi de 0,5 sn'de bir calistirmak
# surekli CPU tuketirdi. Kullaniciya gosterilen dilim her RECOMPUTE_INTERVAL
# saniyede bir guncellenir, digerleri daha seyrek.
RECOMPUTE_INTERVAL = 15
RECOMPUTE_INTERVAL_ACTIVE = 3
RECOMPUTE_INTERVAL_PASSIVE = 60

# Portfoy izleme (2026-11-25 kullanici istegi):
# "Coin listesini goster, her biri icin son sinyal, skor, fiyat ve
# 24s degisimi goster. Tiklaninca grafik acilsin."
WATCHLIST: list[str] = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
]

# --------------------------------------------------------------------------
# Indikator esikleri (TradingView Technicals benzeri)
# --------------------------------------------------------------------------
# Bu degerler GUI uzerinden de degistirilebilir.
# RSI (14) - asiri alim/satim
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# Stokastik (14, 3, 3)
STOCH_OVERBOUGHT = 80
STOCH_OVERSOLD = 20

# CCI (20)
CCI_OVERBOUGHT = 100
CCI_OVERSOLD = -100

# ADX (14)
ADX_TREND = 25

# AO
AO_ZERO = 0

# MACD
MACD_ZERO = 0

# MACD Histogram
MACD_HIST_ZERO = 0

# Momentum (10)
MOMENTUM_ZERO = 0

# Williams %R (14)
WILLIAMS_OVERBOUGHT = -20
WILLIAMS_OVERSOLD = -80

# Ultimate Oscillator (7, 14, 28)
UO_OVERBOUGHT = 70
UO_OVERSOLD = 30

# Hull MA
HULL_PERIOD = 9

# VWMA
VWMA_PERIOD = 20

# Ichimoku
ICHIMOKU_TENKAN = 9
ICHIMOKU_KIJUN = 26
ICHIMOKU_SENKOU_B = 52

# Pivot - klasik (gunluk)
PIVOT_TYPE = "classic"

# --------------------------------------------------------------------------
# Skorlama agirliklari
# --------------------------------------------------------------------------
OSCILLATOR_WEIGHT = 0.4
MA_WEIGHT = 0.4
PIVOT_WEIGHT = 0.2

# Bilesik skor esikleri
BASE_THRESHOLD = 0.40
STRONG_THRESHOLD = 0.65

# --------------------------------------------------------------------------
# Grafik ayarlari
# --------------------------------------------------------------------------
# Gorunen mum sayisi
VISIBLE_CANDLES = 300

# --------------------------------------------------------------------------
# Ayarlar sinifi (GUI icin)
# --------------------------------------------------------------------------
@dataclass
class Settings:
    # Sembol
    symbol: str = SYMBOL
    timeframes: list[str] = field(default_factory=lambda: list(TIMEFRAMES))
    active_timeframe: str = ACTIVE_TIMEFRAME
    strong_threshold: float = STRONG_THRESHOLD
    base_threshold: float = BASE_THRESHOLD
    record_neutral: bool = True   # NOTR gecislerini de kaydet (varsayilan evet)
    show_ma_overlay: bool = True
    visible_candles: int = VISIBLE_CANDLES

    def validate(self) -> list[str]:
        """Gecersiz ayar varsa hata mesajlari dondurur."""
        errors: list[str] = []
        if self.base_threshold <= 0:
            errors.append("Temel esik 0'dan buyuk olmalidir.")
        if self.base_threshold >= 1:
            errors.append("Temel esik 1'den kucuk olmalidir.")
        if self.strong_threshold < self.base_threshold:
            errors.append("Guclu esik, temel esikten kucuk veya esit olmalidir.")
        if self.strong_threshold > 1:
            errors.append("Guclu esik 1'den buyuk olamaz.")
        for tf in self.timeframes:
            if tf not in TIMEFRAMES:
                errors.append(f"Gecersiz zaman dilimi: {tf}")
        if self.active_timeframe not in self.timeframes:
            errors.append("Aktif dilim, dilim listesinde degil.")
        return errors


SETTINGS = Settings()

# GUI yapilandirma
GUI_CONFIG = {
    "title": "BTCUSDT Futures Trading Bot",
    "width": 1480,
    "height": 940,
    "theme": "dark-blue",
    "log_lines": 800,
}

# Trading yapilandirma (varsayilan degerler)
TRADING_CONFIG = Settings()

# Indicator hesaplayici icin yapilandirma
@dataclass
class IndicatorConfig:
    rsi_period: int = 14
    cci_period: int = 20
    adx_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    ma_periods: list = field(default_factory=lambda: [10, 20, 30, 50, 100, 200])
    vwma_period: int = 20
    hull_period: int = 9

INDICATOR_CONFIG = IndicatorConfig()

# --------------------------------------------------------------------------
# Paper Trading / Core Trading Config
# --------------------------------------------------------------------------
# Candle limit for fetching (Binance max 1500 per request)
CANDLE_LIMIT = 1500

# Lookback candles for backtest/initial load (fetcher handles pagination for >1500)
LOOKBACK_CANDLES = 5000

# Service/Service config
BACKGROUND_REFRESH_FACTOR = 5
RESYNC_SECONDS = 300
WS_RECONNECT_SECONDS = 10
TRADE_PRICE_SANITY = 0.25  # %25 sapma toleransi

# Paper trading config
PAPER_INITIAL_BALANCE = 100.0
PAPER_LEVERAGE = 5
PAPER_FEE_RATE = 0.0005
PAPER_WALLET_FRACTION = 0.20
PAPER_LOOKBACK = 20
PAPER_CONFIRM = False
PAPER_SHORT_RULE = "entry"
PAPER_MODE = "range"
PAPER_MIN_HOLD_BARS = 0
PAPER_FIB_ON = True
PAPER_FIB_WINDOW = 24
PAPER_FIB_GATE = 0.382

# Trend config
PAPER_TREND_PERIOD = 10
PAPER_TREND_MULT = 3.0
PAPER_TREND_STOP_ATR = 1.5
PAPER_TREND_TRAIL_ATR = 1.0
PAPER_TREND_RISK_PCT = 0.02
PAPER_TREND_MAX_LEV = 5.0
PAPER_TREND_LOCK_PCT = 0.03
PAPER_TREND_PULL_ATR = 1.0
PAPER_TREND_PULL_BARS = 20
PAPER_FLIP_COOLDOWN_SEC = 60
PAPER_LOCK_COOLDOWN_SEC = 60

# 1M optimized config
PAPER_1M_TREND_PERIOD = 10
PAPER_1M_TREND_MULT = 3.0
PAPER_1M_PULLBACK_EMA = 20
PAPER_1M_PULLBACK_ATR = 1.0
PAPER_1M_COOLDOWN = 3
PAPER_1M_MIN_HOLD = 0
PAPER_1M_ADX_MIN = 20
PAPER_1M_VOL_Z_MIN = -1.5
PAPER_1M_ATR_PCT_MIN = 0.10
PAPER_1M_ATR_PCT_MAX = 0.90
PAPER_1M_STOP_ATR = 1.0
PAPER_1M_TRAIL_ATR = 1.0
PAPER_1M_MIN_STOP_PCT = 0.003
PAPER_1M_MAX_STOP_PCT = 0.02
PAPER_1M_RISK_PCT = 0.02
PAPER_1M_MAX_LEV = 3.0
PAPER_1M_SESSION_FILTER = True

# PPT config
PAPER_PPT_PERIOD = 10
PAPER_PPT_MULT = 3.5
PAPER_PPT_PULL_ATR = 1.0
PAPER_PPT_PULL_BARS = 20
PAPER_PPT_STOP_ATR = 1.0
PAPER_PPT_TRAIL_ATR = 1.0
PAPER_PPT_MIN_STOP_PCT = 0.003
PAPER_PPT_MAX_STOP_PCT = 0.02
PAPER_PPT_RISK_PCT = 0.03
PAPER_PPT_MAX_LEV = 5.0

# Muro config
PAPER_MURO_MODE = "trend"
PAPER_MURO_K = 8
PAPER_MURO_STOP_PCT = 0.008
PAPER_MURO_MAX_STOP_PCT = 0.03
PAPER_MURO_MIN_STOP_PCT = 0.002
PAPER_MURO_LOCK_PCT = 0.01
PAPER_MURO_TRAIL_PCT = 0.008
PAPER_MURO_RETEST_ATR = 0.3
PAPER_MURO_MAX_RETEST = 2
PAPER_MURO_TREND_EMA = 200
PAPER_MURO_ST_PERIOD = 10
PAPER_MURO_ST_MULT = 3.0
PAPER_MURO_PULL_EMA = 9
PAPER_MURO_PULL_ATR = 1.0
PAPER_MURO_COOLDOWN = 10
PAPER_MURO_TRAIL_ALWAYS = True
PAPER_MURO_MAX_LOSSES = 2
PAPER_MURO_FIB_ON = True
PAPER_MURO_FIB_WINDOW = 160
PAPER_MURO_FIB_GATE = 0.15
PAPER_MURO_RISK_PCT = 0.01

# TK config
PAPER_TK_FRACTION = 0.50
PAPER_TK_BANK_RR = 1.8
PAPER_TK_PAUSE_BARS = 3
PAPER_TK_RIBBON_MODE = "cross"
PAPER_TK_RIBBON_DEADBAND = 0.0005
PAPER_TK_RIBBON_CONFIRM = 2
PAPER_TK_ENTRY_OFFSET = -0.001
PAPER_TK_REQUIRE_TREND = True
PAPER_TK_STREAK_N = 2
PAPER_TK_STREAK_BARS = 1
PAPER_TK_LEVEL_BAN = 0.002
PAPER_TK_LEVEL_BARS = 1
PAPER_TK_SL_ATR = 1.0
PAPER_TK_BE_RISK = 1.0
PAPER_TK_TIME_BARS = 0
PAPER_TK_CONFIRM = 2
PAPER_TK_SL = 0.01
PAPER_TK_TP = 0.0
PAPER_TK_BANK_PCT = 0.035

# TK2 config
PAPER_TK2_BANK_USD = 10.0
PAPER_TK2_STAB_ENTRY = 0.0
PAPER_TK2_STAB_HOLD = 0.0

# Takipci/Algograf config
PAPER_ALGOGRAF_TOUCH = 0.0
PAPER_ALGOGRAF_SL = 0.01
PAPER_ALGOGRAF_BANK_USD = 10.0
PAPER_ALGOGRAF_LOSS_USD = 5.0
PAPER_ALGOGRAF_LOSS_PAUSE_MS = 60000
PAPER_TAKIPCI_TOUCH = 0.0

# Service/Service config
ANALYSIS_INTERVAL = 15
CHART_HEADROOM = 0.8
CHART_MIN_INTERVAL_MS = 500
REFRESH_MODES = {
    "Canlı (hızlı)": (0.8, 500, 0.5),
    "Dengeli": (0.8, 500, 1.0),
    "Akku tasarrufu": (0.5, 1000, 2.0),
}
DEFAULT_REFRESH_MODE = "Canlı (hızlı)"

# TF seconds mapping
TF_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

# UI config
LOG_HEIGHT = 800
LOG_WIDTH = 400
LOG_LINES = 800

# Timeframe labels for UI
TF_LABELS = {
    "1m": "1 Dakika",
    "5m": "5 Dakika",
    "15m": "15 Dakika",
    "1h": "1 Saat",
    "4h": "4 Saat",
    "1d": "1 Gün",
}

GUI_TICK_MS = 100
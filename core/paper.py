"""
Kaldıracli islem simulasyonu (paper trading).

Bu bir EMLERDIR: hiçbir emir Binance'e gonderilmez, borsa hesabi
temas edilmez. Yalnizca oluşan mumlardan karar verip sanal bir cuzdan
tutulur.

Kullanicinin koydugu kurallar:
  * LONG  -> fiyat grafigin EN TABAN noktasindan alinir.
  * SHORT -> fiyat "dusus egilimine girdigi" noktada (pencere zirvesi)
             verilir; ANCAK en son LONG fiyatini GECMEMELIDIR, aksi halde
             islem kaybeden baslar.
  * Cuzdanin %80'i kaldiraclı pozisyona kullanilir.
  * Alim ve satis komisyonlari kar/zarar icinde hesaplanir.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import config
from core import indicators as ind
from core import trend as trend_mod
from core import muro as muro_mod
from core import ppst
from core import fib as fib_mod

logger = logging.getLogger("ta.paper")

LONG = "LONG"
SHORT = "SHORT"


@dataclass
class Position:
    side: str                 # LONG | SHORT
    entry: float
    qty: float
    margin: float             # kullanilan teminat (teminat / kaldirac)
    notional: float           # pozisyon degeri = margin * kaldirac
    fee_open: float
    liq_price: float
    opened_at: float
    timeframe: str = ""
    reason: str = ""
    # GIRIS ANINDA dondurulan pencere uclari. Kapanis bu SABIT seviyeye
    # gore yapilir; yoksa yuvaralanan pencere girişten bir sonraki barda
    # "dibden zirveye" zipliyor ve her istek tek barda kapaniyordu.
    target: float = 0.0
    window_low: float = 0.0
    window_high: float = 0.0
    # ---- Trend (Supertrend) modu -----------------------------------
    # stop_price : ATR tabanli giris/takip stopu (0 = stop yok)
    # trail_mult : kapanista guncellenen takip stopu carpani (x ATR)
    # eff_leverage: risk bazli boyutlandirmada GERCEKTE kullanilan
    #               kaldirac. Likidasyon bu degere gore hesaplanir.
    stop_price: float = 0.0
    trail_mult: float = 0.0
    eff_leverage: float = 0.0
    # MURO: kâr kilitleme sonrası "bedava" bacak. trailing stop bu
    # noktadan sonra devreye girer.
    trail_frac: float = 0.0
    locked: bool = False
    # Başabaş koruması: pozisyonun açıldığı bar (epoch ms). KORUMA bu
    # barda DEĞİL, sonraki bardan itibaren devreye girer — giriş
    # salınımı pozisyonu anında kapatmasın.
    entry_bar: int = 0


@dataclass
class Trade:
    side: str
    entry: float
    exit: float
    qty: float
    margin: float
    gross_pnl: float
    fee_open: float
    fee_close: float
    net_pnl: float
    opened_at: float
    closed_at: float
    timeframe: str
    reason: str
    exit_reason: str
    symbol: str
    mode: str = "live"          # "backtest" | "live"


def _px(value: float) -> str:
    """Fiyat bicimi — ondalik adedi degerin buyuklugune gore degisir.

    Coin listesi genisletildiginde (1000PEPE = 0,0038) sabit 4 ondalik
    yetersiz kaldi ve 2 ondalik fiyati TAMAMEN sifirliyordu ("0,00").
    Simdi core.analysis.format_number ile ayni kurali kullanir.
    """
    from core.analysis import format_number
    return format_number(value, digits=None)


def _onceki_kapanis(candles: list, price: float) -> float:
    """Bir onceki barin kapanisi (yoksa mevcut fiyat).

    Takip eden (trailing) stop, bir SONRAKI bar icin hesaplanir; bu
    yuzden icinde bulunulan barin fiyati degil, onceki barin kapanisi
    kullanilir. Aksi halde stop, icinde bulunulan barin dip/zirvesi
    tarafindan ayni barda tetiklenirdi (olcümde: iki motor 3 kat farkli
    islem sayisi cikardi).
    """
    if candles and len(candles) >= 2:
        return float(candles[-2].close)
    return float(price)


def _kapali_mumlar(candles: list) -> list:
    """
    KAPANMIS mumlar (son olusan bar haric).

    ONEMLI: Supertrend/MURO sinyali OLUSAN bar uzerinden hesaplanirsa
    yon bar icinde tik tik degisir. Canli akista analiz 0,5 sn'de bir
    calistigi icin simulator saniyede bir kez LONG/SHORT degistiriyor,
    her islem komisyona gidiyordu (HYPE logu). Bu yuzden sinyal
    yalnizca kapanmis barlardan uretilir.
    """
    if not candles:
        return []
    son = candles[-1]
    if getattr(son, "closed", True):
        return list(candles)
    return list(candles[:-1])


def _bar_acilisi(candles: list, price: float) -> float:
    """Mevcut barin acilis fiyati (yoksa mevcut fiyat).

    Stop bir "gap" ile atlandiginda cikis, barin acilisinda olur
    (daha kotu fiyat). Bu, geriye donuk testin gercekci olmasi icin
    gereklidir.
    """
    if candles:
        try:
            return float(candles[-1].open)
        except (AttributeError, TypeError, ValueError):
            pass
    return float(price)


class PaperTrader:
    """
    Sanal cuzdan + kaldirac + komisyon.

    Parametreler arayuzden degistirilebilir; motor agdan bagimsizdir.
    """

    def __init__(self,
                 symbol: str = config.SYMBOL,
                 balance: float = config.PAPER_INITIAL_BALANCE,
                 leverage: float = config.PAPER_LEVERAGE,
                 fee_rate: float = config.PAPER_FEE_RATE,
                 wallet_fraction: float = config.PAPER_WALLET_FRACTION,
                 lookback: int = config.PAPER_LOOKBACK,
                 on_event=None) -> None:
        self.symbol = symbol
        self.balance = float(balance)
        self.leverage = float(leverage)
        self.fee_rate = float(fee_rate)
        self.wallet_fraction = float(wallet_fraction)
        self.lookback = int(lookback)

        # DIKKAT - is parcacigi:
        #   * analiz dongusu (servis thread'i) on_price() cagirir
        #   * backtest() web istek thread'inden cagrilir
        # Ikisi AYNI nesne uzerinde yaziyor. Kilit olmazsa hesap bozulur
        # (pozisyon kaybolur, bakiye yanlislikla artar).
        self._lock = threading.RLock()
        # Donus teyidi (yeşil/kırmızı mum) varsayılan KAPALI: ölçümde
        # sinyali bar başına %9-19'dan %1,5-4,7'ye düşürüyordu.
        self.confirm = bool(config.PAPER_CONFIRM)
        # SHORT kurali: "pullback" (varsayilan) | "entry"
        self.short_rule = config.PAPER_SHORT_RULE
        # Karar mekanizmasi:
        #   "range"  -> fiyat penceresinin taban/zirvesi (varsayilan)
        #   "signal" -> gosterge analizinin AL/SAT sinyali
        self.mode = config.PAPER_MODE
        self.last_signal = None
        # Sinyal modunda surekli ac-kapa (ve komisyon) engellemek icin
        # minimum tutma suresi (bar). 0 = kisit yok.
        self.min_hold_bars = int(config.PAPER_MIN_HOLD_BARS)
        # ---- Trend (Supertrend) modu ---------------------------------
        # Bu degerler arayuzden degistirilebilir (configure(risk_pct=...)).
        self.trend_period = int(config.PAPER_TREND_PERIOD)
        self.trend_mult = float(config.PAPER_TREND_MULT)
        self.trend_stop_atr = float(config.PAPER_TREND_STOP_ATR)
        self.trend_trail_atr = float(config.PAPER_TREND_TRAIL_ATR)
        self.trend_risk_pct = float(config.PAPER_TREND_RISK_PCT)
        self.trend_max_lev = float(config.PAPER_TREND_MAX_LEV)
        # Trend modunda KÂR KİLİDİ: fiyat %3 ilerleyince pozisyon kapanır,
        # kâr cüzdana yazılır, kısa bir bekleme sonrası pozisyon TEKRAR
        # DEĞERLENDİRİLİR (kullanıcı isteği).
        self.trend_lock_pct = float(config.PAPER_TREND_LOCK_PCT)
        # Kâr kilidi sonrası davranış:
        #   "protected" : aynı yönde HEMEN yeniden pozisyon açılır, stop
        #                 kârın yazıldığı seviyede (bankalanan kâr korunur)
        #   "wait"      : kısa bekleme, sonra pozisyon yeniden değerlendirilir
        self.trend_lock_reentry = str(
            getattr(config, "PAPER_TREND_LOCK_REENTRY", "protected"))
        # Girişte "optimum nokta" filtresi: long icin tepeye, short icin
        # dibe yakin fiyatlarda giris yapilmaz (0 = kapalı).
        self.trend_pull_atr = float(
            getattr(config, "PAPER_TREND_PULL_ATR", 0.0))
        self.trend_pull_bars = int(
            getattr(config, "PAPER_TREND_PULL_BARS", 20))
        # Pozisyon değişimi (LONG <-> SHORT) sonrası bekleme: yeni pozisyon
        # açılmaz, piyasa biraz durulur. Kullanıcı isteği: 5 dakika.
        self.flip_cooldown_ms = float(config.PAPER_FLIP_COOLDOWN_SEC) * 1000
        # Kâr kilidi sonrası bekleme (1-2 dakika).
        self.lock_cooldown_ms = float(config.PAPER_LOCK_COOLDOWN_SEC) * 1000
        # ---- EVRENSEL KURALLAR (tüm modlar, kullanıcı kuralı) ----------
        # 1) KÂR BANKASI: açık pozisyon KENDİ GİRİŞ FİYATINA göre +%X
        #    kârda nakde çevrilir; kâr cüzdanda kalır, sonra sinyal
        #    yeniden değerlendirilip en uygun yönde devam edilir.
        #    (trend/muro kendi kilit bloklarını kullanır; onların
        #    varsayılanları da %2'ye eşitlendi.)
        # 2) BAŞABAŞ KORUMASI: pozisyon ZARARA GEÇEMEZ — fiyat giriş
        #    fiyatına geri dönüp dokunursa pozisyon kapatılır. Tam
        #    girişte değil, giriş + komisyon payı kadar önce (yoksa
        #    net kâr 0'ın altına düşer). Giriş barında devreye girmez.
        self.bank_pct = float(getattr(config, "PAPER_BANK_PCT", 0.02))
        self.breakeven_buf = float(
            getattr(config, "PAPER_BREAKEVEN_BUF", 0.0012))
        # Yeni pozisyon açılamayacak ana kadar (piyasa zamanı, ms).
        self._no_entry_until = 0.0
        self._backtesting = False
        # STOP SONRASI RE-ENTRY KURALI (trend modu)
        #
        # Stop'a yakilan pozisyondan sonra ayni yone hemen girilmez: fiyat
        # once STOP SEVIYESINI GERI ALMALI (reclaim). Aksi halde (a) ayni
        # fiyattan tekrar stop olur (dongu), (b) "kazani sat, kaybedeni
        # tut" tuzagina dusulur.
        #
        # ONEMLI: Bu kural olmadan stop sonrasi yeni pozisyon hic
        # acilmadigi icin KAR KILIDME de hic calismiyordu.
        self._reclaim_side = ""      # "LONG" / "SHORT" / ""
        self._reclaim_level = 0.0
        # Reclaim sartinin dusecegi BAR SAYISI; 0 = sart yok (dustu).
        # Bar bazlidir: 4h/1d modlarinda 2 saat anlamsiz; 12 bar her dilimde
        # tutarli (5m'de 1 saat).
        self._reclaim_out_bars = 0
        # Durum olayi yazma suyu (ms): ayni engel spamini onler.
        self._state_log_until = 0.0
        self.trend_lock_reentry = str(
            getattr(config, "PAPER_TREND_LOCK_REENTRY", "protected"))
        # Girişte "optimum nokta" filtresi: long icin tepeye, short icin
        # dibe yakin fiyatlarda giris yapilmaz (0 = kapalı).
        self.trend_pull_atr = float(
            getattr(config, "PAPER_TREND_PULL_ATR", 0.0))
        self.trend_pull_bars = int(
            getattr(config, "PAPER_TREND_PULL_BARS", 20))
        # ---- 1m Optimized modu --------------------------------------------
        # Multi-timeframe: 15m Supertrend trend + 5m confirmation + 1m EMA20 pullback
        # Filters: ADX>20, Vol z-score > -1.5, ATR percentile 10-90%, Session 00-06 UTC
        # Cooldown: 100 bars, Min hold: 30 bars
        # Risk: 0.3%/trade, Max effective leverage 5x, Stop 3*ATR (min 0.15%), Trail 5*ATR
        # Session filter: 00-06 UTC
        self.mode_1m_trend_period = int(config.PAPER_1M_TREND_PERIOD)
        self.mode_1m_trend_mult = float(config.PAPER_1M_TREND_MULT)
        self.mode_1m_pullback_ema = int(config.PAPER_1M_PULLBACK_EMA)
        self.mode_1m_pullback_atr = float(config.PAPER_1M_PULLBACK_ATR)
        self.mode_1m_cooldown = int(config.PAPER_1M_COOLDOWN)
        self.mode_1m_min_hold = int(config.PAPER_1M_MIN_HOLD)
        self.mode_1m_adx_min = int(config.PAPER_1M_ADX_MIN)
        self.mode_1m_vol_z_min = float(config.PAPER_1M_VOL_Z_MIN)
        self.mode_1m_atr_pct_min = float(config.PAPER_1M_ATR_PCT_MIN)
        self.mode_1m_atr_pct_max = float(config.PAPER_1M_ATR_PCT_MAX)
        self.mode_1m_stop_atr = float(config.PAPER_1M_STOP_ATR)
        self.mode_1m_trail_atr = float(config.PAPER_1M_TRAIL_ATR)
        self.mode_1m_min_stop_pct = float(config.PAPER_1M_MIN_STOP_PCT)
        self.mode_1m_max_stop_pct = float(config.PAPER_1M_MAX_STOP_PCT)
        self.mode_1m_risk_pct = float(config.PAPER_1M_RISK_PCT)
        self.mode_1m_max_lev = float(config.PAPER_1M_MAX_LEV)
        self.mode_1m_session_filter = bool(config.PAPER_1M_SESSION_FILTER)
        # ---- PPT (Pivot Point Supertrend) modu --------------------------
        # Kullanıcı isteği: 5 dk periyodu + PP-Supertrend karar
        # mekanizması (core/ppst.py). Trend ailesiyle aynı pozisyon
        # yönetimi (stop/trail/kâr kilidi/reclaim).
        self.mode_ppt_period = int(config.PAPER_PPT_PERIOD)
        self.mode_ppt_mult = float(config.PAPER_PPT_MULT)
        self.mode_ppt_pull_atr = float(config.PAPER_PPT_PULL_ATR)
        self.mode_ppt_pull_bars = int(config.PAPER_PPT_PULL_BARS)
        self.mode_ppt_stop_atr = float(config.PAPER_PPT_STOP_ATR)
        self.mode_ppt_trail_atr = float(config.PAPER_PPT_TRAIL_ATR)
        self.mode_ppt_min_stop_pct = float(config.PAPER_PPT_MIN_STOP_PCT)
        self.mode_ppt_max_stop_pct = float(config.PAPER_PPT_MAX_STOP_PCT)
        self.mode_ppt_risk_pct = float(config.PAPER_PPT_RISK_PCT)
        self.mode_ppt_max_lev = float(config.PAPER_PPT_MAX_LEV)
        # ---- MURO modu -------------------------------------------------
        # Yeni algoritma: Supertrend yonu + geri cekilme girisi +
        # kâr kilitleme (kâr cüzdana yazilir, ayni yönde yeniden girilir).
        self.muro_cfg = muro_mod.MuroConfig.from_config()
        self.muro_risk_pct = float(config.PAPER_MURO_RISK_PCT)
        self.muro_max_lev = float(config.PAPER_TREND_MAX_LEV)
        # ---- AUTO FIB (skor tabanli + aralic motor) -------------------------
        # Skor modlari (sadece MA / sadece osilator / sinyal) karar
        # serisine ve aralik pencere motoruna AUTO FIB retracement:
        # altin cebede GÜÇLÜ, ucda engel (skor modlari) / altin cebede
        # ek giris (aralik motor). Olcum: tools/research_fib2.py.
        self.fib_score_on = bool(
            getattr(config, "PAPER_FIB_SCORE_ON", False))
        self.fib_range_on = bool(
            getattr(config, "PAPER_FIB_RANGE_ON", False))
        self.fib_window = int(getattr(config, "PAPER_FIB_WINDOW", 160))
        self.fib_gate = float(getattr(config, "PAPER_FIB_GATE", 0.15))
        # ---- DUZELTICI (seri kilidi) -------------------------------------
        # Zarar biten islemden sonra K BAR yeni giris yok; cikislar
        # (stop/banka/likidasyon) her zaman serbest. TESHIS:
        # tools/research_teshis.py — kayip serileri kumali.
        self.corr_on = bool(getattr(config, "PAPER_CORR_ON", False))
        self.corr_pause_bars = int(
            getattr(config, "PAPER_CORR_PAUSE_BARS", 4))
        self._corr_until = 0
        # Skor modlarinda (corr_on=True iken) basabas tamponi DUZELTICI
        # degerini kullanir: dar tampon (%0.12) komisyon-trip kayip
        # uretir; genis tampon fiyat geldiginde +tampon mikrokâr verir.
        self.corr_be_buf = float(
            getattr(config, "PAPER_CORR_BE_BUF", 0.0))
        # OLCUM yardimcisi: True iken stake start_balance'tan sabit
        # alinir (compounding yok) — konfig karsilastirmalari adil olsun.
        self.fixed_stake = False
        # Skor modlarinda buyuk tolerans stop (giris x (1-stop_down)).
        # Koken: mikro-klip (BE buffer) pozisyonlari +"micro" kesip
        # +2% bankaya ulastirmiyordu (olcum: tools/research_be2.py);
        # kaba tolerans stop + banka kombinasyonu tek duzeltme yolu.
        self.corr_stop_down = float(
            getattr(config, "PAPER_CORR_STOP_DOWN", 0.0))
        self.corr_tfs = set(getattr(config, "PAPER_CORR_TFS", {"1h"}))
        # ARM: zarar yonune ters sinyal gelmeden yeni giris acilmaz.
        self.corr_arm_on = bool(getattr(config, "PAPER_CORR_ARM_ON", False))
        self._corr_arm = ""                     # zarar yonu (LONG/SHORT)
        # Sadece GÜÇLÜ sinyaller giris acar (zayif AL/SAT -> NÖTR).
        self.corr_strong_only = bool(
            getattr(config, "PAPER_CORR_STRONG_ONLY", False))
        # GUC yen yazimi gate ONCESI (arm kurali zayif sinyalden
        # etkilenmesin): olcum tools/research_karar2.py.
        self.corr_strong_first = bool(
            getattr(config, "PAPER_CORR_STRONG_FIRST", False))
        # LIMIT-dolum cikislarda maker ucreti (resting emir gercekcigi).
        self.maker_rate = float(getattr(config, "PAPER_MAKER_RATE", 0.0002))
        # ---- TICK (super-hizli limit scalper) ----
        self.tk_on = bool(getattr(config, "PAPER_TK_ON", False))
        self.tk_tp = float(getattr(config, "PAPER_TK_TP", 0.002))
        self.tk_sl = float(getattr(config, "PAPER_TK_SL", 0.003))
        self.tk_window = int(getattr(config, "PAPER_TK_WIN", 60))
        self.tk_theta_max = float(getattr(config, "PAPER_TK_THETA_MAX", 0.85))
        self.tk_vol_mult = float(getattr(config, "PAPER_TK_VOL_MULT", 1.0))
        self.tk_fill = float(getattr(config, "PAPER_TK_FILL", 0.55))
        self.tk_trend = bool(getattr(config, "PAPER_TK_TREND", False))
        self._bars_held = 0
        self._last_bar_time = 0
        # Son LONG'dan bu yana ulasilan en yuksek fiyat. SHORT karari
        # "buradan geri cekildi mi" sorusuna dayanir.
        self.long_peak = 0.0
        self._on_event = on_event

        self.running = False
        self.position: Optional[Position] = None
        self.last_long_price: Optional[float] = None
        self.long_peak: float = 0.0
        self.trades: list[Trade] = []

        # Geriye donuk test (backtest) ozeti. Simulator BASLATILDIGINDA
        # grafikteki mumlarin BASINDAN simule edilir; boylece "simdiye
        # kadar ne kadar kazanirdi" sorusu olculmus olur.
        self.backtest_stats: Optional[dict] = None
        self._quiet = False        # backtest sirasinda olay basilmaz
        # Canli odagin basladigi an (yalnizca "Trade Basla" akisinda).
        self._live_started_at: Optional[float] = None

        # Kâr/zarar bu değere göre hesaplanır. Kullanıcı başlangıç bakiyesini
        # değiştirirse burası da güncellenir; aksi halde "başlangıç 1000,
        # bakiye 5000" durumunda %400 kâr görünürdü.
        self.start_balance = float(balance)

        # istatistikler
        self.gross_pnl = 0.0
        self.commission_paid = 0.0
        self.wins = 0
        self.losses = 0

    # ------------------------------------------------------------------
    # Ayarlar
    # ------------------------------------------------------------------
    def configure(self, balance: Optional[float] = None,
                  leverage: Optional[float] = None,
                  fee_rate: Optional[float] = None,
                  wallet_fraction: Optional[float] = None,
                  lookback: Optional[int] = None,
                  confirm: Optional[bool] = None,
                  short_rule: Optional[str] = None,
                  mode: Optional[str] = None,
                  min_hold: Optional[int] = None,
                  risk_pct: Optional[float] = None,
                  lock_pct: Optional[float] = None,
                  pull_atr: Optional[float] = None) -> None:
        with self._lock:
            self._configure(balance, leverage, fee_rate, wallet_fraction,
                            lookback, confirm, short_rule, mode, min_hold,
                            risk_pct, lock_pct, pull_atr)

    def _configure(self, balance: Optional[float] = None,
                   leverage: Optional[float] = None,
                   fee_rate: Optional[float] = None,
                   wallet_fraction: Optional[float] = None,
                   lookback: Optional[int] = None,
                   confirm: Optional[bool] = None,
                   short_rule: Optional[str] = None,
                   mode: Optional[str] = None,
                   min_hold: Optional[int] = None,
                   risk_pct: Optional[float] = None,
                   lock_pct: Optional[float] = None,
                   pull_atr: Optional[float] = None) -> None:
        if balance is not None and balance > 0:
            self.balance = float(balance)
            # Yeni baslangic bakiyesi: kâr/zarar buna gore olcerilir.
            # Pozisyon aciksa kâr hesabini bozmamak icin eski kalibrasyon
            # korunur (kimse yanlis "sifir kâr" gormesin).
            if self.position is None:
                self.start_balance = self.balance
        if leverage is not None and 1 <= leverage <= 125:
            self.leverage = float(leverage)
        if fee_rate is not None and 0 <= fee_rate < 0.01:
            self.fee_rate = float(fee_rate)
        if wallet_fraction is not None and 0 < wallet_fraction <= 1:
            self.wallet_fraction = float(wallet_fraction)
        if lookback is not None and 3 <= int(lookback) <= 200:
            self.lookback = int(lookback)
        if confirm is not None:
            self.confirm = bool(confirm)
        if short_rule in ("pullback", "entry"):
            self.short_rule = short_rule
        if mode in ("range", "signal", "signal_long", "signal_exit",
                    "ma_only", "osc_only", "trend", "muro", "1m", "ppt",
                    "tk"):
            if mode != self.mode:
                # Mod degisti: onceki sinyal gecersiz.
                self.last_signal = None
            self.mode = mode
        if mode == "tk":
            # OLCUMLU tik parametreleri (tools/research_tk.py +
            # tools/research_tk2.py + research_tk3.py pencere testi):
            #   BTC 5m : tp %3 sl %5 theta<=0.678  -> 3/3 pencere pozitif
            #   SOL 1m : tp %3 sl %5 theta<=0.85   -> +118$ / 3 pencere
            # Diger semboller ayni sl/tp, theta 0.85 (SOL etaloni).
            self.tk_on = True
            if "BTC" in self.symbol:
                self.tk_theta_max = 0.678
            else:
                self.tk_theta_max = 0.85
            self.tk_tp = 0.003
            self.tk_sl = 0.005
            self.tk_fill = 0.55
            self.tk_vol_mult = 1.0
        if min_hold is not None and 0 <= int(min_hold) <= 500:
            self.min_hold_bars = int(min_hold)
        if risk_pct is not None and 0 < float(risk_pct) <= 0.50:
            # Islem basina sermaye riski (trend + MURO + 1m + PPT modlari).
            # %50 ustu anlamsiz: tek bir stop hesabin yarisini siler.
            self.trend_risk_pct = float(risk_pct)
            self.muro_risk_pct = float(risk_pct)
            self.mode_1m_risk_pct = float(risk_pct)
            self.mode_ppt_risk_pct = float(risk_pct)
        if pull_atr is not None and 0 <= float(pull_atr) <= 5.0:
            # Girişte optimum nokta filtresi (ATR cinsinden).
            self.trend_pull_atr = float(pull_atr)
            self.mode_ppt_pull_atr = float(pull_atr)
        if lock_pct is not None and 0 <= float(lock_pct) <= 0.20:
            # Kâr bankalama eşiği (fiyat %). 0 = kilitleme KAPALI.
            # Kullanıcı kuralı: TÜM MODELLERDE aynı +%X bankalama.
            #   trend -> trend_lock_pct, MURO -> muro_cfg.lock_pct,
            #   1m -> trend_lock_pct, diğerleri -> bank_pct.
            lv = float(lock_pct)
            self.bank_pct = lv
            if self.mode == "muro":
                self.muro_cfg.lock_pct = lv
            elif self.mode in ("trend", "1m", "ppt"):
                self.trend_lock_pct = lv

    def reset(self, symbol: Optional[str] = None) -> None:
        """Simulasyonu sifirlar (coin degisiminde de cagrilir)."""
        with self._lock:
            if symbol:
                self.symbol = symbol
            self.running = False
            self.position = None
            self.last_long_price = None
            self.long_peak = 0.0
            self.trades = []
            self.last_signal = None
            self._bars_held = 0
            self._last_bar_time = 0
            self.balance = float(config.PAPER_INITIAL_BALANCE)
            self.start_balance = self.balance
            self.backtest_stats = None
            self.gross_pnl = 0.0
            self.commission_paid = 0.0
            self.wins = 0
            self.losses = 0

    # ------------------------------------------------------------------
    # Hesaplar
    # ------------------------------------------------------------------
    def unrealized(self, price: float) -> float:
        """
        Acik pozisyonun anlik kar/zarari.

        DIKKAT: acilis komisyonu (fee_open) ACILIS ANINDA bakiyeden
        dusulur. Burada bir daha dusulurse equity ayni komisyonu IKI
        kez sayar (olcum: acik pozisyon varken equity ~%0,1 eksik
        gosteriliyordu ve MURO'da pozisyon boyutu bu yuzden kucuk
        kaliyordu).
        """
        p = self.position
        if p is None:
            return 0.0
        raw = (price - p.entry) * p.qty if p.side == LONG \
            else (p.entry - price) * p.qty
        return raw

    def equity(self, price: float) -> float:
        return self.balance + self.unrealized(price)

    # ------------------------------------------------------------------
    # Bekleme (cooldown) — pozisyon dalgalanmasını engeller
    # ------------------------------------------------------------------
    def _simdi_ms(self, candles: list) -> float:
        """
        Şimdiki zaman (ms).

        Canlıda duvar saati (saniye hassasiyetinde bekleme şart).
        Geriye dönük testte barın PİYASA zamanı — testte saniyeler
        sıkışmaz, bar bar işlem olur.
        """
        if self._backtesting and candles:
            try:
                return float(candles[-1].open_time)
            except (AttributeError, TypeError, ValueError):
                pass
        return time.time() * 1000.0

    def _bekleme_kaldi_ms(self, candles: list) -> float:
        """Yeni pozisyon açmak için kalan süre (ms). 0 = bekleme yok."""
        kalan = self._no_entry_until - self._simdi_ms(candles)
        return kalan if kalan > 0 else 0.0

    def _bekleme_baslat(self, ms: float, candles: list) -> None:
        """Yeni pozisyon açılmayacağı süreyi başlat."""
        self._no_entry_until = self._simdi_ms(candles) + max(0.0, ms)

    def _durum_bildir(self, text: str, candles: list) -> None:
        """
        "Sessiz engel" durumlarini KISITLI aralikla olay akisina yazar.

        Kullanici sorunu: simulator pozisyon acmiyor ama NEDEN gosterilmiyordu
        (reclaim sarti kalicilik kilidi, pull filtresinin tepe beklemesi).
        Ayrinti burada raporlanir; ayni engel icin her
        PAPER_STATE_LOG_SEC'de bir kez yazilir (spam olmasin).
        """
        simdi = self._simdi_ms(candles)
        if simdi < self._state_log_until:
            return
        self._state_log_until = simdi + config.PAPER_STATE_LOG_SEC * 1000.0
        self._emit("info", f"Durum: {text}")

    # ------------------------------------------------------------------
    # Kural motoru
    # ------------------------------------------------------------------
    def _window(self, candles: list) -> list:
        return candles[-self.lookback:] if len(candles) > self.lookback \
            else list(candles)

    @staticmethod
    def _position_in_range(w: list, price: float) -> float:
        """
        Fiyatin pencere icindeki YERI: 0 = en taban, 1 = en zirve.

        Neden "fiyat == en dusuk" degil?
        ------------------------------
        Mum kapandiginda kapanis fiyati en dusuk noktadan AYRILMIS olur;
        birebir esitlik kontrolu hicbir zaman dogru degildi. Bunun yerine
        fiyatin pencere araligindaki KONUMU kullanilir:
            pos = (fiyat - enDusuk) / (enYuksek - enDusuk)
        0'a yakinse "grafikteki en taban noktasinda", 1'e yakinse
        "dusus eğilimine girdiği noktada" (zirve) demektir. Bu olcek
        bagimsizdir (dolar/jcoin fark etmez) ve her enstrumanda calisir.
        """
        low = min(c.low for c in w)
        high = max(c.high for c in w)
        # Savunma: bozuk (0/NaN) mum araligi sifirdan cikmasin. Binance
        # yeni acilan barda arada low=0 gonderiyor; onarim core'da yapilir
        # ama burada da tekrar kontrol ediyoruz.
        if not (low > 0) or not (high > 0):
            return 0.5
        if high - low <= 0:
            return 0.5                      # duz bant, anlam yok
        pos = (price - low) / (high - low)
        return max(0.0, min(1.0, pos))

    @staticmethod
    def _fib_state(w: list) -> tuple:
        """
        Pencere icindeki AUTO FIB salinim durumu: (leg, theta).

        leg   : salinim yonu (+1 yukari, -1 asagi, 0 bilinmiyor)
        theta : son kapanisin geri cekilme derinligi (0=uc, 0.618
                altin oran; NaN = aralik yok). Aralik motorunun
                "altin cebe" kurali bunu kullanir.
        """
        if len(w) < 5:
            return 0, float("nan")
        leg, _hi, _lo, th = fib_mod.retrace_series(
            [c.high for c in w], [c.low for c in w],
            [c.close for c in w], len(w))
        return int(leg[-1]), float(th[-1])

    def _long_signal(self, candles: list, price: float) -> Optional[str]:
        """
        LONG: fiyat pencerenin TABAN bolgesinde mi?

        Teyit (confirm) varsayilan KAPALI. Sebebi olcumdir:
            konum kriteri tek basina  bar basina  %9-19  -> 15m'de ~2 saatte bir
            + "yesil mum" teyidi ile   bar basina  %1,5-4,7 -> 4h'de ~70 saatte
        Ikincisi canli izlemesi imkansiz bir simulatordur. Ayrica tabanda
        olan mum DUSUS yonunde kapanmistir (dibi yapan mum odur), yani
        "yesil mum" diye beklemek dogru donus noktasini tamamen gecirir.
        """
        w = self._window(candles)
        if len(w) < 5:
            return None
        pos = self._position_in_range(w, price)
        if pos > config.PAPER_BOTTOM_POS:
            # AUTO FIB (fib_range_on): taban sarti yetmediyse ALTIN
            # CEBE kurali — penceredeki asagi salinim %44-68 geri
            # cekilme yapip donus bekliyorsa LONG acilir.
            if self.fib_range_on:
                leg, th = self._fib_state(w)
                if fib_mod.at_golden_pocket(th):
                    if self.confirm and \
                            not (w[-1].close > w[-1].open):
                        return None           # ayni donus teyidi
                    return ("altın cebe (fib geri çekilme " f"%{th*100:.0f}, konum %{pos*100:.0f})")
            return None                       # henuz tabanda değil
        if self.confirm and not (w[-1].close > w[-1].open):
            return None                       # istege bagli donus teyidi
        return f"pencere tabanında (konum %{pos*100:.0f})"

    def _short_signal(self, candles: list, price: float) -> Optional[str]:
        """
        SHORT: fiyat "dusus egilimine girdigi" noktada mi?

        Iki kural desteklenir (config.PAPER_SHORT_RULE / arayuzden secilir):

        "pullback" (varsayilan)
            Fiyat, son LONG'dan bu yana ulastigi ZIRVEDEN belirgin sekilde
            geri cekilmis olmali ve hala pencerenin ust bolgesinde olmali.
            Yani fiyat zirveyi yapti, sonra geri cekildi -> zirve teyit
            edildi, dusus basladi. Bu gercek bir "lower high" formasyonudur.

        "entry" (ilk formul)
            Fiyat son LONG'un GIRIS fiyatinin altinda olmali. Olcudde bu
            sart 4h'de 197/480 barin tamamini engelliyordu: SHORT hicbir
            zaman acilmadi.
        """
        w = self._window(candles)
        if len(w) < 5:
            return None

        pos = self._position_in_range(w, price)

        if self.short_rule == "entry":
            if self.last_long_price is None:
                return None        # referans yok -> karar vermiyoruz
            if price >= self.last_long_price:
                return None        # long fiyatini gecmis olurdu
            if pos < config.PAPER_TOP_POS:
                return None
            return (f"düşüş eğilimi başladı (pencere zirvesi, konum "
                    f"%{pos*100:.0f}), son LONG fiyatının altında")

        if pos < config.PAPER_TOP_POS and self.fib_range_on:
            # AUTO FIB: zirve bolgesi sarti yetmediyse ALTIN CEBE —
            # yukari salinim (tepe pencerede) %44-68 geri cekilme
            # yapiyor: donus bekleniyor, zirveden once satilir.
            leg, th = self._fib_state(w)
            if leg > 0 and fib_mod.at_golden_pocket(th):
                cek2 = (1.0 - float(th)) * 100.0
                return (f"altin cebe short (fib tepe geri çekilme "
                        f"%{cek2:.0f}, konum %{pos*100:.0f})")
        # --- pullback ---
        if self.long_peak <= 0:
            return None            # henuz LONG yok, zirve referansı yok
        if pos < config.PAPER_TOP_POS:
            return None            # zirve bölgesinde değil
        zirve = self.long_peak
        if price >= zirve * (1.0 - config.PAPER_PULLBACK):
            return None            # zirveden henuz geri çekilmedi
        cekilme = (zirve - price) / zirve * 100.0
        if self.confirm and not (w[-1].close < w[-1].open):
            return None            # istege bagli teyit
        return (f"zirve {zirve:,.4f}'den %{cekilme:.2f} geri çekildi "
                f"(pencere zirvesi, konum %{pos*100:.0f})")

    def _exit_for_long(self, candles: list, price: float) -> Optional[str]:
        """LONG kapisi: girişte dondurulan zirve seviyesine ulasildi mi?"""
        return None      # artik pozisyonun sabit hedefi kullanilir

    def _exit_for_short(self, candles: list, price: float) -> Optional[str]:
        return None

    # ------------------------------------------------------------------
    # Ana giris noktasi: her mum guncellemesinde cagrilir
    # ------------------------------------------------------------------
    def on_price(self, price: float, candles: list, timeframe: str,
                   signal: Optional[str] = None,
                   bar_low: Optional[float] = None,
                   bar_high: Optional[float] = None) -> Optional[str]:
        """
        Fiyat geldi. Acik pozisyon varsa kapatmayi dener, yoksa yeni
        pozisyon acmayi dener. Geri donus: olusan olayin aciklamasi
        (yoksa None).

        signal: gorege analizinin anlik karari ("AL", "SAT", "NÖTR", ...).
        Yalnizca mode == "signal" iken kullanilir.

        KILIT NOTU: analiz dongusu (servis thread'i) ve backtest (web
        thread'i) ayni anda burayi cagirabilir; kilit olmadan hesap
        bozulur.
        """
        with self._lock:
            return self._on_price(price, candles, timeframe, signal,
                                  bar_low, bar_high)

    def _on_price(self, price: float, candles: list,
                  timeframe: str,
                  signal: Optional[str] = None,
                  bar_low: Optional[float] = None,
                  bar_high: Optional[float] = None) -> Optional[str]:
        if not self.running or price <= 0 or len(candles) < 10:
            return None

        # Zirve takibi: gorulen en yuksek fiyat. SHORT karari "fiyat bu
        # zirveden geri cekildi mi" sorusuna dayandigi icin her fiyatta
        # guncellenir.
        if price > self.long_peak:
            self.long_peak = price

        # Yeni bar mi? (bar sayaci yalnizca yeni mumda artar; canli akista
        # saniyede onlarca kez on_price cagrilir, sayac olmasaydi
        # "kac bar tutuldu" sayimi anlamli olmazdi.)
        yeni_bar = False
        if candles:
            t_bar = candles[-1].open_time
            if t_bar != self._last_bar_time:
                self._last_bar_time = t_bar
                self._bars_held += 1
                yeni_bar = True

        # DUZELTICI (seri kilidi): zarar sonrasi K barda YENI GIRIS yok.
        # Pozisyon VARSA gate devreye girmez — cikis/stop/banka her zaman
        # calisir; bu koruma yalnizca yeni GIRISSI durdurur.
        # DÜZELTİCİ (seri kilidi + arm): zarar sonrasi K barda YENI GIRIS
        # yok; K dolunca ARM aktifse zarar yonune TERS sinyal gelmeden
        # girilmez (azap-degirmeni engeli: ayni sinyal stoplari yeniden
        # ucret prompt eder). Pozisyon VARSA gate devreye girmez -
        # cikis/stop/banka her zaman calisir; yalnizca YENI GIRISI durdurur.
        if self.corr_on and self.corr_strong_first and \
                self.corr_strong_only and self._guc_scope() and \
                signal in ("AL", "SAT"):
            signal = "NÖTR"

        if self.corr_on and self.position is None:
            if self._bars_held < self._corr_until:
                return None
            if self._corr_arm:
                yon = ("LONG" if signal in ("AL", "GÜÇLÜ AL")
                       else "SHORT" if signal in ("SAT", "GÜÇLÜ SAT")
                       else "")
                if yon == self._corr_arm:
                    # Zarar yonune yeniden girme yok: ters sinyal beklenir.
                    return None
                if yon and yon != self._corr_arm:
                    self._corr_arm = ""     # ters sinyal geldi: arm dustu

        # GÜÇÜ FIRTINA yen yazimi (PAPER_CORR_STRONG_ONLY): zayif AL/SAT
        # -> NÖTR. Pozisyon varsa NÖTR kurali kapanir ve bekler; yeni
        # giris acilmaz. Koken: zayif sinyaller giriş kalitesini
        # tasimiyor; olcum tools/research_karar.py GUC kolonlari.
        if self.corr_on and self.corr_strong_only and \
                self._guc_scope() and signal in ("AL", "SAT"):
            signal = "NÖTR"

        if self.mode == "tk":
            return self._tk(price, candles, timeframe,
                            bar_low, bar_high)

        # 1) likidasyon kontrolu
        p = self.position
        if p is not None:
            # 1c) takip eden stop — yalnizca YENI BARDA guncellenir.
            # Her tick'te guncellemek stopu fiyata yapistirip pozisyonu
            # gereksiz kapatirdi.
            #
            # ONEMLI: bir onceki barin KAPANISI kullanilir, mevcut
            # fiyat degil. Boylece stop, bir sonraki bar icin onceki
            # barin kapanisina gore hesaplanir (stop kontrolunden SONRA
            # uygulanmis olur). Aksi halde stop, icinde bulunulan barin
            # dip/zirvesi tarafindan ayni barda tetiklenirdi.
            if self.mode in ("trend", "1m", "ppt") and p.trail_mult > 0 and yeni_bar:
                a = trend_mod.atr_value([c.high for c in candles],
                                        [c.low for c in candles],
                                        [c.close for c in candles])
                if a > 0:
                    mesafe = p.trail_mult * a
                    ref = _onceki_kapanis(candles, price)
                    if p.side == LONG:
                        p.stop_price = max(p.stop_price, ref - mesafe)
                    else:
                        p.stop_price = min(p.stop_price, ref + mesafe)

            # 1c-2) MURO: trailing stop. Kâr kilitlemeden sonraki
            # "bedava" bacakta devreye girer (fiyat yüzdesi).
            # trail_always = True ise kilitten ÖNCE de devrede.
            if self.mode == "muro" and p is not None and \
                    (p.locked or self.muro_cfg.trail_always) and \
                    p.trail_frac > 0 and yeni_bar:
                ref = _onceki_kapanis(candles, price)
                if p.side == LONG:
                    p.stop_price = max(p.stop_price,
                                       ref * (1.0 - p.trail_frac))
                else:
                    p.stop_price = min(p.stop_price,
                                       ref * (1.0 + p.trail_frac))

            # 1a) STOP (trend + MURO) — LİKİDASYONDAN ÖNCE kontrol edilir.
            #
            # NEDEN SIRA ÖNEMLİ: Fiyat stop'a doğru yolunda likidasyon
            # fiyatından ÖNCE gelir. Önce likidasyon kontrol edilirse,
            # stop'a yetişemeden pozisyon sıfırlanır (ölçümde: aynı veri
            # üzerinde iki motor 3 kat farklı işlem sayısı çıkardı).
            #
            # Bar ici dusuk/yuksek GERIYE DONUK TESTTE verilir, canlida
            # verilmez: canlida pozisyon barin ortasinda acilmis olabilir;
            # o barin low/high'i giristen ONCE olusmus olabilir ve stop
            # yanlislikla tetiklenirdi. Canlida yalnizca anlik fiyat.
            if self.mode in ("trend", "muro", "1m", "ppt") and p.stop_price > 0:
                if p.side == LONG:
                    vurdu = price <= p.stop_price or \
                        (bar_low is not None and bar_low <= p.stop_price)
                else:
                    vurdu = price >= p.stop_price or \
                        (bar_high is not None and bar_high >= p.stop_price)
                if vurdu:
                    # GAP durumu: bar, stop'un OTUNDE acildiysa cikis
                    # fiyati barin ACILIS fiyatidir (daha kotu). Diger
                    # durumda stop fiyatinda cikilir.
                    acilis = _bar_acilisi(candles, price)
                    cikis = (min(p.stop_price, acilis) if p.side == LONG
                             else max(p.stop_price, acilis))
                    # GAP likidasyonu: bar, stop'un OTUNDE acildiysa ve
                    # likidasyon seviyesinin ALTINDA acildiysa pozisyon
                    # likidasyonda kapanir (borsa likidasyon fiyatinda
                    # kapatir, acilista degil).
                    if (p.side == LONG and cikis <= p.liq_price) or \
                            (p.side == SHORT and cikis >= p.liq_price):
                        self._close(p.liq_price, "LİKİDASYON (kaldıraç "
                                    "kaybı)", timeframe,
                                    )
                        if self.mode in ("trend", "1m", "ppt"):
                            self._bekleme_baslat(self.flip_cooldown_ms,
                                                 candles)
                        return "Likidasyon"
                    self._close(cikis, f"stop ({_px(p.stop_price)})",
                                timeframe,
                                )
                    if self.mode in ("trend", "1m", "ppt"):
                        # Ayni yone girilmeden once fiyat stop seviyesini
                        # geri almali (reclaim). Sart tarifli: TTL sonra
                        # dusur (kalici kilit olmasin).
                        self._reclaim_side = p.side
                        self._reclaim_level = p.stop_price
                        self._reclaim_out_bars = self._bars_held + \
                            config.PAPER_RECLAIM_TTL_BARS
                        # STOP SONRASI BEKLEME.
                        #
                        # KÖK NEDEN (ölçüm): stop'a yakılan pozisyon
                        # hemen aynı sinyal ile yeniden açılıyor ve aynı
                        # fiyattan tekrar stop oluyordu (BTC 1g'de 33 yerine
                        # 171 işlem!). Bu döngü komisyonu yiyordu.
                        # Şimdi stop sonrası 5 dk beklenir: fiyat yerleşir,
                        # sonra yeni bir stop ile yeniden girilir.
                        self._bekleme_baslat(self.flip_cooldown_ms, candles)
                    return "Stop"

            # 1b) LİKİDASYON
            if (p.side == LONG and price <= p.liq_price) or \
               (p.side == SHORT and price >= p.liq_price):
                self._close(price, "LİKİDASYON (kaldıraç kaybı)", timeframe,
                            )
                if self.mode in ("trend", "1m", "ppt"):
                    self._reclaim_side = p.side
                    self._reclaim_level = p.liq_price
                    self._reclaim_out_bars = self._bars_held + \
                        config.PAPER_RECLAIM_TTL_BARS
                    # Likidasyondan sonra da bekleme: ayni fiyattan
                    # tekrar likidasyon dongusu kurulmasin.
                    self._bekleme_baslat(self.flip_cooldown_ms, candles)
                return "Likidasyon"

            # 1b-2) MURO: KÂR KİLİDİ — fiyat %X ilerlediyse pozisyon
            # kapanır, kâr CÜZDANA yazılır ve AYNI YÖNDE yeniden pozisyon
            # açılır (stop = kilitlenen kâr seviyesinin altında).
            # Böylece trend devam etse bile kâr birikir, trend dönse bile
            # kâr cüzdanda kalır.
            if self.mode == "muro" and p is not None:
                lock = self.muro_cfg.lock_pct
                # KİLİT FİYATI = limit emir: fiyat o seviyeye DOKUNMALI.
                # Geriye donuk testte bar ici en yuksek/dusuk kullanilir
                # (dokunma = emir doldu). Canlida anlik fiyat kullanilir
                # (tick seviyeyi gectiyse emir dolmustur).
                # DIKKAT: kapanis fiyati seviyenin USTUNDE olmak dokunma
                # demek DEGILDIR; o durumda limit emir dolmamis olabilir.
                if p.side == LONG:
                    lock_px = p.entry * (1.0 + lock)
                    vurdu = (bar_high >= lock_px) if bar_high is not None \
                        else (price >= lock_px)
                else:
                    lock_px = p.entry * (1.0 - lock)
                    vurdu = (bar_low <= lock_px) if bar_low is not None \
                        else (price <= lock_px)
                if vurdu:
                    # Yeni stop ayni risk mesafesinde (basi bas seviyesi
                    # stop OLMAZ: mesafe ~0 olursa gurultude kapanir).
                    dist = (abs(p.entry - p.stop_price) / p.entry
                            if p.entry > 0 and p.stop_price > 0
                            else self.muro_cfg.min_stop_pct)
                    new_dist = min(dist, lock)
                    side = p.side
                    self._close(lock_px, "kâr kilidi", timeframe,
                                maker=True)
                    self._open(side, lock_px, "kâr kilidi sonrası", timeframe,
                               candles, stop_dist=new_dist, locked=True)
                    return (f"Kâr kilidi — {side} {lock*100:.1f}% kâr "
                            f"cüzdana yazıldı, aynı yönde yeniden açıldı")

            # 1b-3) TREND: KÂR KİLİDİ — fiyat %3 ilerlediyse pozisyon
            # kapanır, kâr CÜZDANA yazılır, kısa bir bekleme sonrası
            # pozisyon TEKRAR DEĞERLENDİRİLİR (kullanıcı isteği:
            # "hangi pozisyonda olurda olsun %3 kazanç sağladığında
            #  pozisyonu durdur, kazancı cüzdana aktar").
            #
            # KİLİT FİYATI limit emir gibidir: fiyat o seviyeye
            # dokunmalıdır. Canlida anlık fiyat, geriye dönük testte
            # bar içi en yüksek/düşük.
            if self.mode in ("trend", "ppt") and p is not None and \
                    self.trend_lock_pct > 0:
                lock = self.trend_lock_pct
                if p.side == LONG:
                    lock_px = p.entry * (1.0 + lock)
                    vurdu = (bar_high >= lock_px) if bar_high is not None \
                        else (price >= lock_px)
                else:
                    lock_px = p.entry * (1.0 - lock)
                    vurdu = (bar_low <= lock_px) if bar_low is not None \
                        else (price <= lock_px)
                if vurdu:
                    yon = p.side
                    self._close(lock_px, "kâr kilidi", timeframe,
                                maker=True)
                    if self.trend_lock_reentry == "protected":
                        # KORUMALI YENİ GİRİŞ (MURO mantığı): kâr
                        # cüzdana yazıldıktan SONRA aynı yönde yeni
                        # pozisyon açılır, ama stop KİLİT SEVİYESİNDE
                        # olur — yani bankalanan kâr geri verilemez.
                        # (Limit emir mantığı: fiyat o seviyeye dokundu,
                        #  orada dolduk.)
                        # Yeni stop: kilit seviyesinin ALTINDA, ayni risk
                        # mesafesi kadar (MURO mantigi). Boylece bankalanan
                        # kâr geri verilemez; yeni bacak en kotu durumda
                        # başa baş kapanir.
                        dist = (abs(p.entry - p.stop_price) / p.entry
                                if p.entry > 0 and p.stop_price > 0
                                else lock)
                        new_dist = min(dist, lock)
                        self._open(yon, lock_px, "kâr kilidi sonrası",
                                   timeframe, candles, stop_dist=new_dist,
                                   locked=True)
                        return (f"Kâr kilidi — {yon} %{lock*100:.1f} kâr "
                                f"cüzdana yazıldı, aynı yönde yeniden açıldı "
                                f"(stop kilit seviyesinde)")
                    # "wait & re-evaluate": kısa bekleme, sonra pozisyon
                    # yeniden değerlendirilir.
                    self._bekleme_baslat(self.lock_cooldown_ms, candles)
                    return (f"Kâr kilidi — {yon} %{lock*100:.1f} kâr cüzdana "
                            f"yazıldı, {self.lock_cooldown_ms/60000:.1f} dk "
                            f"bekleniyor (pozisyon yeniden değerlendirilecek)")

            # 1b-4) EVRENSEL KÂR BANKASI (tüm modlar) — kullanıcı kuralı:
            # "açılan pozisyonun KENDİ kazancı +%X olunca nakde çevir;
            #  kâr cüzdanda kalsın, sonra en uygun girişte devam et".
            # trend/muro kendi kilid bloklarını kullandığı için buraya
            # gelmez (varsayılanları da %2'ye eşitlendi). Diğer modların
            # (ma_only/osc_only/sinyal/1m/aralık) tek kâr çıkışı budur.
            #
            # KİLİT FİYATI limit emir gibidir: fiyat seviyeye
            # dokunmalıdır (bar içi ekstrem / anlık fiyat).
            #
            # SINYAL TEMİZLEME (reset_signal varsayılan = True): kâr
            # bankalandıktan sonra aynı sinyal TEKRAR geçerli sayılır —
            # kısa bekleme (lock_cooldown) sonrası sistem sinyali yeniden
            # değerlendirir ve EN UYGUN yone (AL -> LONG, SAT -> SHORT)
            # yeniden girer. Böylece "banka + devam" şeklinde işler.
            p2 = self.position
            if p2 is not None and \
                    self.mode not in ("trend", "muro", "ppt") and \
                    self.bank_pct > 0:
                lock = self.bank_pct
                if p2.side == LONG:
                    lock_px = p2.entry * (1.0 + lock)
                    vurdu = (bar_high is not None and bar_high >= lock_px) \
                        or (price >= lock_px)
                else:
                    lock_px = p2.entry * (1.0 - lock)
                    vurdu = (bar_low is not None and bar_low <= lock_px) \
                        or (price <= lock_px)
                if vurdu:
                    self._close(lock_px,
                                f"kâr bankası +%{lock*100:.0f}", timeframe,
                            maker=True)
                    self._bekleme_baslat(self.lock_cooldown_ms, candles)
                    return (f"Kâr bankası — {p2.side} %{lock*100:.0f} kâr "
                            f"cüzdana yazıldı; "
                            f"{self.lock_cooldown_ms/60000:.1f} dk sonra "
                            f"sinyal yeniden değerlendirilir")

            # 1b-5) BAŞABAŞ KORUMASI (TÜM MODLAR) — kullanıcı kuralı:
            # "pozisyon zarara geçmeden kapat": fiyat giriş fiyatına
            # GERİ DÖNMEYE başladıysa (giriş + komisyon payı seviyesine
            # dokunursa) pozisyon kapatılır; net zarar ~0 civarı kalır.
            #
            #   LONG  : çıkış eşiği = entry * (1 + komisyon payı)
            #   SHORT : çıkış eşiği = entry * (1 - komisyon payı)
            #
            # GİRİŞ BARINDA devreye girmez (giriş salınımı trips); sonraki
            # bardan itibaren aktiftir. Durak/likidasyondan SONRA
            # kontrol edilir; kâr bankaları önce gelir (favori taraf).
            # 1b-5b) DUZELTICI CEKIRDEK (skor modlari): genis tolerans
            # stop. Eski mikro-klip yerine:
            #   * GIRIS x (1 - corr_stop_down) altini kapanis veya bar
            #     acilisi gorurse MARKET cikis (adil: fiyat=veri).
            #   * Mikro-klip YOK: pozisyon +2% bankaya kadar yasayabilir
            #     (kullanici kurali: evrensel +%2 kâr bankasi).
            #   * Zarar sourasi: satlar stop_out = -(stop_down) x
            #     kaldirac x kese... lose sorunu olcume bagli.
            p3 = self.position
            if p3 is not None and p3.entry_bar and self._corr_active() and \
                    int(candles[-1].open_time) != int(p3.entry_bar):
                stop_frac = self.corr_stop_down
                tetik = False
                if p3.side == LONG:
                    stop_px = p3.entry * (1.0 - stop_frac)
                    acilis = float(candles[-1].open) if candles else price
                    if acilis < stop_px:
                        # Bar stopun ALTINDA acildi: market acilisi.
                        tetik, cikis = True, acilis
                    elif candles[-1].close < stop_px:
                        # Kapanis stopun altinda: bar kapanisinda market.
                        tetik, cikis = True, candles[-1].close
                    else:
                        tetik = False
                else:
                    stop_px = p3.entry * (1.0 + stop_frac)
                    acilis = float(candles[-1].open) if candles else price
                    if acilis > stop_px:
                        tetik, cikis = True, acilis
                    elif candles[-1].close > stop_px:
                        tetik, cikis = True, candles[-1].close
                    else:
                        tetik = False
                if tetik:
                    self._close(cikis, "duzeltici stop", timeframe)
                    self._bekleme_baslat(self.lock_cooldown_ms, candles)
                    return f"Duzeltici stop - {p3.side} parf. %{stop_frac*100:.1f} asti ({_px(cikis)})"
            p3 = self.position
            be_buf = self._be_buf(
                p3.timeframe if p3 is not None else None)
            if p3 is not None and p3.entry_bar and \
                    int(candles[-1].open_time) != int(p3.entry_bar) and \
                    be_buf > 0:
                acilis = float(candles[-1].open) if candles else price
                tetik = False
                maker_dolum = False
                if p3.side == LONG:
                    be_px = p3.entry * (1.0 + be_buf)
                    if acilis < p3.entry:
                        # Bar girisin ALTINDA acildi: esikteki limit
                        # DOLMAZ, pozisyon zaten tersine dondu — "koruma"
                        # anlamini kaybetmesin: ACILIS fiyatindan (market)
                        # cikilir.
                        tetik, cikis, maker_dolum = True, acilis, False
                    elif bar_high is not None and bar_low is not None and \
                            bar_low <= be_px <= bar_high:
                        # ESIK BAR ARALIGININ ICINDE: fiyatin o barda
                        # seviyeye dokundugu belli -> sell-limit dolu
                        # sayilir. Bar esige hic gitmisse (high < esik)
                        # dolmez, pozisyon yasar (adil dolum kurali).
                        tetik, cikis, maker_dolum = True, be_px, True
                    elif bar_high is None and price <= be_px:
                        # Canli (bar araligi yok): tick esigi asti (market).
                        tetik, cikis, maker_dolum = True, price, False
                else:
                    be_px = p3.entry * (1.0 - be_buf)
                    if acilis > p3.entry:
                        # Bar girisin USTUNDE acildi: buy-limit dolmaz,
                        # pozisyon tersine dondu — acilis fiyatindan
                        # (market) cikilir.
                        tetik, cikis, maker_dolum = True, acilis, False
                    elif bar_high is not None and bar_low is not None and \
                            bar_low <= be_px <= bar_high:
                        # ESIK BAR ARALIGININ ICINDE -> buy-limit dolu.
                        tetik, cikis, maker_dolum = True, be_px, True
                    elif bar_low is None and price >= be_px:
                        # Canli (bar araligi yok): tick esigi asti (market).
                        tetik, cikis, maker_dolum = True, price, False

                if tetik:
                    # Kapanışta sinyal TEMİZLENİR + kısa bekleme: aksi
                    # halde eşik çevresinde aç-kapa döngüsü (komisyon
                    # yeme) kurulur. Bekleme bitince sinyal YENİDEN
                    # değerlendirilir ve en uygun yone girilir.
                    self._close(cikis, "başabaş koruması", timeframe,
                                maker=maker_dolum)
                    if self.mode in ("trend", "1m", "ppt"):
                        # Aynı yone girmeden önce eşik geri alınmalı
                        # (stop-after-reclaim kuralıyla aynı mantık).
                        self._reclaim_side = p3.side
                        self._reclaim_level = be_px
                        self._reclaim_out_bars = self._bars_held + \
                            config.PAPER_RECLAIM_TTL_BARS
                        self._bekleme_baslat(self.flip_cooldown_ms, candles)
                    elif self.mode == "muro":
                        self._bekleme_baslat(self.flip_cooldown_ms, candles)
                    else:
                        self._bekleme_baslat(self.lock_cooldown_ms, candles)
                    return (f"Başabaş koruması — {p3.side} zarara geçmeden "
                            f"kapatıldı ({_px(cikis)})")

            # 2) GIRISTE DONDURULAN hedefe ulasildi mi?
            #    (Yuvarlanan pencere kullanılmıyor: pencere bir bar kayınca
            #     "dibden zirveye" zıplayıp her pozisyonu tek barda
            #     kapatıyordu.)
            if p.target > 0:
                if (p.side == LONG and price >= p.target) or \
                   (p.side == SHORT and price <= p.target):
                    self._close(price,
                                f"hedefe ulaşıldı ({p.target:,.4f})",
                                timeframe)
                    return "Hedefe ulaşıldı"

            # 2b) YALNIZCA MA / YALNIZCA OSILATÖR modlari.
            #
            # KULLANICI KURALI (guncel):
            #   "Sadece hareketli ortalamalara göre SHORT LONG yap."
            #   "Sadece osilatörlere göre SHORT LONG yap."
            #   "LONG'dan NÖTR geçtiğinde veya SHORT'tan NÖTR geldiğinde
            #    karşı pozisyona GECMESIN, pozisyonu kapatsın. Beklesin.
            #    NÖTR'de ne SHORT ne de LONG yapsın."
            #
            # DÖNGÜ:
            #   * Art arda LONG  → LONG zaten açık, İŞLEM YAPILMAZ
            #   * SAT geldi      → LONG kapanır, SHORT açılır
            #   * NÖTR geldi     → pozisyon KAPANIR, ters yön AÇILMAZ
            #                      (nakitte bekleme)
            #   * Art arda SHORT → SHORT zaten açık, İŞLEM YAPILMAZ
            #   * AL geldi       → SHORT kapanır, LONG açılır
            #   * NÖTR geldi     → pozisyon KAPANIR, ters yön AÇILMAZ
            #
            # NÖTR SONRASI: yeni sinyal gelene kadar beklenir. AL gelirse
            # LONG, SAT gelirse SHORT acilir (pozisyon yoksa giris blogu).
            #
            # Bu blok POZISYON ACIKKEN calisir — aksi halde asagidaki
            # sinyal bloguna hic ulasilamaz (proje tarihinde yasanmis hata).
            if self.mode in ("ma_only", "osc_only", "trend", "1m", "ppt") and signal:
                if signal == self.last_signal:
                    return None                 # ayni yon: dokunma
                if self._bars_held < self.min_hold_bars:
                    # Bekleme suresi dolmadi. SIKICI: last_signal BURADA
                    # guncellenmez; yoksa ayni sinyal gelmeye devam ettigi
                    # icin "sinyal degisti" kontrolu bir sonraki tick'te
                    # True olur ve pozisyon SONSUZA kadar bekler.
                    # (Testte yakalandi: min_hold=5 iken kapanma hic olmadi.)
                    return None
                self.last_signal = signal       # bekleme gecti, simdi kaydet

                dusus = signal in ("SAT", "GÜÇLÜ SAT")
                yukselis = signal in ("AL", "GÜÇLÜ AL")
                nötr = signal == "NÖTR"
                kaynak = ("hareketli ortalamalar" if self.mode == "ma_only"
                          else "osilatörler" if self.mode == "osc_only"
                          else "Supertrend" if self.mode == "trend"
                          else "PP-Supertrend" if self.mode == "ppt"
                          else "MTF (1m)")

                # ---- NÖTR: KAPAT VE BEKLE, TERS YÖN ACMA ----
                if nötr:
                    # NÖTR-HOLD (ölçüm varyantı, ntr_hold=True): NÖTR
                    # hemen market kapatmak yerine pozisyonu BE klip
                    # (kâra dönünce maker çıkış) ve düzeltici stopuna
                    # korumasına bırakır. Üretim default'u KAPALI.
                    if getattr(self, "ntr_hold", False):
                        return (f"{p.side} tutuldu — NÖTR "
                                f"(klip/stop koruması devrede)")
                    # Kullanici kurali: ne LONG ne SHORT acilir.
                    self._close(price, f"{signal} ({kaynak})", timeframe)
                    return (f"{p.side} kapandı — {signal} · {kaynak} "
                            f"(nakitte bekleniyor)")

                if p.side == LONG and not yukselis:
                    # SAT: LONG kapanır.
                    #
                    # TREND MODUNDA karşı yön HEMEN AÇILMAZ: önce piyasa
                    # biraz durulur (5 dk), sonra sinyal yeniden
                    # değerlendirilir. Aksi halde yön her tikte değişir ve
                    # komisyon kazancı yer (HYPE logu).
                    #
                    # ma_only/osc_only modlarında eski davranış korunur
                    # (anında ters yön) — o modların kendi kuralları ve
                    # testleri var.
                    yon = p.side
                    self._close(price, f"{signal} ({kaynak})", timeframe)
                    if self.mode in ("trend", "ppt"):
                        # Yon degisti: reclaim blogu gecersiz.
                        self._reclaim_side = ""
                        self._reclaim_level = 0.0
                        self._reclaim_out_bars = 0
                        self._bekleme_baslat(self.flip_cooldown_ms, candles)
                        return (f"{yon} kapandı — {signal} · {kaynak} "
                                f"({self.flip_cooldown_ms/60000:.0f} dk "
                                f"bekleme, sonra yön yeniden "
                                f"değerlendirilecek)")
                    self._open(SHORT, price, f"{signal} ({kaynak})",
                               timeframe, candles)
                    return (f"SHORT açıldı — {signal} · {kaynak} "
                            f"({yon} kapandı)")

                if p.side == SHORT and not dusus:
                    yon = p.side
                    self._close(price, f"{signal} ({kaynak})", timeframe)
                    if self.mode in ("trend", "ppt"):
                        # Yon degisti: reclaim blogu gecersiz.
                        self._reclaim_side = ""
                        self._reclaim_level = 0.0
                        self._reclaim_out_bars = 0
                        self._bekleme_baslat(self.flip_cooldown_ms, candles)
                        return (f"{yon} kapandı — {signal} · {kaynak} "
                                f"({self.flip_cooldown_ms/60000:.0f} dk "
                                f"bekleme, sonra yön yeniden "
                                f"değerlendirilecek)")
                    self._open(LONG, price, f"{signal} ({kaynak})",
                               timeframe, candles)
                    return (f"LONG açıldı — {signal} · {kaynak} "
                            f"({yon} kapandı)")
                return None

            # 3) SİNYAL TERS YÖN: pozisyon kapatılır ve tersi açılır.
            #    SAT geldiyse LONG kapanır + SHORT açılır.
            #    (Bu kontrol POZISYON ACIKKEN yapilir; aksi halde sinyal
            #     bloguna hic ulasilamaz ve hicbir sinyal islenmez.)
            #
            # NOTR KURALI (kullanıcı, tüm sinyal modlarına):
            #   "LONG'dan NÖTR geçtiğinde veya SHORT'tan NÖTR geldiğinde
            #    karşı pozisyona GECMESIN, pozisyonu kapatsın. Beklesin."
            #
            #   signal_exit HARIC: girisi araliktan gelir; sadece SAT
            #   sinyali kapatir (asili zararda kalmasin diye).
            if self.mode in ("signal", "signal_long", "signal_exit") and signal:
                # Kâr bankası sonrasi kısa bekleme: bankalanan kâr
                # cüzdanda kalır, pozisyon hemen yeniden açılmaz.
                if self._bekleme_kaldi_ms(candles) > 0:
                    return None
                if signal == self.last_signal:
                    return None
                self.last_signal = signal
                dusus = signal in ("SAT", "GÜÇLÜ SAT")
                yukselis = signal in ("AL", "GÜÇLÜ AL")
                nötr = signal == "NÖTR"

                # GIRIS aralık kuralindan, CIKIS sinyalden:
                # acik LONG, SAT sinyalinde kapanir (asili zararda kalmasin).
                if self.mode == "signal_exit":
                    if p.side == LONG and dusus:
                        self._close(price, f"{signal} sinyali", timeframe)
                        return f"LONG kapandı — {signal} sinyali (nötrde beklendi)"
                    return None

                # ---- NÖTR: KAPAT VE BEKLE, TERS YÖN ACMA ----
                if nötr:
                    self._close(price, f"{signal} sinyali", timeframe)
                    return (f"{p.side} kapandı — {signal} sinyali "
                            f"(nakitte bekleniyor)")

                if p.side == LONG and dusus:
                    # Sinyal_LONG modunda sadece KAPATIR; SHORT acmaz.
                    # signal modunda min. bekleme suresi gecerlidir.
                    if self.mode == "signal" and self._bars_held < self.min_hold_bars:
                        return None        # cok yeni, bekle
                    self._close(price, f"{signal} sinyali", timeframe)
                    if self.mode == "signal":
                        self._open(SHORT, price, f"{signal} sinyali",
                                   timeframe, candles)
                        return (f"SHORT açıldı — {signal} sinyali "
                                f"(LONG kapandı)")
                    return f"LONG kapandı — {signal} sinyali (nötrde beklendi)"

                if p.side == SHORT and yukselis:
                    if self.mode == "signal" and self._bars_held < self.min_hold_bars:
                        return None
                    self._close(price, f"{signal} sinyali", timeframe)
                    if self.mode == "signal":
                        self._open(LONG, price, f"{signal} sinyali",
                                   timeframe, candles)
                        return (f"LONG açıldı — {signal} sinyali "
                                f"(SHORT kapandı)")
                    return f"SHORT kapandı — {signal} sinyali"
            # MURO'da akis DEVAM etmeli: aksiyon (AL/SAT/KAPAT) asagida,
            # pozisyonun disinda islenir. Diger modlarda burada biter.
            if self.mode != "muro":
                return None

        # ------------------------------------------------------------------
        # 2c) MURO — yeni algoritma
        #
        # Aksiyonlar (core.muro):
        #   AL / SAT         : giris (ters yon aciksa once kapatilir)
        #   LONG_KAPAT       : yapı kırıldı -> long kapanır
        #   SHORT_KAPAT      : yapı kırıldı -> short kapanır
        #
        # TERS YÖN KURALI: "short'a zarar ederek girmesin" — ters yön
        # sinyali geldiğinde mevcut pozisyon kapanır ve yeni pozisyon
        # aynı fiyattan açılır; kâr kilidi ile bankalanan kâr cüzdanda
        # kalır (geri verilmez).
        # ------------------------------------------------------------------
        if self.mode == "muro" and signal:
            # BEKLEME: yön değişiminden/kilitten sonra yeni pozisyon
            # açılmaz (pozisyon dalgalanması olmasın).
            if self._bekleme_kaldi_ms(candles) > 0:
                return None
            if signal == self.last_signal:
                return None                 # ayni aksiyon: dokunma
            self.last_signal = signal
            cur = self.position

            if signal == muro_mod.LONG_KAPAT:
                if cur is not None and cur.side == LONG:
                    self._close(price, "yapı kırıldı", timeframe)
                    self._bekleme_baslat(self.flip_cooldown_ms, candles)
                    return ("LONG kapandı — yapı kırıldı (MURO) · "
                            f"{self.flip_cooldown_ms/60000:.0f} dk bekleme")
                return None

            if signal == muro_mod.SHORT_KAPAT:
                if cur is not None and cur.side == SHORT:
                    self._close(price, "yapı kırıldı", timeframe)
                    self._bekleme_baslat(self.flip_cooldown_ms, candles)
                    return ("SHORT kapandı — yapı kırıldı (MURO) · "
                            f"{self.flip_cooldown_ms/60000:.0f} dk bekleme")
                return None

            if signal == muro_mod.AL:
                if cur is not None and cur.side == SHORT:
                    self._close(price, "ters yön", timeframe)
                    # Karşı yön HEMEN açılmaz: önce bekleme (pozisyon
                    # dalgalanması olmasın), sonra yeniden değerlendirilir.
                    self._bekleme_baslat(self.flip_cooldown_ms, candles)
                    return ("SHORT kapandı — ters yön (MURO) · "
                            f"{self.flip_cooldown_ms/60000:.0f} dk bekleme")
                if self.position is None:
                    self._open(LONG, price,
                               "AL (Supertrend + geri çekilme)",
                               timeframe, candles)
                    return "LONG açıldı — MURO AL"
                return None

            if signal == muro_mod.SAT:
                if cur is not None and cur.side == LONG:
                    self._close(price, "ters yön", timeframe)
                    self._bekleme_baslat(self.flip_cooldown_ms, candles)
                    return ("LONG kapandı — ters yön (MURO) · "
                            f"{self.flip_cooldown_ms/60000:.0f} dk bekleme")
                if self.position is None:
                    self._open(SHORT, price,
                               "SAT (Supertrend + geri çekilme)",
                               timeframe, candles)
                    return "SHORT açıldı — MURO SAT"
                return None

        # ------------------------------------------------------------------
        # 2b-A) PPST SESSIZ BEKLEME RAPORU: pozisyon YOK + karar NÖTR/"".
        #
        # pull filtresi optimum nokta beklerken karar "" (bos) gelir:
        # yon +1/-1 olabilir ama girilmez. Kullanici "hic acmiyor"
        # goruyordu; NEDENI burada raporlanir (PAPER_STATE_LOG_SEC'de bir).
        # ------------------------------------------------------------------
        if self.mode == "ppt" and self.position is None and \
                signal in (None, "", "NÖTR") and \
                self._bekleme_kaldi_ms(candles) == 0 and candles:
            try:
                _, dseri = ppst.ppsupertrend(
                    [c.high for c in candles], [c.low for c in candles],
                    [c.close for c in candles],
                    self.mode_ppt_period, self.mode_ppt_mult)
                yon_v = int(dseri[-1]) if dseri.size else 0
            except Exception:      # noqa: BLE001
                yon_v = 0
            if yon_v > 0:
                self._durum_bildir(
                    "PP-Supertrend yönü AL, pozisyon açılmadı — fiyat "
                    "dönen tepeye yakın; optimum nokta filtresi geri "
                    "çekilmeyi bekliyor", candles)
            elif yon_v < 0:
                self._durum_bildir(
                    "PP-Supertrend yönü SAT, pozisyon açılmadı — fiyat "
                    "dönen dibe yakın; optimum nokta filtresi tepenin "
                    "dönüşünü bekliyor", candles)

        # ------------------------------------------------------------------
        # 2b) YALNIZCA MA / OSILATÖR — pozisyon YOKKEN giris
        #
        # NÖTR geldiğinde pozisyon açılmaz (bekle). Sıralı sinyal
        # (LONG → SAT → LONG) ilk pozisyonu zaten yukarıdaki açık
        # pozisyon bloğu açıyor.
        # ------------------------------------------------------------------
        if self.mode in ("ma_only", "osc_only", "trend", "1m", "ppt") and signal:
            # BEKLEME (cooldown): pozisyon kapandıktan sonra yeni
            # pozisyon açılmaz. Kullanıcı isteği: "pozisyon
            # değişmlerinde mevcut pozisyonu kapattıktan sonra 5 dk
            # bekle ki stabilite sağlansın".
            #
            # last_signal BURADA guncellenmez; aksi halde ayni sinyal
            # geldigi icin bekleme bitince de pozisyon acilamazdi.
            if self._bekleme_kaldi_ms(candles) > 0:
                return None
            if signal == self.last_signal:
                return None
            # STOP SONRASI RECLAIM: ayni yone, fiyat stop seviyesini geri
            # almadan girilmez. Boylece (a) stop dongusu kurulmaz,
            # (b) kaybeden pozisyon hemen yenisiyle degistirilmez.
            # SART TARIFLIDIR: 12 bar sonra (PAPER_RECLAIM_TTL_BARS) blok
            # duser — yoksa kalici "hic acmiyor" kilidi kuruluyordu.
            if self.mode in ("trend", "1m", "ppt") and self._reclaim_side:
                if self._bars_held >= self._reclaim_out_bars:
                    # 12 bar doldu: sart dustu — blok temizlenir.
                    self._reclaim_side = ""
                    self._reclaim_level = 0.0
                    self._reclaim_out_bars = 0
                else:
                    long_mu = signal in ("AL", "GÜÇLÜ AL")
                    short_mu = signal in ("SAT", "GÜÇLÜ SAT")
                    if self._reclaim_side == LONG and long_mu and \
                            price < self._reclaim_level:
                        self._durum_bildir(
                            f"{signal} bekliyor — stop seviyesi "
                            f"({_px(self._reclaim_level)}) geri alınmadan "
                            "aynı yone girilmez (reclaim şartı)", candles)
                        return None
                    if self._reclaim_side == SHORT and short_mu and \
                            price > self._reclaim_level:
                        self._durum_bildir(
                            f"{signal} bekliyor — stop seviyesi "
                            f"({_px(self._reclaim_level)}) geri alınmadan "
                            "aynı yone girilmez (reclaim şartı)", candles)
                        return None
                    # Reclaim oldu ya da yon degisti -> blok temizlenir.
                    self._reclaim_side = ""
                    self._reclaim_level = 0.0
                    self._reclaim_out_bars = 0
            self.last_signal = signal
            kaynak = ("hareketli ortalamalar" if self.mode == "ma_only"
                      else "osilatörler" if self.mode == "osc_only"
                      else "Supertrend" if self.mode == "trend"
                      else "PP-Supertrend" if self.mode == "ppt"
                      else "MTF (1m)")

            if signal in ("SAT", "GÜÇLÜ SAT"):
                self._open(SHORT, price, f"{signal} ({kaynak})", timeframe,
                           candles)
                return f"SHORT açıldı — {signal} · {kaynak}"
            if signal in ("AL", "GÜÇLÜ AL"):
                self._open(LONG, price, f"{signal} ({kaynak})", timeframe,
                           candles)
                return f"LONG açıldı — {signal} · {kaynak}"
            return None                      # NÖTR: giris yok

        # ------------------------------------------------------------------
        # 3) SİNYAL MODU: gösterge analizi karar verir
        #    SAT (veya GÜÇLÜ SAT) gelince LONG kapanır, SHORT açılır.
        #    AL (veya GÜÇLÜ AL) gelince SHORT kapanır, LONG açılır.
        # ------------------------------------------------------------------
        if self.mode in ("signal", "signal_long") and signal:
            # Sinyal DEGİŞTİĞİNDE aksiyon al. Aynı sinyal her fiyatta
            # gelir; sürekli aç-kapa yapmamak için geçiş şart.
            if signal == self.last_signal:
                return None
            self.last_signal = signal

            if signal in ("SAT", "GÜÇLÜ SAT"):
                if self.mode == "signal":
                    if self.position is not None and self.position.side == LONG:
                        self._close(price, f"{signal} sinyali", timeframe)
                    self._open(SHORT, price, f"{signal} sinyali", timeframe,
                               candles)
                    return f"SHORT açıldı — {signal} sinyali"
                return None          # signal_long: SHORT acilmaz

            if signal in ("AL", "GÜÇLÜ AL"):
                if self.position is not None and self.position.side == SHORT:
                    self._close(price, f"{signal} sinyali", timeframe)
                self._open(LONG, price, f"{signal} sinyali", timeframe, candles)
                return f"LONG açıldı — {signal} sinyali"
            return None

        # ------------------------------------------------------------------
        # 4) ARALIK MODU: fiyat penceresinin taban/zirvesi karar verir
        #
        # DIKKAT: bu blok MOD kontrolu olmadan calisirdi. Diger modlar
        # yukaridaki bloklarda her zaman dondugu icin sorun gorunmuyordu;
        # ancak MURO'da akis buraya kadar gelince "aralik modu" pozisyonlari
        # AÇILIYORDU (yanlis kural, cok fazla islem). Duzeltildi.
        # signal_exit GİRİŞİ aralık mantığıyla yapar (sadece ÇIKIŞI
        # sinyalden olur) — o yuzden o da bu bloga dahil.
        # ------------------------------------------------------------------
        if self.mode not in ("range", "signal_exit"):
            return None

        long_reason = self._long_signal(candles, price)
        if long_reason:
            self._open(LONG, price, long_reason, timeframe, candles)
            return f"LONG açıldı — {long_reason}"

        short_reason = self._short_signal(candles, price)
        if short_reason:
            self._open(SHORT, price, short_reason, timeframe, candles)
            return f"SHORT açıldı — {short_reason}"
        return None

    # ------------------------------------------------------------------
    def start_live(self) -> None:
        """
        Yalnizca CANLI islem: hesap sifirlanir, gecmis oynatilmaz.

        "Trade Basla" butonunun arkasinin dengi. Kullanicinin sordugu:
        cüzdandaki USDT ile o andan itibaren islem acilsin, sonraki
        kâr/zarar canli izlensin.
        """
        with self._lock:
            # reset() bakiyeyi PAPER_INITIAL_BALANCE'a cekiyor; oysa
            # kullanici panelden kendi USDT'sini girdi. Baslangic
            # bakiyesini reset ONCESI koruyoruz.
            baslangic = self.balance
            self.reset(self.symbol)
            self.balance = baslangic
            self.start_balance = baslangic
            self.running = True
            self._live_started_at = time.time()

    # ------------------------------------------------------------------
    def _build_signal_series(self, candles: list,
                             timeframe: str) -> list:
        """
        Geriye donuk test icin bar basina sinyal dizisi uretir.

        Kural moduna gore KAYNAK degisir (bkz. service._signal_for_mode):
          signal / signal_long / signal_exit : bilesik skor
          ma_only     : 15 hareketli ortalamanin skoru
          osc_only    : 11 osilatorun skoru

        Osilator modunda daha kucuk esikler kullanilir; bilesik esikler
        11 osilatorun ortalamasi icin neredeyse hic asilmaz.
        """
        from core.analysis import analyze
        import config as cfg

        # YENI: trend modu analyze() cagirmaz — Supertrend tek basina
        # yeterli ve daha hizli. Ayni fonksiyon canlida da kullanilir.
        if self.mode == "trend":
            # Karar serisi: yon (Supertrend) + optimum nokta filtresi +
            # guclu sinyal bypass'i. Canli akis AYNI fonksiyonu kullanir
            # (core/trend.py::decide_series) -> test ve canli ayni.
            strong = None
            try:
                res = analyze(
                    symbol=self.symbol or "TESTUSDT", timeframe=timeframe,
                    open_times=[c.open_time for c in candles],
                    o=[c.open for c in candles], h=[c.high for c in candles],
                    l=[c.low for c in candles], c=[c.close for c in candles],
                    v=[c.volume for c in candles],
                    close_times=[c.close_time for c in candles],
                    strong_threshold=self.thresholds()[1],
                    base_threshold=self.thresholds()[0])
                strong = trend_mod.strong_series(res.signals)
            except Exception:      # noqa: BLE001
                strong = None
            return trend_mod.decide_series(
                [c.high for c in candles],
                [c.low for c in candles],
                [c.close for c in candles],
                strong=strong,
                period=self.trend_period, mult=self.trend_mult,
                pull_atr=self.trend_pull_atr,
                pull_bars=self.trend_pull_bars)

        # 1M OPTIMIZED: Multi-TF trend follow with 1m pullback entry
        if self.mode == "1m":
            # Karar serisi: yon (15m+5m Supertrend) + optimum nokta filtresi +
            # guclu sinyal bypass'i. Canli akis AYNI fonksiyonu kullanir
            # (core/trend.py::decide_series) -> test ve canli ayni.
            strong = None
            try:
                res = analyze(
                    symbol=self.symbol or "TESTUSDT", timeframe=timeframe,
                    open_times=[c.open_time for c in candles],
                    o=[c.open for c in candles], h=[c.high for c in candles],
                    l=[c.low for c in candles], c=[c.close for c in candles],
                    v=[c.volume for c in candles],
                    close_times=[c.close_time for c in candles],
                    strong_threshold=self.thresholds()[1],
                    base_threshold=self.thresholds()[0])
                strong = trend_mod.strong_series(res.signals)
            except Exception:      # noqa: BLE001
                strong = None
            return trend_mod.decide_series(
                [c.high for c in candles],
                [c.low for c in candles],
                [c.close for c in candles],
                strong=strong,
                period=self.mode_1m_trend_period, mult=self.mode_1m_trend_mult,
                pull_atr=self.mode_1m_pullback_atr,
                pull_bars=self.mode_1m_pullback_ema)

        # PPT: Pivot Point Supertrend karari — trend ile ayni akis.
        if self.mode == "ppt":
            # Karar serisi: yon (PP-Supertrend) + optimum nokta filtresi +
            # guclu sinyal bypass'i. Canli akis AYNI fonksiyonu kullanir
            # (core/ppst.py::decide_series) -> test ve canli ayni.
            strong = None
            try:
                res = analyze(
                    symbol=self.symbol or "TESTUSDT", timeframe=timeframe,
                    open_times=[c.open_time for c in candles],
                    o=[c.open for c in candles], h=[c.high for c in candles],
                    l=[c.low for c in candles], c=[c.close for c in candles],
                    v=[c.volume for c in candles],
                    close_times=[c.close_time for c in candles],
                    strong_threshold=self.thresholds()[1],
                    base_threshold=self.thresholds()[0])
                strong = trend_mod.strong_series(res.signals)
            except Exception:      # noqa: BLE001
                strong = None
            return ppst.decide_series(
                [c.high for c in candles],
                [c.low for c in candles],
                [c.close for c in candles],
                strong=strong,
                period=self.mode_ppt_period, mult=self.mode_ppt_mult,
                pull_atr=self.mode_ppt_pull_atr,
                pull_bars=self.mode_ppt_pull_bars)

        # MURO: aksiyon serisi (AL / SAT / LONG_KAPAT / SHORT_KAPAT).
        # Canli akista da ayni kod kullanilir (core.muro).
        if self.mode == "muro":
            return muro_mod.actions(
                [c.open for c in candles],
                [c.high for c in candles],
                [c.low for c in candles],
                [c.close for c in candles],
                self.muro_cfg)

        strong = self.thresholds()[1]
        base = self.thresholds()[0]

        # ONCE TEK SEFERDE TUM GECMISI ANALIZ ET.
        #
        # analyze() TEK CAGRIDA tum gecmisin bar basina skoru uretiyor
        # VE NEDENSELDIR: signals[i] yalnizca i'ye kadar olan mumlara bakar
        # (150/150 kesme testiyle dogrulanmis). Bu yuzden "her bar icin
        # ayri analyze()" yerine TEK cagri yeterlidir.
        #
        # PERFORMANS: bar basina yeniden hesap 500 bar x ~55 ms = ~26 sn
        # suruyordu; tek cagri ~50 ms.
        try:
            res = analyze(
                symbol=self.symbol, timeframe=timeframe,
                open_times=[c.open_time for c in candles],
                o=[c.open for c in candles], h=[c.high for c in candles],
                l=[c.low for c in candles], c=[c.close for c in candles],
                v=[c.volume for c in candles],
                close_times=[c.close_time for c in candles])
        except Exception:      # noqa: BLE001
            return [None] * len(candles)

        if self.mode == "ma_only":
            seriler = res.ma_scores
        elif self.mode == "osc_only":
            seriler = res.oscillator_scores
        else:
            # ONEMLI: res.signals bir LISTE DE Signal ENUM'U dondurur
            # (Signal.SELL), metin DEGIL. _on_price string karsilastirmasi
            # yaptigi icin enum liste donulurse HICBIR sinyal islenmez
            # (olcum: signal/signal_long 0 islem veriyordu).
            vals = [s.value if hasattr(s, "value") else s
                    for s in res.signals]
            # AUTO FIB: sinyal ailesine (signal/signal_long/signal_exit)
            # fib gate uygulanir; ARALIK modu uygulanmaz (aralik girişleri
            # kendi pencere motorudur, asagida).
            if self.mode in ("signal", "signal_long", "signal_exit") \
                    and self.fib_score_on:
                vals = fib_mod.gate_labels(
                    vals, [c.high for c in candles],
                    [c.low for c in candles],
                    [c.close for c in candles], True,
                    self.fib_window, self.fib_gate)
            return vals

        if self.mode == "osc_only":
            s2 = cfg.PAPER_OSC_STRONG_THRESHOLD
            b2 = cfg.PAPER_OSC_BASE_THRESHOLD
        else:
            s2, b2 = strong, base

        out: list = []
        for i in range(len(candles)):
            x = seriler[i] if i < len(seriler) else None
            if x is None or x != x:            # None / NaN
                out.append(None)
            elif x >= s2:
                out.append("GÜÇLÜ AL")
            elif x >= b2:
                out.append("AL")
            elif x <= -s2:
                out.append("GÜÇLÜ SAT")
            elif x <= -b2:
                out.append("SAT")
            else:
                out.append("NÖTR")
        # AUTO FIB: skor serisine fib gate (altın cebe GÜÇLÜ, uç engel).
        # Canlida da AYNI kural isler (service.mode_signal_series).
        if self.fib_score_on:
            out = fib_mod.gate_labels(
                out, [c.high for c in candles], [c.low for c in candles],
                [c.close for c in candles], True,
                self.fib_window, self.fib_gate)
        return out

    # ------------------------------------------------------------------
    def thresholds(self) -> tuple[float, float]:
        """(AL/SAT esigi, GÜÇLÜ esigi) — arayuz ayarlari. Varsayilan
        config'den gelir."""
        return (float(getattr(self, "_base_threshold",
                              config.PAPER_BASE_THRESHOLD)),
                float(getattr(self, "_strong_threshold",
                              config.PAPER_STRONG_THRESHOLD)))

    # ------------------------------------------------------------------
    def backtest(self, candles: list, timeframe: str,
                   signals: Optional[list] = None) -> dict[str, Any]:
        """
        Grafikteki mumlarin BASINDAN bugune kadar hizli tekrar.

        Amac: "bu bot simdiye kadar ne kadar kazanirdi?" sorusunu
        OLCULEBILIR kilmak. Hesap sifirlanir, tum gecmis mumlar tek tek
        canlandirilir, sonuc gunumuzdeki (canli) durumda birakilir;
        ardindan canli akis ayni hesapla devam eder.

        Bu tek yonlu (her mumun kapanisinda) bir tekardir; mum ici
        fiyat hareketi simule edilmez. Bu yuzden sonuclar gercek
        goturuden farkli olabilir.

        Donus: ozet sozluk.
        """
        with self._lock:
            self.reset(self.symbol)
            self.running = True
            self._quiet = True               # her islem icin log basma
            self._live_started_at = None    # geriye donuk test canli degil
            # Bekleme (cooldown) sureleri PIYASA zamani ile olcer:
            # geriye donuk testte bar bar ilerler.
            self._backtesting = True
            self._no_entry_until = 0.0

            start = self.lookback
            n = len(candles)
            if n <= start + 1:
                self._quiet = False
                self.running = False
                self.backtest_stats = {"bars": n, "trades": 0, "wins": 0,
                                       "losses": 0, "net": 0.0,
                                       "commission": 0.0, "error": "yetersiz mum"}
                return self.backtest_stats

            t0 = time.monotonic()
            try:
                if signals is None and self.mode in ("signal", "signal_long",
                                                     "signal_exit",
                                                     "ma_only", "osc_only",
                                                     "trend", "muro", "1m",
                                                     "ppt"):
                    # Sinyal listesi YOKSA ve karar modu sinyal tabanliysa
                    # burada analiz yapip signal listesini kendimiz uretiriz.
                    #
                    # ONCEDEN: signals=None dogrudan geciliyordu ve
                    # _on_price signal=None aliyordu -> sinyal bloklari
                    # hic calismiyor, TUM MODLAR AYNI SONUCU VERIYORDU
                    # (olcum: range/signal/ma_only/osc_only hepsi 981,50).
                    #
                    # Sinyal yalnizca KAPANMIS barlardan uretilir: olusan
                    # bar icinde yon tik tik degisiyor ve geriye donuk
                    # testte de pozisyon dalgalanmasi olusuyordu.
                    signals = self._build_signal_series(
                        _kapali_mumlar(candles), timeframe)
                for i in range(start, n):
                    window = candles[i - start + 1:i + 1]
                    sig = signals[i] if signals and i < len(signals) else None
                    self._on_price(candles[i].close, window, timeframe, sig,
                                   candles[i].low, candles[i].high)
            finally:
                self._quiet = False
                self._backtesting = False

            for t in self.trades:
                t.mode = "backtest"

            stats = {
                "bars": n,
                "from": int(candles[start].open_time),
                "to": int(candles[-1].open_time),
                "timeframe": timeframe,
                "mode": self.mode,
                "trades": len(self.trades),
                "wins": self.wins,
                "losses": self.losses,
                "gross_pnl": round(self.gross_pnl, 2),
                "commission": round(self.commission_paid, 2),
                "balance": round(self.balance, 2),
                "equity": round(self.equity(candles[-1].close), 2),
                "profit": round(self.equity(candles[-1].close)
                                - self.start_balance, 2),
                "return_pct": round(
                    (self.equity(candles[-1].close) / self.start_balance - 1)
                    * 100, 2) if self.start_balance else 0.0,
                "open_position": self.position.side if self.position else None,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
            self.backtest_stats = stats
            logger.info("Geriye dönük test: %s", stats)
            return stats

    # ------------------------------------------------------------------
    def _open(self, side: str, price: float, reason: str, timeframe: str,
              candles_for_target: Optional[list] = None,
              stop_dist: Optional[float] = None,
              locked: bool = False,
              maker: bool = False) -> None:
        if price <= 0:
            return
        eq = self.equity(price)
        if eq <= 0:
            return

        # Varsayilan (eski) boyutlandirma: teminat x kaldirac.
        # fixed_stake (olcum modu): compounding yok; yoksa farkli islem
        # sayisina sahip konfigler karsilastirilamaz halde olurdu.
        stake_eq = self.start_balance if self.fixed_stake else eq
        margin = stake_eq * self.wallet_fraction
        notional = margin * self.leverage
        eff_lev = self.leverage
        stop_price = 0.0
        trail_mult = 0.0
        trail_frac = 0.0
        liq_dist = 0.0

        if stop_dist is not None:
            # Kâr kilidi sonrası yeniden giriş: aynı risk mesafesi.
            stop_price = (price * (1.0 - stop_dist) if side == LONG
                          else price * (1.0 + stop_dist))
            stop_frac = abs(price - stop_price) / price
            if stop_frac <= 0:
                return
            eff_lev = min(self.leverage, self.muro_max_lev,
                          0.6 / stop_frac)
            notional = eq * self.muro_risk_pct / stop_frac
            notional = min(notional, eq * self.wallet_fraction * eff_lev)
            if notional <= 0:
                return
            liq_dist = 1.5 * stop_frac
            margin = notional * liq_dist
            trail_frac = self.muro_cfg.trail_pct
        elif self.mode == "muro":
            # MURO: yapısal stop + risk bazlı boyutlandırma.
            #
            # Stop = girişten sonraki en dip (long) / en tepe (short),
            # risk kapisi ile sınırlı. Pozisyon, stop mesafesi kadar
            # ters gidince sermayenin risk_pct kadari gidecek şekilde
            # açılır: notional = equity * risk / stop_mesafesi(%)
            # Kaldıraç yalnızca ÜST SINIRDIR (likidasyon stop'tan önce).
            seg = (candles_for_target or [])[-self.muro_cfg.k - 1:]
            lows = [c.low for c in seg]
            highs = [c.high for c in seg]
            stop_price = muro_mod.structural_stop(
                1 if side == LONG else -1, price, lows, highs,
                self.muro_cfg.k + 1, self.muro_cfg)
            if stop_price <= 0:
                return
            stop_frac = abs(price - stop_price) / price
            if stop_frac <= 0:
                return
            eff_lev = min(self.leverage, self.muro_max_lev,
                          0.6 / stop_frac)
            notional = eq * self.muro_risk_pct / stop_frac
            notional = min(notional, eq * self.wallet_fraction * eff_lev)
            if notional <= 0:
                return
            # Likidasyon stop'un 1,5 katinda (teminat = notional*liq_dist)
            liq_dist = 1.5 * stop_frac
            margin = notional * liq_dist
            trail_frac = self.muro_cfg.trail_pct
        elif self.mode == "trend":
            # RISK BAZLI BOYUTLANDIRMA.
            #
            # Kullanicinin istedigi 10x/20x burada UST SINIRDIR. Pozisyon,
            # stop mesafesi kadar ters gidince sermayenin trend_risk_pct
            # kadari gidecek sekilde acilir:
            #       notional = equity * risk / stop_mesafesi(%)
            # Boylece kaldirac, stop'un likidasyondan ONCE gelmesini
            # garantileyen bir tavan olur; gercekte ~0,1-0,6x kullanilir.
            a = 0.0
            if candles_for_target:
                a = trend_mod.atr_value(
                    [c.high for c in candles_for_target],
                    [c.low for c in candles_for_target],
                    [c.close for c in candles_for_target])
            if a <= 0:
                return              # ATR yok (isinma) -> islem acma
            stop_dist = self.trend_stop_atr * a
            stop_frac = stop_dist / price
            if stop_frac <= 0:
                return
            # Likidasyon stop'tan SONRA gelmeli (liq mesafesi ~ 1/lev).
            eff_lev = min(self.leverage, self.trend_max_lev,
                          0.6 / stop_frac)
            notional = eq * self.trend_risk_pct / stop_frac
            notional = min(notional, eq * self.wallet_fraction * eff_lev)
            margin = notional / eff_lev if eff_lev > 0 else 0.0
            stop_price = price - (stop_dist if side == LONG else -stop_dist)
            trail_mult = self.trend_trail_atr
        elif self.mode in ("1m", "ppt"):
            # 1M / PPT OPTIMIZED: trend ile ayni risk-tabanli sema, KENDI
            # parametreleriyle (daha dar stop, sinirli kaldirac).
            # PPT: Pivot Point Supertrend modu — ayni yapi, PAPER_PPT_*
            # parametreleri.
            if self.mode == "1m":
                stop_atr = self.mode_1m_stop_atr
                trail_atr = self.mode_1m_trail_atr
                min_stop = self.mode_1m_min_stop_pct
                max_stop = self.mode_1m_max_stop_pct
                risk_pct = self.mode_1m_risk_pct
                max_lev = self.mode_1m_max_lev
            else:
                stop_atr = self.mode_ppt_stop_atr
                trail_atr = self.mode_ppt_trail_atr
                min_stop = self.mode_ppt_min_stop_pct
                max_stop = self.mode_ppt_max_stop_pct
                risk_pct = self.mode_ppt_risk_pct
                max_lev = self.mode_ppt_max_lev
            a = 0.0
            if candles_for_target:
                a = trend_mod.atr_value(
                    [c.high for c in candles_for_target],
                    [c.low for c in candles_for_target],
                    [c.close for c in candles_for_target])
            if a <= 0:
                return              # ATR yok (isinma) -> islem acma
            stop_dist = stop_atr * a
            stop_frac = stop_dist / price
            # ATR dabası cok dar gelirse gurultude kapanmasin:
            stop_frac = max(stop_frac, min_stop)
            stop_frac = min(stop_frac, max_stop)
            if stop_frac <= 0:
                return
            stop_dist = stop_frac * price
            # Likidasyon stop'tan SONRA gelmeli (liq mesafesi ~ 1/lev).
            eff_lev = min(self.leverage, max_lev,
                          0.6 / stop_frac)
            notional = eq * risk_pct / stop_frac
            notional = min(notional, eq * self.wallet_fraction * eff_lev)
            margin = notional / eff_lev if eff_lev > 0 else 0.0
            stop_price = price - (stop_dist if side == LONG else -stop_dist)
            trail_mult = trail_atr

        qty = notional / price if price > 0 else 0.0
        if qty <= 0 or margin <= 0 or notional <= 0:
            return
        # Pasif (resting) LIMIT giris = maker ucreti; market analiz
        # girisleri taker kalir. Tk (super-hizli limit scalper) burada
        # komisyon terazi sini kayar: roundtrip %0.10 -> %0.04.
        o_fee = self.maker_rate if maker else self.fee_rate
        fee_open = notional * o_fee
        self.balance -= fee_open
        self.commission_paid += fee_open

        # likidasyon fiyati: teminatin tamamen bitigi seviye
        # (MURO'da teminat = notional*liq_dist; diger modlarda
        #  teminat x kaldirac modeli)
        if not liq_dist:
            liq_dist = 1.0 / eff_lev if eff_lev > 0 else 0.0
        liq = price * (1.0 - liq_dist) if side == LONG \
            else price * (1.0 + liq_dist)

        # Hedef = giris anindaki pencerenin zirvesi (LONG) / dibi (SHORT).
        # Dondurulur: pencere kaydikca degismez.
        w = self._window(candles_for_target) if candles_for_target else []
        if w:
            win_low = min(c.low for c in w)
            win_high = max(c.high for c in w)
        else:
            win_low = win_high = price
        if self.mode in ("trend", "muro", "1m", "ppt"):
            # Trend / MURO / 1m / PPT modunda sabit hedef YOK: cikis stop,
            # trail veya sinyal (+kâr kilidi) ile.
            target = 0.0
        else:
            target = win_high if side == LONG else win_low

        # Hedefin anlamsiz oldugu iki durum var:
        #
        #  a) Giriş fiyatinin YANINDA kalmasi (pencere dar, zirve girişin
        #     altinda kalmis).
        #  b) Giriş fiyatina EŞİT olmasi.
        #
        # (b) KESINLIKLE Düzeltilmeliydi: hedef = giriş yapilirsa
        # kapanma kontrolü `fiyat <= target` (LONG) / `fiyat >= target`
        # (SHORT) POZISYONUN ACILDIKI ANDA doğru olur ve simule
        # oluşmadan kapanirdi. Testte yakalandi: "SAT → SHORT açıldı"
        # sonrası bir sonraki fiyatta "Hedefe ulaşıldı" ile kapaniyordu.
        #
        # Düzeltme: hedef girişle aynıysa HEDEF YOK say (0) — kapanma
        # yalnizca likidasyon veya sinyal ile olur.
        if (side == LONG and target <= price) or \
           (side == SHORT and target >= price):
            # Pencere, giris fiyatinin tamamen disinda kalmis (fiyat
            # pencerenin disina cikmis). Hedef burada anlamsiz.
            #
            # ONCEDEN: target = price yapiliyordu. Bu, kapanma kontrolunu
            # (`fiyat >= target` SHORT icin) POZISYONUN ACILDIKI ANDA
            # dogru yapiyordu -> "SAT ile SHORT açıldı" sonrasi ilk
            # fiyatta "Hedefe ulaşıldı" ile kapaniyor, sinyal dongusu
            # hic calismiyordu. Testte yakalandi.
            #
            # SIMDI: hedef yok sayilir (0). Kapanma yalnizca likidasyon
            # veya sinyal ile olur.
            target = 0.0

        self.position = Position(
            side=side, entry=price, qty=qty, margin=margin, notional=notional,
            fee_open=fee_open, liq_price=liq,
            opened_at=(int(candles_for_target[-1].open_time)
                       if candles_for_target else time.time()),
            timeframe=timeframe, reason=reason,
            target=target, window_low=win_low, window_high=win_high,
            stop_price=stop_price, trail_mult=trail_mult,
            eff_leverage=eff_lev, trail_frac=trail_frac, locked=locked,
            entry_bar=(int(candles_for_target[-1].open_time)
                       if candles_for_target else 0))
        self._bars_held = 0        # yeni pozisyon: bekleme sayaci sifirlanir
        if side == LONG:
            self.last_long_price = price
            # Zirve referansi buradan yeniden baslar: LONG'dan sonraki
            # yukselisin tepe noktasi, SHORT'un referansidir.
            if self.long_peak <= price:
                self.long_peak = price

        if self.mode == "muro":
            self._emit("trade",
                       f"{side} açıldı @ {_px(price)} · "
                       f"efektif {eff_lev:.2f}x · teminat {margin:,.2f} · "
                       f"stop {_px(stop_price)} · "
                       f"kâr kilidi %{self.muro_cfg.lock_pct*100:.1f} · "
                       f"risk %{self.muro_risk_pct*100:.1f} · {reason}")
        elif self.mode == "trend":
            self._emit("trade",
                       f"{side} açıldı @ {_px(price)} · "
                       f"efektif {eff_lev:.2f}x · teminat {margin:,.2f} · "
                       f"stop {_px(stop_price)} · "
                       f"risk %{self.trend_risk_pct*100:.1f} · "
                       f"komisyon {fee_open:,.4f} · {reason}")
        elif self.mode == "ppt":
            self._emit("trade",
                       f"{side} açıldı @ {_px(price)} · "
                       f"efektif {eff_lev:.2f}x · teminat {margin:,.2f} · "
                       f"stop {_px(stop_price)} · "
                       f"risk %{self.mode_ppt_risk_pct*100:.1f} · "
                       f"komisyon {fee_open:,.4f} · {reason}")
        else:
            self._emit("trade",
                       f"{side} açıldı @ {_px(price)} · "
                       f"{self.leverage:g}x · teminat {margin:,.2f} · "
                       f"komisyon {fee_open:,.4f} · hedef {_px(target)} · "
                       f"{reason}")

    def _be_buf(self, tf: Optional[str] = None) -> float:
        """Basabas tamponu (bar araliginda dokunma ile dolum).
        DUZELTICI mikro-klipsi SADECE corr_tfs icindeki TF'lerde getiri
        uretir: buyuk bar araligi (1h ~%0.5-1.5) tamponun dokunulup
        adil dolmasini mumkun kilar; kucuk TF'lerde (5m ~%0.1) tampon
        bar araligini asip HAYALI dolum uretiyor (olcum: tools/
        research_be2.py honest-fill kolonu)."""
        if tf is None or self.mode not in ("ma_only", "osc_only",
                                           "signal", "signal_long",
                                           "signal_exit", "range"):
            return self.breakeven_buf
        if self.corr_on and self.corr_be_buf > 0 and tf in self.corr_tfs:
            return self.corr_be_buf
        return self.breakeven_buf

    def _guc_scope(self) -> bool:
        """GÜÇLÜ-only yen yazimi yalnizca skor tabanli modlarda: muro
        aksiyon akisi AL/SAT uzerinde kurulu — komple NÖTR'e cevirince
        mod hic islem acmaz (olcum: tools/research_uretim.py)."""
        return self.mode in ("ma_only", "osc_only", "signal",
                             "signal_long", "signal_exit", "range")

    def _corr_active(self) -> bool:
        """DUZELTICI stop-rejimi skor tabanli modlarda aktif mi?"""
        return bool(self.corr_on and self.corr_stop_down > 0 and
                    self.mode in ("ma_only", "osc_only", "signal",
                                  "signal_long", "signal_exit", "range"))

    def _tk(self, price: float, candles: list, timeframe: str,
            bar_low: Optional[float], bar_high: Optional[float]
            ) -> Optional[str]:
        """TICK — super-hizli TAMAMEN-LIMIT scalper (maker ucret motoru).

        FELSEFE (bilinen trader yaklasimlari: fib retracement scalp,
        pullback continuation, volume onay):
          * LONG: yukari salinim leg'i sonrasi fiyat ALTIN CEBE
            (%44-67.8 geri cekilme) dokunurken pasif BUY LIMIT konur.
            Fiyat levela INERKEN dolarsa maker ucretle girilir.
          * TP: resting SELL LIMIT (maker) giris x (1+tk_tp).
          * SL: stop-market (taker) giris x (1-tk_sl).
          * Talep onayi: salinim baci volume'u pencere ortalamasinin
            uzerinde olmali (zayif salinim = fake out).

        DURUST DOLUM KURALLARI (mevcut duzeltici modeliyle ayni):
          * Buy limit YALNIZCA bar o seviyeye INERKEN dolarsa (open>=L
            ve low<=L): maker. Open zaten seviyenin altindaysa limit
            pahali olurdu (marketable) -> giris SKIPTIR.
          * TP sell limit yalnizca seviye bar araligindaysa dolu (maker).
          * SL stop-market: acilis stop altindaysa acilis fiyatindan
            (taker); aksi halde stopPx (taker).
        """
        p = self.position

        # ------------------------------------------------------------------
        # 1) ACIK POZISYON: TP klip / SL stop
        # ------------------------------------------------------------------
        if p is not None:
            tp = getattr(p, "tk_tp", 0.0)
            stop = getattr(p, "tk_stop", 0.0)
            acilis = float(candles[-1].open) if candles else price
            # --- TP: resting limit (maker) ---
            if tp > 0:
                if p.side == LONG:
                    if bar_high is not None and bar_low is not None:
                        if bar_low <= tp <= bar_high:
                            self._close(tp, "tk hedefe ulaşıldı",
                                        timeframe, maker=True)
                            return "TICK: hedef klip (maker)"
                    elif price >= tp:                      # canli tik
                        self._close(price, "tk hedefe ulaşıldı",
                                    timeframe, maker=True)
                        return "TICK: hedef klip (maker)"
                else:
                    if bar_high is not None and bar_low is not None:
                        if bar_low <= tp <= bar_high:
                            self._close(tp, "tk hedefe ulaşıldı",
                                        timeframe, maker=True)
                            return "TICK: hedef klip (maker)"
                    elif price <= tp:
                        self._close(price, "tk hedefe ulaşıldı",
                                    timeframe, maker=True)
                        return "TICK: hedef klip (maker)"
            # --- SL: stop-market (taker) ---
            if stop > 0:
                if p.side == LONG:
                    if acilis <= stop:
                        self._close(acilis, "tk stop", timeframe)
                        return f"TICK: stop ({_px(acilis)})"
                    if bar_low is not None and bar_low <= stop:
                        self._close(stop, "tk stop", timeframe)
                        return f"TICK: stop ({_px(stop)})"
                    if bar_low is None and price <= stop:
                        # Canli tik (bar araligi yok): tick stopu asti.
                        self._close(price, "tk stop", timeframe)
                        return f"TICK: stop ({_px(price)})"
                else:
                    if acilis >= stop:
                        self._close(acilis, "tk stop", timeframe)
                        return f"TICK: stop ({_px(acilis)})"
                    if bar_high is not None and bar_high >= stop:
                        self._close(stop, "tk stop", timeframe)
                        return f"TICK: stop ({_px(stop)})"
                    if bar_high is None and price >= stop:
                        self._close(price, "tk stop", timeframe)
                        return f"TICK: stop ({_px(price)})"
            # pozisyon yasar: diger kontrol yok (tk bundan ibaret)
            return None

        # ------------------------------------------------------------------
        # 2) SETUP + PASIF GIRIS (altin cebe dokunu)
        # ------------------------------------------------------------------
        if len(candles) < 10 or not self.tk_on:
            return None
        h = [c.high for c in candles]
        l = [c.low for c in candles]
        c_ = [c.close for c in candles]
        leg, hit, lot, th = fib_mod.retrace_series(
            h, l, c_, self.tk_window)
        legv = int(leg[-1]) if leg.size else 0
        if legv == 0:
            return None
        hi_l = float(hit[-1])
        lo_l = float(lot[-1])
        rng = hi_l - lo_l
        if rng <= 0:
            return None
        theta = float(th[-1])
        theta_max = getattr(self, "tk_theta_max", 0.85)
        if not (fib_mod.GOLDEN_LO <= theta <= theta_max):
            return None                       # ne cok yuzeyde ne cok derin

        # Talep onayi: salinim hacmi pencere ortalamasinin UZERINDE
        vol = [getattr(c, "volume", 0.0) or 0.0 for c in candles]
        if vol and sum(vol) > 0:
            ort = sum(vol) / len(vol)
            if max(vol[-3:]) < ort * getattr(self, "tk_vol_mult", 1.0):
                return None                   # zayif salinim: fake out

        # Trend uyumu (knob): LONG yukarı SMA200 ustunde, SHORT altında
        # (pullback-continuation; ters trend fadeleri elenir).
        if getattr(self, "tk_trend", False) and len(c_) >= 50:
            sma200 = sum(c_[-200:]) / min(200, len(c_))
            if (legv > 0 and c_[-1] < sma200) or \
                    (legv < 0 and c_[-1] > sma200):
                return None

        acilis = float(candles[-1].open)
        if legv > 0:
            # LONG: pasif AL limit altin cebe icinde (tk_fill)
            L = hi_l - getattr(self, "tk_fill", 0.55) * rng
            doldu = False
            if bar_low is not None:
                # Bar-daba: bar seviyeye INERKEN dolu (durst).
                doldu = acilis >= L and bar_low <= L
            else:
                # Canli tik: tick seviyeye INDIyse (acilis ustundeyse
                # resting limit adi gecerli; tick altindaysa pahali).
                doldu = acilis >= L and price <= L
            if doldu:
                self._open(LONG, L, "TICK: altin cebe al-limit",
                           timeframe, candles, maker=True)
                q = self.position
                if q is not None:
                    q.tk_tp = L * (1.0 + self.tk_tp)
                    q.tk_stop = L * (1.0 - self.tk_sl)
                return "TICK: LONG limit doldu (maker)"
        else:
            # SHORT: pasif SAT limit altin cebe icinde (tk_fill)
            L = lo_l + getattr(self, "tk_fill", 0.55) * rng
            doldu = False
            if bar_high is not None:
                doldu = acilis <= L and bar_high >= L
            else:
                # Canli tik: tick seviyeye CIKTUYSA resting limit dolu.
                doldu = acilis <= L and price >= L
            if doldu:
                self._open(SHORT, L, "TICK: altin cebe sat-limit",
                           timeframe, candles, maker=True)
                q = self.position
                if q is not None:
                    q.tk_tp = L * (1.0 - self.tk_tp)
                    q.tk_stop = L * (1.0 + self.tk_sl)
                return "TICK: SHORT limit doldu (maker)"
        return None

    def _close(self, price: float, reason: str, timeframe: str,
               reset_signal: bool = True, maker: bool = False) -> None:
        p = self.position
        if p is None:
            return
        notional_close = p.qty * price
        # Cikis komisyonu ayrisma: LIMIT dolumlu cikislar (basabas klip
        # dokunmasi / kâr kilidi / kâr bankasi) resting emirdir -> maker
        # ucreti; NÖTR-flip / stop / likidasyon MARKET'tir -> taker.
        fc_rate = self.maker_rate if maker else self.fee_rate
        fee_close = notional_close * fc_rate
        gross = (price - p.entry) * p.qty if p.side == LONG \
            else (p.entry - price) * p.qty
        net = gross - p.fee_open - fee_close

        self.balance += gross - fee_close
        self.gross_pnl += gross
        self.commission_paid += fee_close
        if net >= 0:
            self.wins += 1
        else:
            self.losses += 1

        self.trades.append(Trade(
            side=p.side, entry=p.entry, exit=price, qty=p.qty, margin=p.margin,
            gross_pnl=gross, fee_open=p.fee_open, fee_close=fee_close,
            net_pnl=net, opened_at=p.opened_at, closed_at=time.time(),
            timeframe=timeframe, reason=p.reason, exit_reason=reason,
            symbol=self.symbol,
        ))
        self.position = None

        # DUZELTICI (seri kilidi): zarar biten islemden sonra K bar
        # yeni GIRIS yok. Gate _on_price basinda ( pozisyon yokken ).
        if self.corr_on and net < 0:
            if self.corr_pause_bars > 0:
                self._corr_until = self._bars_held + int(self.corr_pause_bars)
            if self.corr_arm_on:
                # ARM: pause_bars=0 olsa bile zarar yonu isaretlenir.
                self._corr_arm = p.side

        # SONRAKI SİNYALİN AYNI OLABİLMESİ İÇİN SIFIRLA.
        #
        # KULLANICI BUGÜN BUNU RAPORLADI:
        #   "NÖTR durumuna geçtikten sonra hareketli ortalamalar SAT
        #    emri verdiyse shorta girmesi lazım, ama hiçbir işlem
        #    yapmadı."
        #
        # KÖK NEDEN: sinyal değişimine göre işlem açılıyor
        # (`signal == self.last_signal` → dokunma). Pozisyon hedef/
        # likidasyon ile kapandığında last_signal ESKI sinyalde kalıyordu.
        # Aynı yönde yeni bir sinyal geldiğinde "değişiklik yok" sanılıp
        # yok sayılıyordu → sistem sessizce işlem açmıyordu.
        #
        # Kapatma her seferinde son sinyali temizler: aynı yönde yeni bir
        # sinyal geldiğinde yeniden pozisyon açılabilir.
        #
        # ISTISNA: STOP ve LİKİDASYON kapanışlarında sinyal TEMİZLENMEZ.
        # Çünkü sinyal değişmedi — sadece pozisyon kapandı. Temizlenirse
        # aynı sinyal bir sonraki tick'te (veya bar'da) yeniden pozisyon
        # açar, aynı fiyattan tekrar stop olur ve komisyon döngüsü kurar
        # (ölçüm: BTC 1g'de 33 yerine 171 işlem!).
        if reset_signal:
            self.last_signal = None

        self._emit("trade",
                   f"{p.side} kapandı @ {_px(price)} · net {net:+,.2f} "
                   f"(brüt {gross:+,.2f}, komisyon {p.fee_open + fee_close:,.4f})"
                   f" · {reason}")

    # ------------------------------------------------------------------
    def _emit(self, kind: str, message: str) -> None:
        if self._quiet:
            return                     # backtest sirasında log basılmaz
        logger.info("%s", message)
        if self._on_event:
            try:
                self._on_event(kind, message)
            except Exception:      # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    def state(self, price: float) -> dict[str, Any]:
        """Arayuze gonderilecek anlik goruntu."""
        with self._lock:
            return self._state(price)

    def _state(self, price: float) -> dict[str, Any]:
        eq = self.equity(price)
        p = self.position
        return {
            "type": "wallet",
            "symbol": self.symbol,
            "running": self.running,
            "balance": round(self.balance, 4),
            "equity": round(eq, 4),
            "start_balance": round(self.start_balance, 4),
            "profit": round(eq - self.start_balance, 4),
            "leverage": self.leverage,
            "wallet_fraction": self.wallet_fraction,
            "fee_rate": self.fee_rate,
            "lookback": self.lookback,
            "confirm": self.confirm,
            "short_rule": self.short_rule,
            "mode": self.mode,
            "min_hold_bars": self.min_hold_bars,
            "trend_risk_pct": self.trend_risk_pct,
            "muro_risk_pct": self.muro_risk_pct,
            "ppt_risk_pct": self.mode_ppt_risk_pct,
            "muro_lock_pct": self.muro_cfg.lock_pct,
            "trend_lock_pct": self.trend_lock_pct,
            "ppt_lock_pct": self.trend_lock_pct,
            "trend_pull_atr": self.trend_pull_atr,
            "ppt_pull_atr": self.mode_ppt_pull_atr,
            "flip_cooldown_sec": self.flip_cooldown_ms / 1000.0,
            "lock_cooldown_sec": self.lock_cooldown_ms / 1000.0,
            "no_entry_left_sec": round(self._bekleme_kaldi_ms([]) / 1000.0, 1),
            "last_signal": self.last_signal,
            "long_peak": round(self.long_peak, 8),
            "backtest": self.backtest_stats,
            "last_long_price": self.last_long_price,
            "unrealized": round(self.unrealized(price), 4),
            "margin_used": round(p.margin, 4) if p else 0.0,
            "position": None if p is None else {
                "side": p.side,
                "entry": round(p.entry, 8),
                "qty": round(p.qty, 8),
                "margin": round(p.margin, 4),
                "notional": round(p.notional, 4),
                "liq_price": round(p.liq_price, 8),
                "stop_price": round(p.stop_price, 8),
                "eff_leverage": round(p.eff_leverage, 4),
                "target": round(p.target, 8),
                "window_low": round(p.window_low, 8),
                "window_high": round(p.window_high, 8),
                "unrealized": round(self.unrealized(price), 4),
                "opened_at": p.opened_at,
                "reason": p.reason,
            },
            "totals": {
                "trades": len(self.trades),
                "wins": self.wins,
                "losses": self.losses,
                "gross_pnl": round(self.gross_pnl, 4),
                "commission": round(self.commission_paid, 4),
            },
            # SADECE CANLI islemler. Gecmis test sonuclarini ayirmak icin:
            # kullanici "Trade Basla" dediginde yalnizca o andan sonraki
            # hareketler sayilir.
            "live": self._live_stats(),
            "trades": [self._trade_row(t) for t in self.trades[-25:]][::-1],
        }

    def _live_stats(self) -> dict[str, Any]:
        """Yalnizca mode == "live" olan islemlerin ozeti."""
        canli = [t for t in self.trades if t.mode == "live"]
        kazanc = sum(1 for t in canli if t.net_pnl >= 0)
        brut = sum(t.gross_pnl for t in canli)
        komisyon = sum(t.fee_open + t.fee_close for t in canli)
        return {
            "trades": len(canli),
            "wins": kazanc,
            "losses": len(canli) - kazanc,
            "gross_pnl": round(brut, 4),
            "commission": round(komisyon, 4),
            "net_pnl": round(brut - komisyon, 4),
            "started_at": self._live_started_at,
        }

    @staticmethod
    def _trade_row(t: Trade) -> dict[str, Any]:
        from datetime import datetime
        return {
            "side": t.side,
            "entry": round(t.entry, 8),
            "exit": round(t.exit, 8),
            "qty": t.qty,
            "pnl": round(t.net_pnl, 4),
            "pnl_pct": round(t.net_pnl / t.margin * 100, 2) if t.margin else 0.0,
            "commission": round(t.fee_open + t.fee_close, 6),
            "time": datetime.fromtimestamp(t.closed_at).strftime("%H:%M:%S"),
            "tf": t.timeframe,
            "reason": t.exit_reason,
            "mode": t.mode,
        }
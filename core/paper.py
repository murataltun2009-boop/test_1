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
                  min_hold: Optional[int] = None) -> None:
        with self._lock:
            self._configure(balance, leverage, fee_rate, wallet_fraction,
                            lookback, confirm, short_rule, mode, min_hold)

    def _configure(self, balance: Optional[float] = None,
                   leverage: Optional[float] = None,
                   fee_rate: Optional[float] = None,
                   wallet_fraction: Optional[float] = None,
                   lookback: Optional[int] = None,
                   confirm: Optional[bool] = None,
                   short_rule: Optional[str] = None,
                   mode: Optional[str] = None,
                   min_hold: Optional[int] = None) -> None:
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
        if mode in ("range", "signal", "signal_long", "signal_exit"):
            self.mode = mode
        if min_hold is not None and 0 <= int(min_hold) <= 500:
            self.min_hold_bars = int(min_hold)

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
        p = self.position
        if p is None:
            return 0.0
        raw = (price - p.entry) * p.qty if p.side == LONG \
            else (p.entry - price) * p.qty
        return raw - p.fee_open      # acilis komisyonu hemen gider

    def equity(self, price: float) -> float:
        return self.balance + self.unrealized(price)

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
                   signal: Optional[str] = None) -> Optional[str]:
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
            return self._on_price(price, candles, timeframe, signal)

    def _on_price(self, price: float, candles: list,
                  timeframe: str,
                  signal: Optional[str] = None) -> Optional[str]:
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
        if candles:
            t_bar = candles[-1].open_time
            if t_bar != self._last_bar_time:
                self._last_bar_time = t_bar
                self._bars_held += 1

        # 1) likidasyon kontrolu
        p = self.position
        if p is not None:
            if (p.side == LONG and price <= p.liq_price) or \
               (p.side == SHORT and price >= p.liq_price):
                self._close(price, "LİKİDASYON (kaldıraç kaybı)", timeframe)
                return "Likidasyon"
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

            # 3) SİNYAL TERS YÖN: pozisyon kapatılır ve tersi açılır.
            #    SAT geldiyse LONG kapanır + SHORT açılır.
            #    (Bu kontrol POZISYON ACIKKEN yapilir; aksi halde sinyal
            #     bloguna hic ulasilamaz ve hicbir sinyal islenmez.)
            if self.mode in ("signal", "signal_long", "signal_exit") and signal:
                if signal == self.last_signal:
                    return None
                self.last_signal = signal
                dusus = signal in ("SAT", "GÜÇLÜ SAT")
                yukselis = signal in ("AL", "GÜÇLÜ AL")

                # GIRIS aralık kuralindan, CIKIS sinyalden:
                # acik LONG, SAT sinyalinde kapanir (asili zararda kalmasin).
                if self.mode == "signal_exit":
                    if p.side == LONG and dusus:
                        self._close(price, f"{signal} sinyali", timeframe)
                        return f"LONG kapandı — {signal} sinyali (nötrde beklendi)"
                    return None

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
            return None

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
        # ------------------------------------------------------------------
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
                for i in range(start, n):
                    window = candles[i - start + 1:i + 1]
                    sig = signals[i] if signals and i < len(signals) else None
                    self._on_price(candles[i].close, window, timeframe, sig)
            finally:
                self._quiet = False

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
             candles_for_target: Optional[list] = None) -> None:
        margin = self.equity(price) * self.wallet_fraction
        notional = margin * self.leverage
        qty = notional / price if price > 0 else 0.0
        if qty <= 0 or margin <= 0:
            return
        fee_open = notional * self.fee_rate
        self.balance -= fee_open
        self.commission_paid += fee_open

        # likidasyon fiyati: teminatin tamamen bitigi seviye
        liq = price * (1.0 - 1.0 / self.leverage) if side == LONG \
            else price * (1.0 + 1.0 / self.leverage)

        # Hedef = giris anindaki pencerenin zirvesi (LONG) / dibi (SHORT).
        # Dondurulur: pencere kaydikca degismez.
        w = self._window(candles_for_target) if candles_for_target else []
        if w:
            win_low = min(c.low for c in w)
            win_high = max(c.high for c in w)
        else:
            win_low = win_high = price
        target = win_high if side == LONG else win_low
        # Hedef giris fiyatinin yaninda kalmiyorsa kullanma (anlamsiz).
        if side == LONG and target <= price:
            target = price
        if side == SHORT and target >= price:
            target = price

        self.position = Position(
            side=side, entry=price, qty=qty, margin=margin, notional=notional,
            fee_open=fee_open, liq_price=liq, opened_at=time.time(),
            timeframe=timeframe, reason=reason,
            target=target, window_low=win_low, window_high=win_high,
        )
        self._bars_held = 0        # yeni pozisyon: bekleme sayaci sifirlanir
        if side == LONG:
            self.last_long_price = price
            # Zirve referansi buradan yeniden baslar: LONG'dan sonraki
            # yukselisin tepe noktasi, SHORT'un referansidir.
            if self.long_peak <= price:
                self.long_peak = price

        self._emit("trade",
                   f"{side} açıldı @ {price:,.4f} · "
                   f"{self.leverage:g}x · teminat {margin:,.2f} · "
                   f"komisyon {fee_open:,.4f} · hedef {target:,.4f} · "
                   f"{reason}")

    def _close(self, price: float, reason: str, timeframe: str) -> None:
        p = self.position
        if p is None:
            return
        notional_close = p.qty * price
        fee_close = notional_close * self.fee_rate
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
        self._emit("trade",
                   f"{p.side} kapandı @ {price:,.4f} · net {net:+,.2f} "
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
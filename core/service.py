"""
Canli veri servisi - butun is mantiginin bulundugu katman.

Sorumluluklar:
  * Her zaman dilimi icin mum tamponu tutmak (WebSocket + REST)
  * Arka planda indikatorleri hesaplamak ve bilesik skoru cikarmak
  * Sinyal gecislerini tespit etmek, log'a yazmak ve veritabanina kaydetmek
  * Arayuze anlik veri akisi saglamak (kuyruk uzerinden)

Tum ag ve hesaplama isleri arka plan thread'lerinde yapilir; arayuz
kuyruktan okur, hicbir zaman bloklanmaz.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime
from typing import Any, Optional

import config
from core.analysis import Signal, TimeframeAnalysis, analyze, format_number
from core.binance_client import BinanceFuturesClient, Candle, Trade
from core.paper import _kapali_mumlar

logger = logging.getLogger("ta.service")

# MURO/karar etiketlerini grafik Signal'ine cevirir. MURO "kapama"
# aksiyonlarinda yildiz TERS yonde olmalidir (long kapat = sat, short
# kapat = al); aksi halde grafik yanlis gecerli aksiyon gosterir.
_LABEL_TO_SIGNAL = {
    "GÜÇLÜ AL": Signal.STRONG_BUY,
    "AL": Signal.BUY,
    "NÖTR": Signal.NEUTRAL,
    "SAT": Signal.SELL,
    "GÜÇLÜ SAT": Signal.STRONG_SELL,
    "": Signal.NEUTRAL,
    "LONG_KAPAT": Signal.SELL,
    "SHORT_KAPAT": Signal.BUY,
}


def _score_signal_series(score, base: float, strong: float) -> list[Signal]:
    """Skor dizisini (-1..1) esiklerle Signal serisine cevirir."""
    out: list[Signal] = []
    for s in score:
        v = float(s)
        if v != v:                      # NaN -> NÖTR
            out.append(Signal.NEUTRAL)
        elif v >= strong:
            out.append(Signal.STRONG_BUY)
        elif v >= base:
            out.append(Signal.BUY)
        elif v <= -strong:
            out.append(Signal.STRONG_SELL)
        elif v <= -base:
            out.append(Signal.SELL)
        else:
            out.append(Signal.NEUTRAL)
    return out

# Ayni yon icin ardisik kayitlar arasindaki en kisa sure (sn).
# Sinyal NÖTR <-> AL arasinda zipliyorsa log/kayit şişmesini engeller.
COOLDOWN_SECONDS = 60

# Analiz yeniden hesaplama en sik bu kadar aralikla (sn). analyze() ~55 ms
# surer; 3 dilim icin ~165 ms. Daha sik calistirmak CPU'yu yiyip hicbir
# fayda saglamaz (mum saniyede birkac kez degisir).
RECOMPUTE_INTERVAL = config.ANALYSIS_INTERVAL

# Tamponda tutulacak azami mum sayisi
MAX_BUFFER = config.CANDLE_LIMIT + 60


class MarketService:
    """Arka planda calisan veri + analiz servisi."""

    def __init__(self, settings: config.Settings, store, paper=None):
        self.settings = settings
        self.store = store
        self.paper = paper          # kaldirac simulasyonu (istege bagli)
        self.client = BinanceFuturesClient(settings.symbol)

        self._lock = threading.Lock()
        self._buffers: dict[str, list[Candle]] = {}
        self._analyses: dict[str, TimeframeAnalysis] = {}
        self._last_signal: dict[str, Signal] = {}
        self._last_record_time: dict[str, float] = {}
        self._dirty: set[str] = set()
        self._live_price: float = float("nan")
        # Bozuk akis verisine karsi son gecerli islem fiyati (sabit referans).
        self._last_good_price: float = 0.0
        self._time_offset_ms: int = 0
        self._status: str = "duruyor"
        self._started: bool = False
        # Kullaniciya gosterilen dilim. Analiz dongusu bunu her turda
        # hesaplar, digerlerini seyrek (bkz. _analysis_loop).
        self._focus: Optional[str] = settings.active_timeframe
        # Her analiz yeniden hesaplandiginda artan surum. Arayuz sadece
        # surumu degisen paneli yeniler; boylece gereksiz cizim olmaz.
        self._versions: dict[str, int] = {}
        # MURO: islenen son aksiyonun bar indeksi (ayni aksiyonun
        # tekrar tekrar uygulanmasini onler).
        self._muro_action_idx: int = -1
        self._muro_mode: Optional[str] = None
        self._pushed_versions: dict[str, int] = {}
        # Mod bazlı grafik yıldızı serisi cache'i: (cache_key, Signal listesi)
        self._mode_series_cache: dict[str, tuple] = {}

        self.events: queue.Queue = queue.Queue()
        # Anlik fiyat tikleri (her islem). Web arayuzu bunu dogrudan
        # tarayiciya yayar; masaustu arayuzu kullanmaz.
        self.ticks: queue.Queue = queue.Queue(maxsize=4000)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._started

    def request_full_refresh(self) -> None:
        """Anlik goruntu (snapshot) gonderilmesini zorlar."""
        with self._lock:
            self._dirty.update(self._buffers.keys())
        self._push_snapshot()

    def force_mode_refresh(self) -> None:
        """
        Mod degisiminde grafik yildizlarini hemen yeniler.

        _mode_series_cache temizlenir; ws push deduplasyonu
        (sent == version) onceki surumu gordugunden her dilimin
        surumu 1 artirilir, sonra snapshot zorla gonderilir.
        """
        self._mode_series_cache.clear()
        with self._lock:
            for tf in list(self._versions):
                self._versions[tf] = self._versions.get(tf, 0) + 1
            self._dirty.update(self._buffers.keys())
        self._push_snapshot()

    # ------------------------------------------------------------------
    # Dış API
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()

        self._emit_status("info", "Binance Futures'a baglaniliyor...")
        try:
            self._time_offset_ms = self.client.server_time_offset_ms()
        except Exception:      # noqa: BLE001
            self._time_offset_ms = 0

        # 1) Gecmis veriyi REST ile cek
        try:
            for tf in self.settings.timeframes:
                candles = self.client.fetch_klines(tf, config.CANDLE_LIMIT)
                self._buffers[tf] = candles
                self._dirty.add(tf)
                self._emit_status("info",
                                  f"{tf} mum gecmisi cekildi ({len(candles)} bar).")
        except Exception as exc:      # noqa: BLE001
            self._emit_log("error", "sistem",
                           f"Mum gecmisi alinamadi: {exc}")
            self._started = False
            return

        # 2) Analiz iscisi
        t = threading.Thread(target=self._analysis_loop, name="analiz", daemon=True)
        t.start()
        self._threads.append(t)

        # 3) WebSocket dinleyici
        t = threading.Thread(
            target=self._ws_loop, name="websocket", daemon=True)
        t.start()
        self._threads.append(t)

        # 4) Periyodik REST mutabakat + fiyat
        t = threading.Thread(target=self._maintenance_loop, name="bakim", daemon=True)
        t.start()
        self._threads.append(t)

        self._emit_status("ok", "Canli akis basladi.")

    def stop(self) -> None:
        self._stop.set()
        self._status = "duruyor"
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=2.0)
        self._threads.clear()
        self._started = False
        self._emit_status("info", "Servis durduruldu.")

    def update_timeframes(self, timeframes: list[str]) -> None:
        """Arayuzden zaman dilimi degisimi."""
        with self._lock:
            to_fetch = [tf for tf in timeframes if tf not in self._buffers]
            to_drop = [tf for tf in self._buffers if tf not in timeframes]
            for tf in to_drop:
                self._buffers.pop(tf, None)
                self._analyses.pop(tf, None)
                self._last_signal.pop(tf, None)
                self._last_record_time.pop(tf, None)

        for tf in to_fetch:
            try:
                candles = self.client.fetch_klines(tf, config.CANDLE_LIMIT)
                with self._lock:
                    self._buffers[tf] = candles
                    self._dirty.add(tf)
                self._emit_log("info", tf, f"Yeni zaman dilimi yuklendi ({len(candles)} bar).")
            except Exception as exc:      # noqa: BLE001
                self._emit_log("error", tf, f"Zaman dilimi yuklenemedi: {exc}")

    def set_focus(self, tf: str) -> bool:
        """
        Kullaniciya gosterilecek (odak) zaman dilimini degistirir.

        True donerse dilim hemen yeniden hesaplanir; boylece dilim
        degistiginde ekranda anlik dogru veri olur.
        """
        if tf not in self.settings.timeframes:
            return False
        with self._lock:
            if self._focus == tf:
                return True
            self._focus = tf
            self.settings.active_timeframe = tf
            self._dirty.add(tf)
        self._emit_log("info", tf,
                       f"Zaman dilimi değiştirildi → {config.TF_LABELS.get(tf, tf)}")
        return True

    def update_thresholds(self, strong: float, base: float) -> None:
        with self._lock:
            self.settings.strong_threshold = strong
            self.settings.base_threshold = base
            self._dirty.update(self._buffers.keys())
        self._emit_log("info", "ayar",
                       f"Eşikler guncellendi: GÜÇLÜ ±{strong:.2f}, AL/SAT ±{base:.2f}")

    def set_record_neutral(self, enabled: bool) -> None:
        self.settings.record_neutral = bool(enabled)
        self._emit_log("info", "ayar",
                       f"NÖTR gecisleri kaydetme: {'acik' if enabled else 'kapali'}")

    def set_analysis_interval(self, seconds: float) -> None:
        """Gosterge hesabinin araligini degistirir (canlilik ayari)."""
        global RECOMPUTE_INTERVAL
        RECOMPUTE_INTERVAL = max(0.2, float(seconds))
        self._emit_log("info", "ayar",
                       f"Analiz araligi {RECOMPUTE_INTERVAL:.1f} sn olarak ayarlandi.")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "analyses": dict(self._analyses),
                "versions": dict(self._versions),
                "price": self._live_price,
                "status": self._status,
                "timeframes": list(self.settings.timeframes),
                "focus": self._focus,
            }

    # ------------------------------------------------------------------
    # Dahili: Islem (trade) akisindan olusan mum
    # ------------------------------------------------------------------
    def _ws_loop(self) -> None:
        """
        Trade akisindan son mumu gercek zamanli kurar.

        Kline akisi bu ortamda sessiz oldugu icin (bkz.
        binance_client.stream_trades) mum burada islemlerden yeniden
        uretiliyor. Her islem icin:
          * ayni barin icindeysek  -> kapanis/yuksek/dusuk/hacim guncelle
          * yeni bar basladiysa   -> yeni mum ekle

        DIKKAT: bu islem TUM zaman dilimleri icin yapilir. Tek bir islem
        15m / 1h / 4h kovalarinin hepsine birden ait; her biri kendi
        tf_msine gore yuvarlanip guncellenir. Yildizlar yalnizca secili
        dilimin tikleri tarayiciya gonderilir (bkz. web/server.py Hub).
        """
        # (dilim, tf_ms) listesi - start() sirasinda hazir olur
        pairs: list[tuple[str, int]] = []
        for tf in self.settings.timeframes:
            secs = config.TF_SECONDS.get(tf)
            if secs:
                pairs.append((tf, secs * 1000))

        # COIN DEGISTIGINDE ESKI AKISIN DEVAMI (SORUN 1)
        #
        # WS thread'i recv() icinde uzun sure bloklanabilir; stop() 2 sn
        # bekleyip vazgeciyor ve eski thread yeni coinin mumlarina da
        # yazmaya devam ediyor. Sonuc: (a) yeni coinin mumlari bozuluyor,
        # (b) "Bozuk islem atlandi" logu sürekli tekrarlaniyor.
        #
        # COZUM: akis kendi sembolunu etiketler; sembol degistiyse
        # o akisin islemleri sessizce dusurulur.
        akis_symbol = self.settings.symbol
        client = self.client

        # Akistan gelen bozuk islem filtresi.
        #
        # OLCUM (45 sn, her iki sembol): Binance @trade akisi arada fiyati
        # 0,00 / miktari 0,00 olan islemler gonderiyor (3'er adet). Once
        # sadece price<=0 filtreliyorduk; ama ayni aileden daha ince
        # bozuklar da geliyor (or. fiyat 13,11 — kullanici gordu). Bunlar
        # mumun kapanisini yazdiginda:
        #   * Y ekseni ve tum gostergeler (RSI/MA/MACD) bozuluyor,
        #   * "fiyat pencerenin tabaninda" testi anlık tetikleniyor,
        #   * log'a "fiyat 13,11" gibi imkansiz satirlar yaziliyor.
        #
        # Bu yuzden her islem son bilinen saglam fiyata karsi kontrol
        # edilir; makul olmayanlar reddedilir ve log'a dusurulur.
        #
        # IKINCI KATMAN (coin degisimi): Sapma buyukse islem reddedilmek
        # yerine once REST referansina (yeni coinin son kapanisi) bakilir.
        # Cunku coin degisiminden sonra ESKI coinin akisindan gelen
        # islemler referansi bozuyor ve YENI coinin butun islemleri
        # "bozuk" sayilip reddediliyordu (log sürekli tekrarlaniyordu).
        son_bozuk_log = [0.0]

        def _rest_referans() -> float:
            """Yeni coinin REST'ten gelen son kapanis fiyati (0 = yok)."""
            with self._lock:
                for tf in self.settings.timeframes:
                    buf = self._buffers.get(tf)
                    if buf:
                        return float(buf[-1].close)
            return 0.0

        def _trade_is_sane(price: float) -> bool:
            if price <= 0 or price != price:
                return False
            ref = self._last_good_price
            if ref > 0:
                sapma = abs(price - ref) / ref
                if sapma > config.TRADE_PRICE_SANITY:
                    # Coin degismis olabilir: REST referansina bak.
                    rest_ref = _rest_referans()
                    if rest_ref > 0 and \
                            abs(price - rest_ref) / rest_ref <= \
                            config.TRADE_PRICE_SANITY:
                        # Yeni coinin gercek fiyati -> referansi yenile,
                        # log'a BOSUK YAZMA.
                        self._last_good_price = price
                        return True
                    # Gercekten bozuk veri. Logu HIZLANDIR (spam olmasin).
                    now = time.time()
                    if now - son_bozuk_log[0] > 30.0:
                        son_bozuk_log[0] = now
                        self._emit_log(
                            "warning", "sistem",
                            f"Bozuk işlem atlandı: fiyat {price:,.4f} "
                            f"(son geçerli {ref:,.4f}, sapma %{sapma*100:.1f})")
                    return False
            self._last_good_price = price
            return True

        def on_trade(trade: Trade) -> None:
            # Eski coinin akisindan gelen islemler: sessizce dusurulur.
            if akis_symbol != self.settings.symbol:
                return
            if trade.qty < 0:
                return              # bozuk islem verisi, yoksay
            if not _trade_is_sane(trade.price):
                return
            with self._lock:
                for tf, tf_ms in pairs:
                    buf = self._buffers.get(tf)
                    if buf is None:
                        continue

                    # Islemin ait oldugu barin acilis ani
                    bucket = (trade.time_ms // tf_ms) * tf_ms

                    if buf and bucket < buf[-1].open_time:
                        # Gecikmis islem: son bardan eskisine ait, yoksay
                        continue

                    if buf and bucket == buf[-1].open_time:
                        c = buf[-1]
                        c.close = trade.price
                        if trade.price > c.high:
                            c.high = trade.price
                        if trade.price < c.low:
                            c.low = trade.price
                        c.volume += trade.qty
                        c.closed = False
                    else:
                        buf.append(Candle(
                            open_time=bucket,
                            open=trade.price,
                            high=trade.price,
                            low=trade.price,
                            close=trade.price,
                            volume=trade.qty,
                            close_time=bucket + tf_ms - 1,
                            closed=False,
                        ))
                        if len(buf) > MAX_BUFFER:
                            buf.pop(0)

                    self._dirty.add(tf)
                    _publish_tick(tf, bucket, buf[-1])

                self._live_price = trade.price

        def on_status(level: str, message: str) -> None:
            self._status = message
            self._emit_status(level, message)

        def _publish_tick(tf: str, bucket: int, candle: Candle) -> None:
            """
            Son barin guncel halini tik kuyruguna koy.

            tf alani zorunludur: tarayiciya uc dilimin tikleri de gider,
            istemci yalnizca secili olana bakar.
            """
            try:
                self.ticks.put_nowait({
                    "type": "tick",
                    "tf": tf,
                    "price": candle.close,
                    "t": bucket // 1000,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                })
            except queue.Full:
                pass

        try:
            client.stream_trades(
                on_trade=on_trade,
                on_status=on_status,
                stop_event=self._stop,
            )
        except Exception as exc:      # noqa: BLE001
            self._emit_log("error", "sistem", f"WebSocket dongusu coktu: {exc}")

    # ------------------------------------------------------------------
    # Dahili: Analiz dongusu
    # ------------------------------------------------------------------
    def _analysis_loop(self) -> None:
        """
        Gostergeleri periyodik olarak yeniden hesaplar.

        analyze() 500 bar icin ~55 ms surer. Uc dilimi de RECOMPUTE_INTERVAL
        (0,5 sn) ile hesaplamak surekli ~165 ms is -> tek cekirdegin
        ucde birini yiyor, kullaniciya hicbir fayda saglamiyor. Bu yuzden
        odaktaki (kullaniciya gosterilen) dilim her turda, digerleri
        BACKGROUND_REFRESH_FACTOR kat daha seyrek hesaplanir.
        """
        last_focus = 0.0
        last_bg = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                dirty = set(self._dirty)
                self._dirty.clear()
                focus = self._focus

            focus_dirty = {tf for tf in dirty if tf == focus}
            bg_dirty = dirty - focus_dirty

            targets: set[str] = set()
            if focus_dirty and (now - last_focus) >= RECOMPUTE_INTERVAL:
                targets |= focus_dirty
                last_focus = now
            bg_limit = RECOMPUTE_INTERVAL * config.BACKGROUND_REFRESH_FACTOR
            if bg_dirty and (now - last_bg) >= bg_limit:
                targets |= bg_dirty
                last_bg = now

            if targets:
                for tf in sorted(targets):
                    self._process(tf)
                # Yalnizca veri gercekten degistiginde anlik goruntu gonder
                self._push_snapshot()

            self._stop.wait(RECOMPUTE_INTERVAL)

    # ------------------------------------------------------------------
    def _process(self, tf: str) -> None:
        with self._lock:
            buf = self._buffers.get(tf)
            if not buf:
                return
            candles = list(buf)

        if len(candles) < 60:
            return

        try:
            res = analyze(
                symbol=self.settings.symbol,
                timeframe=tf,
                open_times=[c.open_time for c in candles],
                o=[c.open for c in candles],
                h=[c.high for c in candles],
                l=[c.low for c in candles],
                c=[c.close for c in candles],
                v=[c.volume for c in candles],
                close_times=[c.close_time for c in candles],
                strong_threshold=self.settings.strong_threshold,
                base_threshold=self.settings.base_threshold,
            )
        except Exception as exc:      # noqa: BLE001
            self._emit_log("error", tf, f"Analiz hatasi: {exc}")
            return

        with self._lock:
            self._analyses[tf] = res
            self._versions[tf] = self._versions.get(tf, 0) + 1
            previous = self._last_signal.get(tf)
            self._last_signal[tf] = res.signal

        # Kaldirac simulasyonu: YALNIZCA odaktaki dilim icin, anlik fiyatla.
        # (Arka plandaki dilimler karar vermez; kullanici onlari gormuyor.)
        if self.paper is not None and tf == self._focus:
            self._run_paper(candles, tf, res)

        # Baslangic durumu kaydedilmez, sadece bilgi olarak loglanir
        if previous is None:
            self._emit_log(
                "info", tf,
                f"Başlangıç durumu: {res.signal.value} "
                f"(skor {res.composite_value:+.3f}, "
                f"fiyat {format_number(res.price, digits=None)})",
            )
            return

        if previous is res.signal:
            return

        self._handle_signal_change(tf, res, previous)

    # ------------------------------------------------------------------
    def paper_candles(self, tf: Optional[str] = None) -> list[Candle]:
        """
        Simulasyonun kullanacagi mum kopyasi.

        DIKKAT: kopyalanir. PaperTrader pencereyi dondurup hedef hesapliyor;
        paylasilan (copya olmayan) listede mum guncellenince gecmise
        donuk hesaplar bozulur.
        """
        with self._lock:
            key = tf or self._focus
            buf = self._buffers.get(key)
            return list(buf) if buf else []

    # ------------------------------------------------------------------
    def paper_signals(self, tf: Optional[str] = None) -> list[str]:
        """
        Odak dilimin bar basina sinyal dizisi (backtest icin).

        analyze() TEK cagriyla tum gecmis icin sinyal uretiyor
        (TimeframeAnalysis.signals). Bu dizi nedenseldir: signals[i]
        yalnizca i'ye kadar olan mumlara bakar — 150/150 kirpma testiyle
        dogrulandi. Boylece geriye donuk testte sinyal modu da
        gercekci sekilde oynatilabiliyor.
        """
        with self._lock:
            key = tf or self._focus
            buf = self._buffers.get(key)
            res = self._analyses.get(key)
            if not buf or res is None:
                return []
            if len(res.signals) != len(buf):
                # Uzunluklar tutmadiysa (yeni bar eklendiyse) yeniden hesapla
                return []
            return [s.value for s in res.signals]

    # ------------------------------------------------------------------
    def _run_paper(self, candles: list[Candle], tf: str,
                     res: Optional[TimeframeAnalysis] = None) -> None:
        """
        Simulasyon motorunu anlik fiyatla besler.

        Analiz 0,5 sn'de bir calistigindan fiyat orada bayat olabilir.
        Karar, mum sayisi ve anlik fiyat ile verilir. Sinyal modunda
        ayrica gosterge analizinin karari da gecirilir.
        """
        with self._lock:
            price = self._live_price
        if price != price or price <= 0:      # NaN veya gecersiz
            price = candles[-1].close
        signal = self._signal_for_mode(res, candles)
        try:
            self.paper.on_price(price, candles, tf, signal)
        except Exception as exc:      # noqa: BLE001
            self._emit_log("error", "simulator", f"Simülatör hatası: {exc}")

    # ------------------------------------------------------------------
    def _muro_action(self, res: "TimeframeAnalysis",
                     candles: Optional[list] = None) -> str:
        """
        MURO aksiyonu (AL / SAT / LONG_KAPAT / SHORT_KAPAT).

        ONEMLI 1: aksiyon serisi bar bazlidir ve ayni son bar icin her
        analiz dongusunde TEKRAR hesaplanir. Canli akista ayni eski
        aksiyonun tekrar tekrar uygulanmamasi icin "islenen bar"
        numarasi tutulur: sadece YENI bir aksiyon varsa dondurulur.

        ONEMLI 2: Sinyal YALNIZCA KAPANMIS barlardan uretilir. Olusan
        (kapanmamis) bar icinde Supertrend yonu tik tik degisiyor ve
        simulator saniyede bir kez LONG/SHORT degistiriyordu.
        """
        from core import muro as muro_mod
        if self.paper is None:
            return ""
        # Mod degistiyse aksiyon sayaci sifirlanir (yeni modun ilk
        # aksiyonu uygulanabilsin).
        if self._muro_mode != self.paper.mode:
            self._muro_mode = self.paper.mode
            self._muro_action_idx = -1
        cs = _kapali_mumlar(candles or [])
        if len(cs) < 30:
            return ""
        acts = muro_mod.actions([c.open for c in cs],
                                [c.high for c in cs],
                                [c.low for c in cs],
                                [c.close for c in cs],
                                self.paper.muro_cfg)
        idx = -1
        for i in range(len(acts) - 1, -1, -1):
            if acts[i]:
                idx = i
                break
        if idx < 0:
            return ""
        if idx <= self._muro_action_idx:
            return ""                    # yeni aksiyon yok
        self._muro_action_idx = idx
        return acts[idx]

    # ------------------------------------------------------------------
    def _signal_for_mode(self, res: "TimeframeAnalysis | None",
                         candles: Optional[list] = None) -> str | None:
        """
        Karar mekanizmasina göre SINYAL kaynagini secer.

        Varsayilan: bilesik skor (11 osilator + 15 MA birlikte).
        ma_only : SADECE 15 hareketli ortalamanin skoru
        osc_only: SADECE 11 osilatorun skoru
        trend   : Supertrend(10,3) yonu (yeni algoritma)

        ONEMLI: alt skorlar da -1..+1 olcegindedir (ortalama alindiği
        icin), bu yuzden AYNI esikler (GÜÇLÜ / AL-SAT) kullanilabilir.
        Bilesik skor 0,50*osilator + 0,50*MA oldugu icik bilesik deger
        ile alt degerler farkli olabilir; yanlislikla bilesik kullanilirsa
        kural "sadece MA" olmaktan cikar.
        """
        if res is None:
            return None

        mode = self.paper.mode if self.paper is not None else "range"
        if mode == "trend":
            # Supertrend: +1 -> AL, -1 -> SAT, 0 -> NOTR.
            #
            # Sinyal YALNIZCA KAPANMIS barlardan: olusan bar icinde
            # Supertrend yonu tik tik degisiyor ve simulator her sinyal
            # degisiminde pozisyon degistiriyordu (HYPE logu: saniyede
            # bir LONG/SHORT, kazanc komisyona gidiyordu).
            from core import trend as trend_mod
            cs = _kapali_mumlar(candles or [])
            if len(cs) < 30:
                return None
            # Guclu sinyal dizisi: KAPANMIS son barin bilesik skoru.
            # (res.signals her bar icin nedensel sinyal tutar.)
            strong = None
            if res is not None and getattr(res, "signals", None):
                sigs = list(res.signals)
                if len(sigs) > len(cs):
                    sigs = sigs[:len(cs)]
                strong = trend_mod.strong_series(sigs)
            karar = trend_mod.decide_series(
                [c.high for c in cs], [c.low for c in cs],
                [c.close for c in cs], strong=strong,
                period=self.paper.trend_period if self.paper else 10,
                mult=self.paper.trend_mult if self.paper else 3.0,
                pull_atr=(self.paper.trend_pull_atr if self.paper else 0.0),
                pull_bars=(self.paper.trend_pull_bars if self.paper else 20))
            return karar[-1] if karar else None
        if mode == "1m":
            # 1m modu: MTF trend follow + pullback entry + profit lock
            # Sinyal: 15m Supertrend trend + 5m confirmation + 1m EMA20 pullback
            # Filtreler: ADX>20, Vol z-score > -1.5, ATR percentile 10-90%, session 00-06 UTC
            from core import trend as trend_mod
            cs = _kapali_mumlar(candles or [])
            if len(cs) < 30:
                return None
            strong = None
            if res is not None and getattr(res, "signals", None):
                sigs = list(res.signals)
                if len(sigs) > len(cs):
                    sigs = sigs[:len(cs)]
                strong = trend_mod.strong_series(sigs)
            karar = trend_mod.decide_series(
                [c.high for c in cs], [c.low for c in cs],
                [c.close for c in cs], strong=strong,
                period=self.paper.mode_1m_trend_period if self.paper else 10,
                mult=self.paper.mode_1m_trend_mult if self.paper else 3.0,
                pull_atr=(self.paper.mode_1m_pullback_atr if self.paper else 1.0),
                pull_bars=(self.paper.mode_1m_pullback_ema if self.paper else 20))
            return karar[-1] if karar else None
        if mode == "ppt":
            # PPT modu: PP-Supertrend yonu (5 dk periyodu icin yeni
            # karar mekanizmasi). Sinyal YALNIZCA KAPANMIS barlardan —
            # trend modundaki nedensellik kuralinin aynisi.
            from core import ppst as ppst_mod
            from core import trend as trend_mod
            cs = _kapali_mumlar(candles or [])
            if len(cs) < 30:
                return None
            strong = None
            if res is not None and getattr(res, "signals", None):
                sigs = list(res.signals)
                if len(sigs) > len(cs):
                    sigs = sigs[:len(cs)]
                strong = trend_mod.strong_series(sigs)
            karar = ppst_mod.decide_series(
                [c.high for c in cs], [c.low for c in cs],
                [c.close for c in cs], strong=strong,
                period=(self.paper.mode_ppt_period if self.paper else 10),
                mult=(self.paper.mode_ppt_mult if self.paper else 3.0),
                pull_atr=(self.paper.mode_ppt_pull_atr if self.paper else 0.0),
                pull_bars=(self.paper.mode_ppt_pull_bars if self.paper else 20))
            return karar[-1] if karar else None
        if mode == "muro":
            return self._muro_action(res, candles)
        if mode not in ("ma_only", "osc_only"):
            return res.signal.value

        score = (res.ma_scores[-1] if mode == "ma_only"
                 else res.oscillator_scores[-1])

        # ESIKLER MODE GORE DEGISIR — OLCULE GEREKCEYLE (bkz. config.py)
        #   MA  : bilesik esikler (0,40 / 0,65). 15 MA'nin ortalamasi
        #         oldugu icin yeterince hareket ediyor.
        #   OSC : daha kucuk esikler (0,25 / 0,40). 11 osilatorun
        #         ortalamasi oldugu icin bilesik esikler neredeyse hic
        #         asilmaz; olcum: 4h/280 barda 33 sinyal.
        if mode == "osc_only":
            base = config.PAPER_OSC_BASE_THRESHOLD
            strong = config.PAPER_OSC_STRONG_THRESHOLD
        else:
            base = self.settings.base_threshold
            strong = self.settings.strong_threshold

        if score >= strong:
            return "GÜÇLÜ AL"
        if score >= base:
            return "AL"
        if score <= -strong:
            return "GÜÇLÜ SAT"
        if score <= -base:
            return "SAT"
        return "NÖTR"

    # ------------------------------------------------------------------
    def mode_signal_series(self, tf: str) -> list[Signal]:
        """
        Grafik yildizlarina temel olacak MOD BAZLI sinyal serisi.

        Grafik yildizlari daha once her zaman bilesik skordan geliyordu;
        artik secilen algoritmaya gore uretilir:
          signal/range : bilesik skor (res.signals, ayni)
          ma_only      : sadece MA skoru esiklenir
          osc_only     : sadece osilator skoru esiklenir
          trend        : Supertrend karar serisi (decide_series)
          1m           : 1m modu karar serisi (ayni decide_series)
          ppt          : PP-Supertrend karar serisi (core/ppst.py)
          muro         : muro.actions serisi (kapama ters yonde yildiz)

        Seri analizin AKTIF versiyonu icin cache'lenir; her tik
        yeniden hesaplanmaz.
        """
        mode = self.paper.mode if self.paper is not None else "range"
        with self._lock:
            res = self._analyses.get(tf)
            version = self._versions.get(tf, 0)
        if res is None:
            return []

        key = self._mode_cache_key(mode, version)
        cached = self._mode_series_cache.get(tf)
        if cached is not None and cached[0] == key:
            return cached[1]

        if mode in ("trend", "1m", "muro", "ppt"):
            with self._lock:
                buf = list(self._buffers.get(tf) or [])
            series = self._decision_series_for_mode(mode, res, buf)
        elif mode == "ma_only":
            series = _score_signal_series(
                res.ma_scores,
                self.settings.base_threshold,
                self.settings.strong_threshold)
        elif mode == "osc_only":
            series = _score_signal_series(
                res.oscillator_scores,
                config.PAPER_OSC_BASE_THRESHOLD,
                config.PAPER_OSC_STRONG_THRESHOLD)
        else:
            series = list(res.signals)

        n = len(res.signals)
        if n and len(series) != n:
            # Hizalama bozuksa cevreleyen emniyet: bilesik seri göster.
            series = list(res.signals)

        self._mode_series_cache[tf] = (key, series)
        return series

    def _mode_cache_key(self, mode: str, version: int) -> tuple:
        """Seri cache anahtari: analiz versiyonu + mod + ilgili parametreler."""
        parts: list = [version, mode,
                       round(self.settings.base_threshold, 4),
                       round(self.settings.strong_threshold, 4)]
        p = self.paper
        if p is not None:
            if mode == "trend":
                parts += [p.trend_period, p.trend_mult,
                          p.trend_pull_atr, p.trend_pull_bars]
            elif mode == "1m":
                parts += [p.mode_1m_trend_period, p.mode_1m_trend_mult,
                          p.mode_1m_pullback_atr, p.mode_1m_pullback_ema]
            elif mode == "ppt":
                parts += [p.mode_ppt_period, p.mode_ppt_mult,
                          p.mode_ppt_pull_atr, p.mode_ppt_pull_bars]
        return tuple(parts)

    def _decision_series_for_mode(self, mode: str, res: TimeframeAnalysis,
                                  candles: list) -> list[Signal]:
        """trend/1m/muro/ppt modlari icin bar bazli karar serisi."""
        from core import muro as muro_mod
        from core import trend as trend_mod
        cs = _kapali_mumlar(candles)
        if len(cs) < 30 or self.paper is None:
            return list(res.signals)
        gap = len(res.signals) - len(cs)

        if mode == "muro":
            acts = muro_mod.actions(
                [c.open for c in cs], [c.high for c in cs],
                [c.low for c in cs], [c.close for c in cs],
                self.paper.muro_cfg)
            base = [_LABEL_TO_SIGNAL.get(a, Signal.NEUTRAL) for a in acts]
        else:
            # Guclu sinyal dizisi: KAPANMIS son barin bilesik skoru.
            strong = None
            if getattr(res, "signals", None):
                sigs = list(res.signals)
                if len(sigs) > len(cs):
                    sigs = sigs[:len(cs)]
                strong = trend_mod.strong_series(sigs)
            if mode == "1m":
                period = self.paper.mode_1m_trend_period
                mult = self.paper.mode_1m_trend_mult
                pull_atr = self.paper.mode_1m_pullback_atr
                pull_bars = self.paper.mode_1m_pullback_ema
            elif mode == "ppt":
                from core import ppst as ppst_mod
                karar = ppst_mod.decide_series(
                    [c.high for c in cs], [c.low for c in cs],
                    [c.close for c in cs], strong=strong,
                    period=self.paper.mode_ppt_period,
                    mult=self.paper.mode_ppt_mult,
                    pull_atr=self.paper.mode_ppt_pull_atr,
                    pull_bars=self.paper.mode_ppt_pull_bars)
                base = [_LABEL_TO_SIGNAL.get(k, Signal.NEUTRAL) for k in karar]
                if gap > 0 and base:
                    base = base + [base[-1]] * gap
                return base
            else:
                period = self.paper.trend_period
                mult = self.paper.trend_mult
                pull_atr = self.paper.trend_pull_atr
                pull_bars = self.paper.trend_pull_bars
            karar = trend_mod.decide_series(
                [c.high for c in cs], [c.low for c in cs],
                [c.close for c in cs], strong=strong,
                period=period, mult=mult,
                pull_atr=pull_atr, pull_bars=pull_bars)
            base = [_LABEL_TO_SIGNAL.get(k, Signal.NEUTRAL) for k in karar]

        if gap > 0 and base:
            # Olusan (kapanmamis) son bar: son KAPANMIS karar gecerli
            # (_signal_for_mode ile ayni semantik).
            base = base + [base[-1]] * gap
        return base

    # ------------------------------------------------------------------
    def switch_symbol(self, symbol: str) -> tuple[bool, str]:
        """
        Coin degistirir: istemci dogrulanir, servis sifirdan kurulur.

        Donus: (basarili, mesaj)
        """
        symbol = symbol.upper().strip()
        if symbol == self.settings.symbol:
            return False, f"{symbol} zaten seçili."

        # 1) Gecerli mi? (Binance'te var mi, futures'te mi?)
        try:
            probe = BinanceFuturesClient(symbol)
            probe.fetch_klines(self.settings.timeframes[0], 3)
        except Exception as exc:      # noqa: BLE001
            return False, f"{symbol} kullanılamıyor: {exc}"

        # 2) Sembol değişti: eski tamponlar ve analizler anlamsız.
        self.stop()
        self.settings.symbol = symbol
        self.client = BinanceFuturesClient(symbol)
        # Yeni coinin fiyati eskisinden tamamen farkli; bozuk-veri filtresi
        # referansini sifirlamazsak butun ilk islemleri reddederdi.
        self._last_good_price = 0.0
        # Anlik fiyat da sifirlanmali. Aksi halde ilk analiz turunde
        # ESKI coinin fiyatiyle calisiyor ve yeni coinin mumlari
        # o fiyatla etiketleniyordu (log'da "fiyat 0.00" gorunmesinin
        # nedeni buydu: 0,0038 fiyatli bir coinde onceki 0.00 kaliyordu).
        self._live_price = float("nan")
        with self._lock:
            self._buffers.clear()
            self._analyses.clear()
            self._versions.clear()
            self._pushed_versions.clear()
            self._last_signal.clear()
            self._last_record_time.clear()
            self._dirty.clear()
            self._mode_series_cache.clear()
        if self.paper is not None:
            self.paper.reset(symbol)

        self.start()
        if not self._started:
            return False, f"{symbol} yüklenemedi."
        return True, symbol

    # ------------------------------------------------------------------
    def _handle_signal_change(self, tf: str, res: TimeframeAnalysis,
                              previous: Signal) -> None:
        sig = res.signal
        osc_counts, ma_counts = self._counts(res)

        # Log ekrani: HER gecis burada, tarih/saat ile
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._emit_log_signal(tf, stamp, sig, previous, res)

        # Veritabani: varsayilan olarak yalnizca aksiyon alinabilir durumlar
        if sig is Signal.NEUTRAL and not self.settings.record_neutral:
            return

        now = time.time()
        if now - self._last_record_time.get(tf, 0.0) < COOLDOWN_SECONDS:
            return
        self._last_record_time[tf] = now

        details = [
            {
                "bolum": "Osilatörler" if i < res.osc_split else "Hareketli Ortalamalar",
                "ad": row.label,
                "deger": row.value_text,
                "islem": row.verdict.label,
            }
            for i, row in enumerate(res.rows)
        ]

        try:
            self.store.record_signal(
                symbol=res.symbol,
                timeframe=tf,
                candle_open_time=res.open_time,
                signal=sig.value,
                previous_signal=previous.value,
                composite=res.composite_value,
                price=res.price,
                osc_score=float(res.oscillator_scores[-1]),
                ma_score=float(res.ma_scores[-1]),
                osc_counts=osc_counts,
                ma_counts=ma_counts,
                details=details,
            )
        except Exception as exc:      # noqa: BLE001
            self._emit_log("error", tf, f"Veritabanina yazilamadi: {exc}")

    # ------------------------------------------------------------------
    @staticmethod
    def _counts(res: TimeframeAnalysis) -> tuple[dict, dict]:
        def tally(rows) -> dict:
            out = {1: 0, 0: 0, -1: 0}
            for r in rows:
                out[r.verdict.value] += 1
            return out

        return tally(res.oscillator_rows), tally(res.ma_rows)

    # ------------------------------------------------------------------
    # Dahili: Bakim dongusu (REST mutabakat + fiyat)
    # ------------------------------------------------------------------
    def _maintenance_loop(self) -> None:
        while not self._stop.is_set():
            try:
                try:
                    price = self.client.fetch_price()
                    with self._lock:
                        self._live_price = price
                except Exception:      # noqa: BLE001
                    pass

                if time.monotonic() - getattr(self, "_last_resync", 0.0) >= config.RESYNC_SECONDS:
                    self._last_resync = time.monotonic()
                    for tf in list(self.settings.timeframes):
                        try:
                            candles = self.client.fetch_klines(tf, config.CANDLE_LIMIT)
                        except Exception:      # noqa: BLE001
                            continue
                        with self._lock:
                            self._buffers[tf] = candles
                            self._dirty.add(tf)
            except Exception as exc:      # noqa: BLE001
                self._emit_log("error", "sistem", f"Bakim dongusu hatasi: {exc}")

            self._stop.wait(10.0)

    # ------------------------------------------------------------------
    def _push_snapshot(self) -> None:
        snap = self.snapshot()
        if not snap["analyses"]:
            return
        # Kuyruk sismesin: eski anlik goruntuler atilir, yalnizca en son
        # gecerli tutulur (arayuz geride kalmayi istemiyoruz).
        while self.events.qsize() > 40:
            try:
                self.events.get_nowait()
            except Exception:      # noqa: BLE001
                break
        self.events.put(("snapshot", snap))

    # ------------------------------------------------------------------
    def _emit_status(self, level: str, message: str) -> None:
        """
        Durum mesaji. DIKKAT: burada _emit_log CAGRILMAZ.

        Onceki surumde hem "status" hem "log" olayi kuyruga konuyordu;
        iki dinleyici de ayni satiri log'a yaziyor ve log ekraninda her
        mesaj IKI KEZ gorunuyordu. Tek olay yeterli: arayuz hem durum
        cubugunu hem log satirini buradan turetebilir.
        """
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.events.put(("status", level, message))
        try:
            self.store.log(level, "sistem", message)
        except Exception:      # noqa: BLE001
            pass
        logger.info("%s %s", stamp, message)

    def _emit_log(self, level: str, category: str, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.events.put(("log", stamp, level, category, message))
        try:
            self.store.log(level, category, message)
        except Exception:      # noqa: BLE001
            pass
        logger.info("%s [%s] %s", stamp, category, message)

    def _emit_log_signal(self, tf: str, stamp: str, sig: Signal,
                         previous: Signal, res: TimeframeAnalysis) -> None:
        text = (f"[{tf}] {previous.value} → {sig.value}  |  "
                f"skor {res.composite_value:+.3f}  |  fiyat "
                f"{format_number(res.price, digits=None)}")
        self.events.put(("signal_log", stamp, sig, tf, text))
        try:
            self.store.log("signal", tf, text)
        except Exception:      # noqa: BLE001
            pass
        logger.info("%s %s", stamp, text)
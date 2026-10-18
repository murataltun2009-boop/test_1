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
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "signals.db")
LOG_FILE = os.path.join(LOG_DIR, "sinyal.log")

# --------------------------------------------------------------------------
# Binance Futures
# --------------------------------------------------------------------------
# NOT: kullanicinin istegi dogrultusunda SPOT degil FUTURES (fapi) kullanilir.
FAPI_REST = "https://fapi.binance.com"
FAPI_WS = "wss://fstream.binance.com/stream?streams="

SYMBOL = "BTCUSDT"

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
TIMEFRAMES: list[str] = ["15m", "1h", "4h"]

# Odak disi dilimler bu kadar daha seyrek yeniden hesaplanir. analyze()
# 500 bar icin ~55 ms surer; uc dilimi de 0,5 sn'de bir calistirmak
# surekli CPU tuketirdi. Kullaniciya gosterilen dilim her RECOMPUTE_INTERVAL
# guncellenir, digerleri 4 kat seyrek.
BACKGROUND_REFRESH_FACTOR = 4

TF_LABELS: dict[str, str] = {
    "1d": "1 Gün",
    "15m": "15 Dakika",
    "1h": "1 Saat",
    "2h": "2 Saat",
    "4h": "4 Saat",
}

# Arayuzde tek birim olarak gosterilen saniye cinsinden sureler.
TF_SECONDS: dict[str, int] = {
    "1d": 86400,
    "15m": 900,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
}

CANDLE_LIMIT = 500       # cekilen mum sayisi
VISIBLE_CANDLES = 150    # "Sigdir" gorunumunde gosterilen mum sayisi

# --------------------------------------------------------------------------
# Sinyal esikleri
# --------------------------------------------------------------------------
# Bilesik skor araligi -1.0 .. +1.0
STRONG_THRESHOLD = 0.65   # |skor| >= bu deger  -> GUC LU AL / GUC LU SAT
BASE_THRESHOLD = 0.40     # |skor| >= bu deger  -> AL / SAT
                          # arasi               -> NOTR

# Osilatörler %50, Hareketli Ortalamalar %50
OSCILLATOR_WEIGHT = 0.50
MA_WEIGHT = 0.50

# Hareketli ortalama karsilastirmasinda "notr" bolgesi (göreceli).
# Fiyat MA'nin %0.02'si icindeyse Nötr sayilir; aksi halde Al/Sat.
MA_DEADZONE = 0.0002

# --------------------------------------------------------------------------
# Zamanlama
#
# DIKKAT: bu degerler OLCUM sonucuyla secilmistir. Bu makinede:
#   matplotlib Agg cizimi  : ~135 ms / 145.000 piksel (~0,9 us/piksel)
#   matplotlib Tk blit'i  : ~11 ms   (piksel sayisiyla degismez)
#   analyze() (500 bar)   : ~55 ms
#
# Cizim maliyeti GORUNUM ALANIYLA ORANTILI. Buyuk bir grafik (ornegin
# 900x460 = 414.000 piksel) ~370 ms surer. Bu yuzden yenileme araligi sabit
# degil, son cizimin GERCEK suresiyle uyarlanir:
#
#   aralik = max(alt_sinir_ms, son_cizim_ms * headroom)
#
# Boylece zayif makinede grafik yavaslar (arayuz donmaz), guclu makinede
# saniyede birkac kez yeniler. Kullanici ayrica ust cubuktan "Yenileme" ile
# headroom katsayisini secebilir.
# --------------------------------------------------------------------------
WS_RECONNECT_SECONDS = 5      # websocket kopunca yeniden baglanma araligi
RESYNC_SECONDS = 60           # REST ile mumlari mutabakat etme periyodu

# Bozuk akis verisi filtresi.
#
# OLCUM: Binance @trade akisi arada fiyati 0,00 (ve daha ince bozuklar)
# olan islemler gonderiyor. Bunlar mumun kapanisini yazdiginda tum
# gostergeler bozuluyor ve log'a "fiyat 13,11" gibi imkansiz satirlar
# yaziliyor. Bu esik, son gecerli islem fiyatindan sapmasi %25'ten
# buyuk olan islemleri reddeder. (Gun icinde fiyat %25'ten fazla
# ziplamaz; 4h bar icinde bu ihtimal dildigi icin guvenli.)
TRADE_PRICE_SANITY = 0.25

GUI_TICK_MS = 100             # etkinlik kuyrugu + ucuz etiketler (10 Hz)

# Yenileme modlari: etiket -> (headroom katsayisi, alt sinir ms, analiz sn)
REFRESH_MODES: dict[str, tuple[float, int, float]] = {
    "Canlı (hızlı)": (1.6, 350, 0.5),
    "Normal":        (2.6, 700, 1.0),
    "Ekonomik":      (5.0, 2000, 2.5),
}
DEFAULT_REFRESH_MODE = "Canlı (hızlı)"

ANALYSIS_INTERVAL = REFRESH_MODES[DEFAULT_REFRESH_MODE][2]
CHART_HEADROOM = REFRESH_MODES[DEFAULT_REFRESH_MODE][0]
CHART_MIN_INTERVAL_MS = REFRESH_MODES[DEFAULT_REFRESH_MODE][1]

# Log paneli kucuk tutulur ki grafik yer kazansin.
LOG_HEIGHT = 4                # gorunen satir sayisi
LOG_MAX_LINES = 2000          # log ekraninda tutulan azami satir

# Ag uzerinden sunucu saati farki (ms), Binance hizli ise
MAX_TIME_DRIFT_MS = 5000      # bu esigi asarsa uyari verilir


# --------------------------------------------------------------------------
# Sembol secimi — 36 coin, HACIM OLÇUMUYLE secildi
#
# Liste tahminle degil, Binance Futures'un canli verisiyle olusturuldu.
#   python tools/update_symbols.py --write
#
# OLCUTLER (hepsi olculebilir):
#   1. USDT perpetual + durum TRADING
#   2. 24 saatlik islem hacmi >= 45.000.000 USD   (likidite -> kayma yok)
#   3. Listelenme yasi >= 6 ay                    (4h x 500 bar = ~83 gun)
#   4. 30 günlük medyan |günlük değişim| <= %6
#   5. 30 günlük en büyük günlük değişim <= %35
#   6. Kaldıraçlı token'ler ve stabil para çiftleri hariç
#
# 4 ve 5 NEDEN VAR: karar mekanizmasi ARALIKTAN yararlanıyor ("fiyat
# pencerenin tabanında" / "zirve"). 30 günde bir %50 zıplayan coin'de
# aralık oluşmuyor; mumlar aralığı parçalıyor ve taban/zirve testi
# anlamsızlaşıyor. Tek günlük %3 zıplama sorun değil (BTC'de olur).
#
# OLCUM 2026-10-18: 522 USDT perpetual tarandi -> 47 aday -> 36 secildi.
# Elenenler: AGT, Q, QNT, ZEREBRO, GTC, SAND, STRK, ARIA, ICNT, APR, BR
#   (hepsi tek günde %36–114 zıpladı).
#
# NOT — 1000PEPEUSDT: Binance PEPE'yi fiyatının 1000 katıyla bu
# sözleşme adıyla fiyatlıyor; ayrı bir varlık değil.
#
# Sembol degisince servis yeniden kurulur (mum gecmisi ~1 sn/dilim),
# tamponlar temizlenir, simulator sifirlanir.
# --------------------------------------------------------------------------
SYMBOLS: list[str] = [
    "BTCUSDT",
    "ETHUSDT",
    "ZECUSDT",
    "SOLUSDT",
    "NEARUSDT",
    "XRPUSDT",
    "HYPEUSDT",
    "DOGEUSDT",
    "BNBUSDT",
    "WLDUSDT",
    "AVAUSDT",
    "SUIUSDT",
    "PUMPUSDT",
    "TIAUSDT",
    "ENAUSDT",
    "1000PEPEUSDT",
    "FILUSDT",
    "UNIUSDT",
    "ERAUSDT",
    "ADAUSDT",
    "HBARUSDT",
    "XMRUSDT",
    "AVAXUSDT",
    "INJUSDT",
    "TAOUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "ARBUSDT",
    "TRUMPUSDT",
    "BCHUSDT",
    "AAVEUSDT",
    "FETUSDT",
    "ONDOUSDT",
    "APTUSDT",
    "ZROUSDT",
    "DOTUSDT",
]

# --------------------------------------------------------------------------
# Kaldirac simulasyonu
# --------------------------------------------------------------------------
PAPER_INITIAL_BALANCE = 1000.0   # sanal cuzdan baslangic bakiyesi (USDT)
PAPER_LEVERAGE = 10.0            # kaldirac carpani (1..125)
PAPER_WALLET_FRACTION = 0.80     # cuzdanin bu kadari pozisyona kullanilir
PAPER_FEE_RATE = 0.0005          # Binance Futures taker komisyonu (%0,05)
PAPER_LOOKBACK = 20              # "en taban / zirve" penceresi (bar)

# "Fiyat pencerenin en tabaninda" nasil olculur?
# Dogrudan esitlik degil, PENCERE ICINDEKI KONU:
#     konum = (fiyat - enDusuk) / (enYuksek - enDusuk)      0..1
# 0'a yakin = grafikteki en taban noktasi (LONG noktasi)
# 1'e yakin = dusus egiliminin basladigi zirve (SHORT noktasi)
# Mum kapandiginda kapanis fiyati en dusukten ayrilmis oldugu icin
# birebir esitlik kontrolu HIC BIR ZAMAN dogru olmazdi.
PAPER_BOTTOM_POS = 0.12          # %12 alti = "en taban"
PAPER_TOP_POS = 0.88             # %88 ustu = "zirve / dusus basligi"

# Donus teyidi (LONG icin yesil mum, SHORT icin kirmizi mum).
# Varsayilan KAPALI. Olcum (BTC, 500 bar):
#     konum tek basina            bar basina %9-19  -> 15m'de ~2 saatte bir
#     + yesil/kirmizi mum teyidi  bar basina %1,5-4,7 -> 4h'de ~70 saatte bir
# Ikincisi canli izlenemeyecek kadar seyrek. Ayrica "dibi yapan mum" zaten
# dusus yonunde kapanmistir; yesil mum beklemek dogru donus noktasini gecer.
PAPER_CONFIRM = False

# SHORT kurali: iki secenek
#   "entry"    : fiyat son LONG'un GIRIS fiyatinin altinda olmali.
#                Bu, kullaniciya onaylanmis ORIJINAL davranistir ve
#                simulatorun varsayilanidir (4h / 500 mum / +%120).
#   "pullback" : fiyat son LONG'un zirvesinden geri cekilmis olmali.
#                DENEYSEL: SHORT'a izin verir ama 4h orneginde
#                +%120 -> +%64'e dusurdugu icin varsayilan degildir.
PAPER_SHORT_RULE = "entry"
PAPER_PULLBACK = 0.005           # zirveden en az %0,5 geri cekilme

# Karar mekanizmasi
#   "range"  : LONG pencerenin tabaninda, SHORT son LONG'un altinda.
#              Bu, kullaniciya onaylanmis ORIJINAL davranistir ve
#              simulatorun varsayilanidir.
#   "signal"      : gosterge analizinin sinyali karar verir (AL<->SHORT).
#   "signal_long" : SADECE LONG. AL sinyaliyle girilir, SAT sinyaliyle
#                   kapanir, arada beklenir; hicbir zaman SHORT acilmaz.
#   "ma_only"     : SADECE 15 hareketli ortalamanin skoru karar verir.
#   "osc_only"    : SADECE 11 osilatorun skoru karar verir.
#                   Bu ikisinde NÖTR "bekle" DEGIL, TERS YÖN sinyalidir:
#                   acik LONG'yi kapatip SHORT acar, acik SHORT'u kapatip
#                   LONG acar. Art arda ayni yon gelirse islem yapilmaz.
PAPER_MODE = "range"

# ---- Tek kaynak modlarinin esikleri --------------------------------
#
# OLCUM (tools/pick_osc_threshold.py, 15 coin x 3 dilim, 280 bar):
#
#   Esik            4h AL     4h SAT   islem   ort.bar
#   0,40 / 0,65        15        18       66      43,4   <- bilesik esik
#   0,30 / 0,45        70        91      320      12,5
#   0,25 / 0,40       222       283      920       4,5   <- SECILDI
#   0,15 / 0,25       917      1023     2089       2,0   <- asiri gurultulu
#
# NEDEN AYRI ESIK?
#   osilator skoru = 11 osilatorun ORTALAMASI. Tek bir osilatorun en
#   buyuk katkisi 1/11 = 0,091. Bilesik skor icin kullanilan 0,40 esigi
#   bu yuzden neredeyse hic asilmaz (4h/280 barda yalniz 33 sinyal).
#
# MA skoru ise 15 MA'nin ortalamasi oldugu icin ayni esiklerle
# yeterince hareket ediyor (olcum: 4h/280 barda 9.604 AL/SAT bar).
# O yuzden MA modunda bilesik esikler kullanilir, osilator modunda
# daha kucuk esikler.
#
# 0,15/0,25 secilmedi: 4h'te bar basina 2 islem -> her pozisyon 2
# barda kapanir; cift tarafli komisyon kari tamamen yer.
PAPER_OSC_BASE_THRESHOLD = 0.25    # AL/SAT esigi (osc_only)
PAPER_OSC_STRONG_THRESHOLD = 0.40  # GÜÇLÜ AL/SAT esigi (osc_only)

# Geriye donuk testte varsayilan esikler (arayuzden degistirilebilir).
PAPER_BASE_THRESHOLD = BASE_THRESHOLD
PAPER_STRONG_THRESHOLD = STRONG_THRESHOLD

# Sinyal modunda minimum tutma suresi (bar).
PAPER_MIN_HOLD_BARS = 0          # 0 = kisit yok


@dataclass
class Settings:
    """Arayuzden degistirilebilen ayarlar."""

    symbol: str = SYMBOL
    timeframes: list[str] = field(default_factory=lambda: list(TIMEFRAMES))
    active_timeframe: str = ACTIVE_TIMEFRAME
    strong_threshold: float = STRONG_THRESHOLD
    base_threshold: float = BASE_THRESHOLD
    record_neutral: bool = False   # NOTR gecislerini de kaydet (varsayilan hayir)
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
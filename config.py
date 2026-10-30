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
TIMEFRAMES: list[str] = ["1m", "5m", "15m", "1h", "4h", "1d"]

# Odak disi dilimler bu kadar daha seyrek yeniden hesaplanir. analyze()
# 500 bar icin ~55 ms surer; uc dilimi de 0,5 sn'de bir calistirmak
# surekli CPU tuketirdi. Kullaniciya gosterilen dilim her RECOMPUTE_INTERVAL
# guncellenir, digerleri 4 kat seyrek.
BACKGROUND_REFRESH_FACTOR = 4

TF_LABELS: dict[str, str] = {
    "1m": "1 Dakika",
    "5m": "5 Dakika",
    "1d": "1 Gün",
    "15m": "15 Dakika",
    "1h": "1 Saat",
    "2h": "2 Saat",
    "4h": "4 Saat",
}

# Arayuzde tek birim olarak gosterilen saniye cinsinden sureler.
TF_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
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
# LIMIT-dolumlu cikislarda maker ucreti (resting emir gercekcigi).
PAPER_MAKER_RATE = 0.0002        # Binance Futures maker (%0,02)
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
#   "trend"       : Supertrend(10, 3) + ATR stop (4x) / takip stopu (6x).
#                   YENI ALGORITMA — asagidaki olcume dayanir.
#                   NÖTR: pozisyon kapatilir, ters yon ACILMAZ.
#
# Bu modlarda NÖTR "bekle" demektir: acik pozisyon kapatilir, ters
# yone gecilmez (kullanici kurali).
PAPER_MODE = "range"

# ---- Trend (Supertrend) modu ---------------------------------------
#
# OLCUM — neden bu parametreler?
# ---------------------------------
# 25 coin (10 secim + 15 holdout), Binance Futures, komisyon %0,05,
# kayma %0,02, funding %0,01/8h, risk bazli boyutlandirma.
# Ayrintili tablo: ALGORITMA_ARASTIRMASI.md
#
#   SUPERTREND(10,3) · stop 4xATR · trail 6xATR
#   kume       medyan/fold   kazanan hücre   PF
#   secim          +%5,0           %62        1,29
#   holdout        +%5,3           %65        1,54
#
# Ayni ayar uygulamanin 500 mumluk penceresinde:
#   secim (10 buyuk coin)  +%6,6 medyan · %90 pozitif · PF 1,94
#   holdout (14 coin)      +%1,9 medyan · %57 pozitif · PF 1,18
#
# NOT: "10x/20x kaldirac" bu stratejide UST SINIRDIR. Risk bazli
# boyutlandirma kullanilir: pozisyon, stop mesafesi x risk kadarlik
# kayip verecek sekilde acilir. Gercekte kullanilan kaldirac ~0,1-0,6x
# cikar. 10x'i gercekten kullanmak islem basina %100+ risk demektir ve
# testlerde hesap sifirlanir (bkz. rapor).
PAPER_TREND_PERIOD = 10
PAPER_TREND_MULT = 3.0
PAPER_TREND_STOP_ATR = 4.0       # giris stopu = 4 x ATR
PAPER_TREND_TRAIL_ATR = 6.0      # takip stopu = 6 x ATR (kapanista)
PAPER_TREND_RISK_PCT = 0.05      # islem basina sermayenin %5'i
PAPER_TREND_MAX_LEV = 20.0       # kaldıraç ust siniri (arayuz degeri ile min)
# Trend modunda kar kilitleme: fiyat %2 ilerleyince pozisyon kapanir,
# kar cuzdana yazilir, 1-2 dk beklenir ve pozisyon TEKRAR DEGERLENDIRILIR.
# (Kullanıcı kuralı: TÜM algoritmalarda +%2 kâr bankası — önceden %3 idi.)
PAPER_TREND_LOCK_PCT = 0.02      # kar bankasi (fiyat +%2)
PAPER_LOCK_COOLDOWN_SEC = 90     # kilit sonrasi bekleme (1,5 dk)

# RECLAIM sarti: stop (veya basabas/likidasyon) sonrasi ayni yone girmek
# icin stop seviyesinin "geri alinmasi" beklenir. Sart BIRIM BARDIR:
# 12 bar sonra sart duser (5m'de 1 saat, 4h'de 2 gun). Olcum: hic
# dusmeyen kalici blok "2 stop sonrasi hic pozisyon acmiyor" sikayetinin
# kok sebebiydi (PPT 5m canli raporu).
PAPER_RECLAIM_TTL_BARS = 12
# Sessiz engeller (reclaim bekliyor / pull filtresi bekliyor) bu aralikta
# bir kez olay akisina yazilir (spam olmasin).
PAPER_STATE_LOG_SEC = 300

# ---- AUTO FIB RETRACEMENT (trend + muro, hibrit donus yakalama) --------
# core/fib.py: son salinim (yuzde tabanli degil, swing tabanli) hesaplanir.
# * ALTIN CEBE (0.5-0.618) gelinince yon uyumlu ise GUCLU sinyal uretilir
#   (optimum nokta filtresini atlar) -> "donus yerini yakala".
# * SALINIM UCUNA cok yakin (FIB_GATE payindan az mesafe) devam girisi
#   engellenir (tepe alma/dip satma).
#
# Olcum (tools/research_fib.py, BTC/ETH/SOL 5m x1500 + BTC 1h x1500):
#   TREND fib acik  : toplam -427$ vs kapali -402$ -> NET OLUMSUZ (1h
#                     +0.52% -> -1.59%). Trend filtresi KAPALI default.
#   MURO  fib acik  : toplam -27$ vs kapali -56$  -> NET POZITIF (1h
#                     -4.15% -> -1.57%). MURO'da fibonacci ACIK.
PAPER_FIB_ON = False
PAPER_MURO_FIB_ON = True
# Skor tabanli modlar (sadece MA / sadece osilator / sinyal) icin fib:
# OLCUM (tools/research_fib2.py, BTC/ETH/SOL 5m + BTC 1h; toplam net):
#   ma_only     -1314$ -> -794$  (+520$) -> ACIK
#   osc_only     -607$ -> -557$  ( +50$) -> ACIK
#   signal       -863$ -> -526$  (+337$) -> ACIK
#   signal_long  -337$ -> -151$  (+186$) -> ACIK (1h +1.3% -> +4.3%)
PAPER_FIB_SCORE_ON = True
# Aralik (pencere tabani) motoru icin fib "altin cebede LONG/SHORT":
# OLCUM: -160$ -> -671$ (-511$; giris sayisi 3-4 kat artiyor, komisyon
# yiyor). KAPALI default.
PAPER_FIB_RANGE_ON = False
PAPER_FIB_WINDOW = 160           # son N bar icinde salinim uclari taranir
PAPER_FIB_GATE = 0.15            # uca yakinlik esigi (0..0.5)

# ---- DUZELTICI (seri kilidi) ------------------------------------------------
# TESHIS (tools/research_teshis.py, 1799+628+1087+543 islem): zarar biten
# islemden SONRA gelen islemler ortalama -7.5$ (dort mod, dort pencere
# TUTARLI); temiz serideki islemler ortalama +1.6$. Yani kayip KUMALI:
# basabaş gap-acilisi sonrasi piyasa chop rejiminde ve sinyaller yeniden
# aliniyor. ILAC: zarar bitince K bar yeni GIRIS acilmaz (posisyon yoksa
# gate devrede; cikis/stop/banka her zaman serbest).
# ---- OLCUM SONUCU AKTIF (research_karar3.py, "GUC8REV") ------------
# K8 + ARM + sadece-GÜÇLÜ (giris) + GÜÇLÜ-once-yen-yaz kombinasyonu:
# 1000$ tabana gore skor modlarinda %91-95 zarar kesilmesi (sabit stake
# 4 pencere), BTC 1h ma_only pozitivesi (+54$ compounding). Diğer modlar
# (trend/muro/1m/ppt/range) de zarar görmüyor: -%65..%93 iyilesme.
PAPER_CORR_ON = True
PAPER_CORR_PAUSE_BARS = 8        # zarar sonrasi giris bekleme (BAR)
# Skor modlarinda genis basabaş tamponu: giris sonrasi fiyat %buf geri
# gelirse +buf mikrokâr (limit mantigi, bar isi dokunma ile). Dar tampon
# (%0.12) komisyon-trip zarar uretiyor, genis tampon doviz-kirpma
# hem kârlari hem zararlari buyutuyor (olcum: tools/research_be2.py).
PAPER_CORR_BE_BUF = 0.004        # 1h/15m skor modlari mikro-klip tamponu
# GERCEK DURECO: skor modlarinda buyuk tolerans stop (kaba stop).
# Mikro-klip pozisyonlari +2% banka yolunda kesiyordu; genis stop +
# banka kombinasyonu olcumle karar verilecek (research_stop.py).
PAPER_CORR_STOP_DOWN = 0.0       # olcume kadar kapali (0..1 arasi frac)
# Mikro-klip hangi TFlerde getiri uretir (bar araligi tamponu kapsar)?
# 1h bar araligi ~%0.5-1.5: tamponun icinde dolum adil; 5m ~%0.1:
# tampon bar araligini asip HAYALI dolum uretir -> 5m kapatildi.
PAPER_CORR_TFS = {"1h", "15m"}
# ARM: zarar yonune TERS sinyal gelmeden yeni giris acilmaz
# (azap-degirmeni engeli). Olcum: tools/research_karar.py ARM.
PAPER_CORR_ARM_ON = True        # azap-degirmeni engeli (ters sinyal gerek)
# Sadece GÜÇLÜ sinyaller giris acar (zayif AL/SAT -> NÖTR).
PAPER_CORR_STRONG_ONLY = True     # zayif AL/SAT giris acmaz (NÖTR olur)
PAPER_CORR_STRONG_FIRST = True   # zayif-yazimi ARM gate ONCESI uygula
# ---- TICK (super-hizli tamamen-limit scalper) --------------------------
# Mod "tk": fib altin-cebe (%44-67.8) pasif BUY/SELL LIMIT giris,
# resting TP limit (maker) + stop-market SL. Round-trip ~%0.04 maker.
# Olcum: tools/research_tk(2,3).py — uretim parametreleri configure()
# icinde SEMBOLE GORE atanir:
#   BTC  5m : tp %3 sl %5 theta<=0.678 -> 3/3 pencere pozitif (+150$)
#   SOL  1m : tp %3 sl %5 theta<=0.85  -> +123$ / 3 pencere
# ETH ve digerleri ayni tp/sl, theta 0.85 (ETH olcumu zayifti).
PAPER_TK_ON = False              # mode="tk" secilirken configure acar
PAPER_TK_TP = 0.003              # hedef %0.3 (olcum: BTC5m/SOL1m en iyi)
PAPER_TK_SL = 0.005              # stop %0.5 (genis: 1m mean-reversion)
PAPER_TK_WIN = 60                # fib salinim penceresi (BAR)
PAPER_TK_THETA_MAX = 0.85        # geri cekilme ust siniri (BTC 0.678)
PAPER_TK_THETA_MIN = 0.44        # gercekleme alt siniri (yogun modda 0.0)
PAPER_TK_VOL_MULT = 1.0          # talep onayi carpani (1.5 olcum: negatif)
PAPER_TK_FILL = 0.55             # altin cebe giris konumu (0.55 en iyi)
PAPER_TK_TREND = False           # SMA200 uyumu (olcumde etkisiz)
# ---- TIK duzeltici (canli cogor teshisi, research_tk8-10 olcumu) ------
PAPER_TK_AFTER_SEC = 60           # her ac/kapadan sonra bekleme (SNAKIYE — kullanici kurali)
PAPER_TK_SAR = True               # stop kaybinda pozisyonu TERS yonde ac (stop->ters; dususte short yakala)
PAPER_TK_SAR_MEAN = 10            # SAR trend filtresi: son N kapali bar kapanis ortalamasi
PAPER_TK_SAR_MINPCT = 0.004       # SAR girisi icin fiyat-ortalama mesafesi (%0.4; chop sinirda ret)
PAPER_TK_RIBBON = True            # grafik cizgi kesismesi (EMA20/EMA50): kirmizi>yesil LONG, yesil>kirmizi SHORT
PAPER_TK_RIBBON_FLIP = True       # trende ters pozisyonu aninda trend yonune cevir
PAPER_TK_RIBBON_MODE = "cross"    # cross: ilk kesisme | cross200: +EMA200 tarafi | stack: tam dizilim
PAPER_TK_CONFIRM_BARS = 2         # yildiz sabitlemesi: son K kapali bar ayni yon olmali (1=kapali)
PAPER_TK_BANK_PCT = 0.025         # acik pozisyon kari bakiyenin bu kadarini gecince cuzdana yaz (+25$ @1000)
PAPER_TK_PAUSE_BARS = 0          # stop-sonrasi K bar giris yok (yogun: 3)
PAPER_TK_BE = False              # yarim-kar klip (yogun hook acar)
PAPER_TK_BE_TRIG = 0.5           # TP mesafesinin bu kadarini gecince aktif
PAPER_TK_BE_LOCK = 0.0           # klip seviyesi = ucresiz BE (yogun: 0.5)
PAPER_TK_LEG_FLIP = False        # ayni-leg tekrar giris engeli
# 1) KÂR BANKASI: açık pozisyon KENDİ giriş fiyatına göre +%2 kârda
#    nakde çevrilir; kâr cüzdanda kalır, sonra sinyal yeniden
#    değerlendirilip en uygun yönde devam edilir.
#    (trend/muro kendi kilit bloklarıyla kullanır; diğer modların tek
#    kâr çıkışı budur. Arayüzdeki "kâr kilidi" değeri hepsini eşler.)
PAPER_BANK_PCT = 0.02            # evrensel kâr bankası (fiyat +%2)
# 2) BAŞABAŞ KORUMASI: pozisyon ZARARA GEÇEMEZ. Fiyat giriş fiyatına
#    geri dönüp bu pay kadar önce dokunursa pozisyon kapatılır.
#    Pay = gidiş-dönüş komisyon + kayma payı: o kadar kızgın çıkışta
#    bile net kâr ~0'ın üstünde kalır.
PAPER_BREAKEVEN_BUF = 0.0012     # giriş ± %0,12 (2 komisyon + kayma)
# Kâr kilidi sonrası davranış:
#   "protected" : aynı yönde HEMEN yeniden pozisyon açılır ve stop kârın
#                 yazıldığı seviyeye çekilir → bankalanan kâr geri
#                 verilemez.
#   "wait"      : 1-2 dk beklenir, sonra pozisyon yeniden değerlendirilir.
#                 (KULLANICI İSTEĞİ — varsayılan)
#
# ÖLÇÜM (25 coin, 1g, app backtest motoru, risk %5):
#   kilit %0  → seçim +%24,5 · holdout +%31,7 · 350 işlem   <-- EN İYİ
#   kilit %3  → seçim −%10,4 · holdout +%3,9  · 2.287 işlem
#   kilit %12 → seçim +%1,9  · holdout +%6,8  · 796 işlem
#
# Sebep: kilit trendi %3'lük parçalara böler; işlem sayısı 6-25 katına
# çıkar ve komisyon kârı götürür. Kullanıcı isteği olarak %3 varsayılan
# yapıldı; arayüzden 0 yazılınca kilitleme kapanır (ölçülen en iyi).
PAPER_TREND_LOCK_REENTRY = "wait"

# GIRIŞTE "OPTIMUM NOKTA" KURALI (trend modu)
#
# KULLANICI SORUNU: "long pozisyonunu açmasın hemen arkasından coin
# fiyatı düştüğü için zarar yapıyor" ve "short fiyatın en dibine
# gelmiş oluyor artık longa geçecek shortla girince zarar yapıyor".
#
# KURAL: long için fiyat son N barın ZIRVESINE çok yakınsa girilmez;
# short için DIP'e çok yakınsa girilmez. Ölçü: ATR cinsinden mesafe.
#   long  : (zirve - fiyat) >= pull_atr * ATR
#   short : (fiyat - dip)  >= pull_atr * ATR
# 0 = filtre kapalı.
#
# AYRICA: bilesik skorda GÜÇLÜ AL / GÜÇLÜ SAT varsa filtre Bypass edilir
# (güçlü sinyalde hemen girilir).
PAPER_TREND_PULL_ATR = 0.0
PAPER_TREND_PULL_BARS = 20

# ---- 1m Optimized (yeni mod) --------------------------------------------
#
# Multi-timeframe: 15m Supertrend trend + 5m confirmation + 1m EMA20 pullback
# Filters: ADX>20, Vol z-score > -1.5, ATR percentile 10-90%, Session 00-06 UTC
# Cooldown: 100 bars, Min hold: 30 bars
# Risk: 0.3%/trade, Max effective leverage 5x, Stop 3*ATR (min 0.15%), Trail 5*ATR
# Session filter: 00-06 UTC
# Bu mod 1 dakikalık grafikler için optimize edilmiştir.
PAPER_1M_TREND_PERIOD = 10
PAPER_1M_TREND_MULT = 3.0
PAPER_1M_PULLBACK_EMA = 20
PAPER_1M_PULLBACK_ATR = 1.0
PAPER_1M_COOLDOWN = 100
PAPER_1M_MIN_HOLD = 30
PAPER_1M_ADX_MIN = 20
PAPER_1M_VOL_Z_MIN = -1.5
PAPER_1M_ATR_PCT_MIN = 0.1
PAPER_1M_ATR_PCT_MAX = 0.9
PAPER_1M_STOP_ATR = 3.0
PAPER_1M_TRAIL_ATR = 5.0
PAPER_1M_MIN_STOP_PCT = 0.0015
PAPER_1M_MAX_STOP_PCT = 0.02
PAPER_1M_RISK_PCT = 0.003
PAPER_1M_MAX_LEV = 5.0
PAPER_1M_SESSION_FILTER = True

# --------------------------------------------------------------------------
# PPT: PIVOT POINT SUPERTREND MODU (kullanıcı isteği — 5 dk önerilir)
#
#   Karar: core/ppst.py → PP-Supertrend(period, mult) yönü
#   + optimum nokta filtresi (pull_atr, pull_bars) + GÜÇLÜ sinyal bypass.
#   Pozisyon yönetimi trend ailesiyle aynı: stop/trail ATR bazlı,
#   +%2 kâr kilidi ("wait": bekle → sinyali yeniden değerlendir → en
#   uygun yonde devam), başabaş koruması + stop sonrası reclaim.
# --------------------------------------------------------------------------
PAPER_PPT_PERIOD = 10             # PP-Supertrend pivot dönemi (bar)
# OLCUM (tools/research_ppt.py, BTC/ETH/SOL 5m x1500 + BTC 1h x1500):
# mult 3.5 + pull 1.0, tek olumlu bolge; pull kapaliyken (0.0) ayni
# pencerede sonuc -%2..-%9 -> optimum nokta filtresi sart.
# period 14/20 ve stop 2.0 komisyon gitgidi (islem sayisi firlar).
PAPER_PPT_MULT = 3.5              # bant genişliği (x ATR)
PAPER_PPT_PULL_ATR = 1.0          # optimum nokta filtresi (tepe 1 ATR mesafede bekle)
PAPER_PPT_PULL_BARS = 20          # dönen zirve/dip penceresi
PAPER_PPT_STOP_ATR = 3.0          # giriş stopu = 3 x ATR
PAPER_PPT_TRAIL_ATR = 5.0         # takip stopu = 5 x ATR
PAPER_PPT_MIN_STOP_PCT = 0.003    # gürültü kapısı (stop en az %0,3)
PAPER_PPT_MAX_STOP_PCT = 0.05     # risk kapısı (stop en fazla %5)
PAPER_PPT_RISK_PCT = 0.03         # işlem başına sermayenin %3'ü
PAPER_PPT_MAX_LEV = 10.0          # kaldıraç üst sınırı

# Pozisyon DEGISIMI (LONG <-> SHORT) sonrasi bekleme.
#
# KULLANICI SORUNU (HYPE/USDT logu): "long short veya short long
# gecislerinde defalarca islem yapiyor" — Supertrend yonu OLUSAN
# (kapanmamis) bar icinde tik tik degisiyordu; simulator her sinyal
# degisiminde pozisyon degistiriyor, komisyon kazanci yiyordu.
#
# Iki koruma birlikte calisir:
#   1) Sinyal yalnizca KAPANMIS barlardan hesaplanir (core/service.py)
#   2) Pozisyon kapandiktan sonra yeni pozisyon acilmaz (bu bekleme)
PAPER_FLIP_COOLDOWN_SEC = 300    # yon degisiminden sonra 5 dk bekle

# ---- MURO (yeni algoritma) -------------------------------------------
#
# Yapı + kâr kilitleme + geri çekilme girişi. Ayrıntı: ALGORITMA_ARASTIRMASI.md
#   * YÖN: Supertrend(10, 3) — günlük dilimde ölçüldü.
#   * GİRİŞ: yön uyumluyken fiyat EMA'ya geri çekilip geri alınır
#     ("long en dipten", "short en tepeden").
#   * KÂR KİLİDİ: fiyat %1 (ölçülen optimum) ilerleyince pozisyon
#     kapanır, kâr CÜZDANA yazılır ve AYNI YÖNDE yeniden pozisyon
#     açılır (stop aynı risk mesafesinde, kâr seviyesinin altında).
#   * STOP: yapısal (giriş sonrası dip/tepe), %1,5-%5 aralığında.
#   * Boyutlandırma: risk bazlı (varsayılan %2). Kaldıraç üst sınırdır.
#
# ÖLÇÜM (25 coin, 1g, komisyon+kayma+funding dahil, 4 zaman dilimi):
#   risk %2 : seçim +%47,6 (PF 1,52) · holdout +%118,6 (PF 2,18)
#             500 bar: seçim +%14,5 · holdout +%4,7
#   NOT: kâr kilitleme %3 yapılırsa sonuç NEGATİFE döner (ölçüldü):
#        kâr kilidi mesafesi küçük olmalı.
PAPER_MURO_MODE = "trend"         # "trend" (Supertrend+geri çekilme)
PAPER_MURO_K = 3                  # swing pivot kolları (yapı varyantı)
PAPER_MURO_STOP_PCT = 0.025       # giriş stopu (fiyat %2,5)
PAPER_MURO_MAX_STOP_PCT = 0.05    # risk kapısı (stop en fazla %5)
PAPER_MURO_MIN_STOP_PCT = 0.015   # gürültü kapısı (stop en az %1,5)
PAPER_MURO_LOCK_PCT = 0.02        # kâr bankası (fiyat +%2) — kullanıcı kuralı
                                  # (tüm algoritmalarda +%2; önceden %1 idi)
PAPER_MURO_TRAIL_PCT = 0.02       # kilitleme sonrası trailing stop
PAPER_MURO_RETEST_ATR = 0.6       # kırılan seviyeye dönüş bandı (x ATR)
PAPER_MURO_MAX_RETEST = 24        # retest bekleme süresi (bar)
PAPER_MURO_TREND_EMA = 50         # yön filtresi (0 = filtre yok)
PAPER_MURO_ST_PERIOD = 10         # Supertrend periyodu
PAPER_MURO_ST_MULT = 3.0          # Supertrend çarpanı
PAPER_MURO_PULL_EMA = 50          # geri çekilme EMA'sı
PAPER_MURO_PULL_ATR = 1.5         # geri çekilme bandı (x ATR)
PAPER_MURO_COOLDOWN = 20          # iki giriş arası minimum bar
PAPER_MURO_RISK_PCT = 0.02        # işlem başına sermaye riski (%2)
PAPER_MURO_TRAIL_ALWAYS = False   # trailing stop yalnız kâr kilidinden
                                  # sonra devreye girer (ölçülen ayar)
PAPER_MURO_MAX_LOSSES = 0         # aynı yönde art arda N kayıptan sonra
                                  # dur (0 = kapalı; ölçümde fayda vermedi)

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
    record_neutral: bool = True   # NÖTR gecislerini de kaydet (varsayilan evet)
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
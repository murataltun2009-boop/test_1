"""
MURO algoritmasi.

KULLANICININ ISTEĞI (özet)
--------------------------
  * "Long en dipten tespit etsin, short en tepeden."
  * "Long'da elde edilen kazancı kaybetmeden short'a geçsin; %3 kazanç
     sağladıkça cüzdana atsın, yeniden long'a girsin."
  * "Short'a zarar ederek girmesin, en optimum noktayı yakalasın."
    (Short -> long geçişi için de aynı kural.)

MURO'NUN YAPISI (3 parça)
-------------------------
1) YAPI (structure) — fiyat kendi swing'lerini kırar:
     * son teyitli DIP (swing low) kırılırsa  -> asagi yön kırılımı
     * son teyitli TEPE (swing high) kırılırsa -> yukarı yön kırılımı
   Kırılımın kendisi giriş DEĞİLDİR: kırılım barda fiyat en kötü
   yere gelmiştir. MURO, kırılan seviyeye GERİ ÇEKİLME (retest)
   bekler ve girişi orada yapar. Bu "en optimum nokta" yaklaşımıdır:
   long, desteğe çekilmeden sonra alınır; short, kırılan desteğe
   tepki verince satılır.

2) KÂR KİLİDİ (profit lock) — pozisyon açıkken fiyat %3 (varsayılan)
   kâra ulaşınca:
     * pozisyon KAPATILIR -> kâr cüzdana (bakiyeye) yazılır,
     * AYNI YÖNDE yeniden pozisyon açılır, ama bu kez stop, kilitlenen
       kâr seviyesinde (başabaş) ve stop sonrası trailing ile.
   Böylece kâr "cüzdan'a atılır", sonraki bacak riski sıfırdan başlar.
   Trend devam ederse kâr birikir; trend dönse bile kilitlenen kâr
   cüzdanda kalır. Bu, "uzunun kazancını kaybetmeden short'a geç"
   isteğinin karşılığıdır.

3) POZİSYON YÖNETİMİ — yapısal stop (girişten sonraki dip/tepe),
   likidasyon koruması (stop, likidasyondan ÖNCE gelmeli) ve
   kilitleme sonrası trailing stop.

GIRIS/ÇIKIŞ OLAYLARI (action serisi)
-------------------------------------
  "AL"          : long'a gir
  "SAT"         : short'a gir
  "LONG_KAPAT"  : long pozisyonu kapanmalı (yapı kırıldı)
  "SHORT_KAPAT" : short pozisyonu kapanmalı (yapı kırıldı)

Olaylar pozisyondan BAĞIMSIZ üretilir; karar veren (paper trader)
kendi pozisyonuna göre uygular. Böylece canlı akış ile geriye
dönük test aynı kodu kullanır.

NEDEN BU KOD TEK YERDE?
------------------------
Aynı mantık hem canlı (servis) hem testte (paper.backtest) kullanılır.
Ayrı iki yazılırsa "testte kazandı, canlıda kaybetti" hatası kaçınılmaz
olur.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

import config
from core import indicators as ind

AL = "AL"
SAT = "SAT"
LONG_KAPAT = "LONG_KAPAT"
SHORT_KAPAT = "SHORT_KAPAT"

LONG = 1
SHORT = -1


@dataclass
class MuroConfig:
    """MURO parametreleri.

    stop_pct    : giriş stopu (fiyat yüzdesi). likidasyon koruması
                  bunu kaldiraca (ust sinir) birakir.
    max_stop_pct: yapısal stop bu orandan uzaksa fiyat yüzdesiyle
                  sinirlanir (risk kapisi).
    lock_pct    : kâr kilitleme eşiği (fiyat yüzdesi). %3 -> her %3
                  hareket kâr cüzdana yazilir ve pozisyon yeniden
                  acilir.
    trail_pct   : kilitleme sonrasi trailing stop mesafesi.
    retest_atr  : kirilan seviyeye donus bandi (x ATR).
    max_retest  : geri cekilme bekleme suresi (bar).
    k           : swing (pivot) kol uzunlugu: bar i, i-k..i+k
                  araliginda en dusuk/yuksek ise pivot sayilir ve
                  i+k barinda teyit edilir.
    """

    k: int = 3
    stop_pct: float = 0.025
    max_stop_pct: float = 0.05
    min_stop_pct: float = 0.015
    lock_pct: float = 0.03
    trail_pct: float = 0.03
    retest_atr: float = 0.6
    max_retest: int = 24
    atr_n: int = 14
    trend_ema: int = 50        # 0 = filtre yok
    buffer: float = 0.001      # stop ile fiyat arasindaki emniyet payi
    # ---- "trend" varyanti (Supertrend + geri cekilme girisi) ----
    mode: str = "structure"    # "structure" | "trend"
    st_period: int = 10
    st_mult: float = 3.0
    pull_ema: int = 20
    pull_atr: float = 0.5      # geri cekilme bandi (x ATR)
    cooldown: int = 10         # iki giris arasinda minimum bar
    pull_strong: bool = True   # sert geri alim (onceki barin yuksekligi)
    trail_always: bool = True  # trailing stop da kilitten once aktif
    flip_exit: bool = True     # yon degisiminde pozisyon kapanir mi
    max_losses: int = 2        # ayni yonde art arda N kayiptan sonra dur

    @staticmethod
    def from_config() -> "MuroConfig":
        return MuroConfig(
            mode=str(getattr(config, "PAPER_MURO_MODE", "trend")),
            k=int(config.PAPER_MURO_K),
            stop_pct=float(config.PAPER_MURO_STOP_PCT),
            max_stop_pct=float(config.PAPER_MURO_MAX_STOP_PCT),
            min_stop_pct=float(config.PAPER_MURO_MIN_STOP_PCT),
            lock_pct=float(config.PAPER_MURO_LOCK_PCT),
            trail_pct=float(config.PAPER_MURO_TRAIL_PCT),
            retest_atr=float(config.PAPER_MURO_RETEST_ATR),
            max_retest=int(config.PAPER_MURO_MAX_RETEST),
            trend_ema=int(config.PAPER_MURO_TREND_EMA),
            st_period=int(config.PAPER_MURO_ST_PERIOD),
            st_mult=float(config.PAPER_MURO_ST_MULT),
            pull_ema=int(config.PAPER_MURO_PULL_EMA),
            pull_atr=float(config.PAPER_MURO_PULL_ATR),
            cooldown=int(config.PAPER_MURO_COOLDOWN),
            trail_always=bool(getattr(config, "PAPER_MURO_TRAIL_ALWAYS",
                                      False)),
            max_losses=int(getattr(config, "PAPER_MURO_MAX_LOSSES", 0)),
        )


# --------------------------------------------------------------------------
# Swing (pivot) tespiti
# --------------------------------------------------------------------------
def pivots(high, low, k: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Swing dip (low) ve tepe (high) tespiti.

    DONUS: (dip, tepe)
      dip[i]  : i barinda TEYIT EDILEN swing low fiyati (NaN = yok)
      tepe[i] : i barinda TEYIT EDILEN swing high fiyati

    TEYIT KURALI: bar i, i-k..i+k araliginda EN DUSUK (EN YUKSEK) ise
    pivot olur ve bilgi ancak i+k barinda kullanilabilir. Boylece
    gelecege bakis (look-ahead) olmaz: i+k barinda yapilan karar
    yalnizca i+k'e kadar olan veriyi kullanir.

    Duz (flat) barlarda tekillik sarti kullanilir: birden fazla bar
    ayni minimumdaysa pivot sayilmaz.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    n = l.size
    dip = np.full(n, np.nan)
    tepe = np.full(n, np.nan)
    if n < 2 * k + 1:
        return dip, tepe
    for i in range(k, n - k):
        w = l[i - k:i + k + 1]
        if l[i] <= w.min() and int(np.argmin(w)) == k:
            dip[i + k] = l[i]
        w = h[i - k:i + k + 1]
        if h[i] >= w.max() and int(np.argmax(w)) == k:
            tepe[i + k] = h[i]
    return dip, tepe


# --------------------------------------------------------------------------
# Aksiyon serisi
# --------------------------------------------------------------------------
def actions(o, h, l, c, cfg: Optional[MuroConfig] = None) -> list[str]:
    """
    Bar basina aksiyon listesi. index i -> i barinin KAPANISI icin karar.

    KURALLAR
    --------
    * Kirilim: close < son teyitli dip  -> asagi kirilim (LONG_KAPAT)
               close > son teyitli tepe -> yukari kirilim (SHORT_KAPAT)
      Kirilim aninda yeni pozisyon ACILMAZ; kırılan seviyeye
      geri cekilme beklenir.
    * Retest: kirilan seviyeye fiyatin geri gelmesi (bant icinde) ve
      kapanisin tekrar kirilim yonunun USTUNDE (long) / ALTINDA
      (short) kalmasi -> giris (AL / SAT).
    * Retest zaman asimi: max_retest bar gelince beklenen retest
      iptal edilir ("peşine düşme" yok).
    """
    cfg = cfg or MuroConfig.from_config()
    if cfg.mode == "trend":
        return actions_trend(o, h, l, c, cfg)
    return actions_structure(o, h, l, c, cfg)


def actions_trend(o, h, l, c, cfg: Optional[MuroConfig] = None) -> list[str]:
    """
    TREND VARYANTI: Supertrend yonu + geri cekilme (pullback) girisi.

    * YON: Supertrend(period, mult). Yon degisiyince mevcut pozisyon
      kapanir (LONG_KAPAT / SHORT_KAPAT).
    * GIRIS: yon uyumlu iken fiyat kisa vadeli ortalamaya (EMA)
      geri cekilip geri alinirsa. Yani "long en dipten": trend yukarida
      iken dipte alinir, short tepeden: trend asagida iken zirvede
      satilir.
    * Supertrend yonu FLIP olmadan yeni pozisyon acilmaz; boylece
      "her geri cekilmede islem" yapilmaz (komisyon birikir).
    """
    cfg = cfg or MuroConfig.from_config()
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    n = c.size
    acts: list[str] = [""] * n
    if n < 40:
        return acts
    _, dirn = ind.supertrend(h, l, c, cfg.st_period, cfg.st_mult)
    ema_pull = ind.ema(c, cfg.pull_ema)
    a = ind.atr(h, l, c, cfg.atr_n)
    son_giris = -10 ** 6
    for i in range(n):
        d = int(dirn[i])
        prev = int(dirn[i - 1]) if i > 0 else 0
        if d == 0:
            continue
        # 1) yon degisi -> karsi pozisyon kapanir
        if prev != 0 and d != prev:
            acts[i] = LONG_KAPAT if d < 0 else SHORT_KAPAT
            continue
        # 2) geri cekilme girisi
        if i - son_giris < cfg.cooldown:
            continue
        av = a[i] if np.isfinite(a[i]) else 0.0
        band = cfg.pull_atr * av
        e = ema_pull[i]
        if not np.isfinite(e):
            continue
        if d > 0:
            if l[i] <= e + band and c[i] > e and c[i] > c[i - 1]:
                if cfg.pull_strong and i > 0 and c[i] <= h[i - 1]:
                    continue
                acts[i] = AL
                son_giris = i
        else:
            if h[i] >= e - band and c[i] < e and c[i] < c[i - 1]:
                if cfg.pull_strong and i > 0 and c[i] >= l[i - 1]:
                    continue
                acts[i] = SAT
                son_giris = i
    return acts


def actions_structure(o, h, l, c, cfg: Optional[MuroConfig] = None) -> list[str]:
    cfg = cfg or MuroConfig.from_config()
    o = np.asarray(o, dtype=float)
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    n = c.size
    acts: list[str] = [""] * n
    if n < 3 * cfg.k + 5:
        return acts

    a = ind.atr(h, l, c, cfg.atr_n)
    dip, tepe = pivots(h, l, cfg.k)
    trend = ind.ema(c, cfg.trend_ema) if cfg.trend_ema > 1 else None

    piv_lo = np.nan          # son teyitli dip fiyati
    piv_hi = np.nan          # son teyitli tepe fiyati
    ref_lo = np.nan          # kirilim tespiti icin (kirilimda temizlenir)
    ref_hi = np.nan
    pend_dir = 0             # +1 long, -1 short
    pend_level = np.nan
    pend_age = 0
    son_giris = -10 ** 6      # son giris barı (bekleme filtresi)

    for i in range(n):
        if not np.isnan(dip[i]):
            piv_lo = dip[i]
            ref_lo = dip[i]
        if not np.isnan(tepe[i]):
            piv_hi = tepe[i]
            ref_hi = tepe[i]

        av = a[i] if np.isfinite(a[i]) else 0.0
        band = cfg.retest_atr * av

        # ---- 1) kirilimlar ----
        bull = (not np.isnan(ref_hi)) and c[i] > ref_hi
        bear = (not np.isnan(ref_lo)) and c[i] < ref_lo
        if bear:
            acts[i] = LONG_KAPAT
            pend_dir = SHORT
            pend_level = ref_lo
            pend_age = 0
            ref_lo = np.nan          # ayni seviye ikinci kez kirilmasin
        elif bull:
            acts[i] = SHORT_KAPAT
            pend_dir = LONG
            pend_level = ref_hi
            pend_age = 0
            ref_hi = np.nan

        # ---- 2) geri cekilme (retest) ----
        if pend_dir and acts[i] == "":
            pend_age += 1
            if pend_dir == LONG:
                if (l[i] <= pend_level + band) and (c[i] > pend_level) and \
                        (i - son_giris >= cfg.cooldown):
                    # TREND FILTRESI: sadece ana yonunle gir.
                    # (Yapisal kirilim-retest, yana donus piyasalarinda
                    #  surekli yanlis yon sinyali uretir; filtre bunu
                    #  siler ve islem sayisini 5-10 kat dusurur.)
                    if trend is None or not np.isfinite(trend[i]) or \
                            c[i] > trend[i]:
                        acts[i] = AL
                        son_giris = i
                    pend_dir = 0
            else:
                if (h[i] >= pend_level - band) and (c[i] < pend_level) and \
                        (i - son_giris >= cfg.cooldown):
                    if trend is None or not np.isfinite(trend[i]) or \
                            c[i] < trend[i]:
                        acts[i] = SAT
                        son_giris = i
                    pend_dir = 0
            if pend_dir and pend_age > cfg.max_retest:
                pend_dir = 0            # zaman asimi: peşine düşme
    return acts


def last_action(o, h, l, c, cfg: Optional[MuroConfig] = None) -> str:
    """Son bar icin aksiyon (canli akista kullanilir)."""
    a = actions(o, h, l, c, cfg)
    return a[-1] if a else ""


# --------------------------------------------------------------------------
# Yapısal stop
# --------------------------------------------------------------------------
def structural_stop(side: int, price: float, lows: list[float],
                    highs: list[float], lookback: int,
                    cfg: Optional[MuroConfig] = None) -> float:
    """
    Giriş anindaki stop.

    Yapısal stop = giris barindan sonraki EN DUSUK (long) / EN YUKSEK
    (short) seviye. Bu, "fikir gecersizlesince" seviyesidir: swing
    kırılırsa stop olur.

    IKI SINIR:
      * min_stop_pct : stop girişe cok yakinsa (gurultu) uzaklastirilir.
        Aksi halde stop bir sonraki mumun gürültüsünde tetiklenir.
      * max_stop_pct : stop cok uzaksa (risk kapisi) fiyat yuzdesiyle
        sinirlanir; boylece risk (ve likidasyon) sinirli kalir.
    """
    cfg = cfg or MuroConfig.from_config()
    if price <= 0:
        return 0.0
    if side == LONG:
        seg_low = min(lows[-lookback:]) if lows else price
        stop = seg_low - cfg.buffer * seg_low
        # [max_stop_pct, min_stop_pct] araligina sikistir
        hi_lim = price * (1.0 - cfg.max_stop_pct)
        lo_lim = price * (1.0 - cfg.min_stop_pct)
        stop = min(max(stop, hi_lim), lo_lim)
        return min(stop, price * (1.0 - 0.0001))
    seg_high = max(highs[-lookback:]) if highs else price
    stop = seg_high + cfg.buffer * seg_high
    lo_lim = price * (1.0 + cfg.max_stop_pct)
    hi_lim = price * (1.0 + cfg.min_stop_pct)
    stop = max(min(stop, lo_lim), hi_lim)
    return max(stop, price * (1.0 + 0.0001))


def lock_price(side: int, entry: float, cfg: Optional[MuroConfig] = None) -> float:
    """Kâr kilitleme fiyati (girişe göre +lock_pct)."""
    cfg = cfg or MuroConfig.from_config()
    return entry * (1.0 + cfg.lock_pct) if side == LONG else \
        entry * (1.0 - cfg.lock_pct)

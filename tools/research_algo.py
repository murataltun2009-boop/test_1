"""
Yeni islem algoritmasi arastirmasi.

AMAC
----
Kullanicinin istegi:
  "Bitcoin listemden 10 coin icin en az 500 mumluk test yap; komisyonu da
   dusunerek en yuksek getirili, en az 10x-20x kaldiracli LONG/SHORT
   algoritmasi uret. Testlerden gecerse uygulamaya ekle."

BU ARAC NE YAPAR
----------------
1) Binance Futures'tan 4h mum indirir (varsayilan 3000 bar = ~500 gun).
2) Bircok aday kural ailesini AYNI gercekci simulatorle olcer.
3) Orneklemi ZAMAN olarak boler: ilk %60 kesif, son %40 dogrulama.
4) Komisyon + kayma + funding maliyetini uygular.
5) Sonucu JSON + tablo olarak yazar.

NEDEN BOYLE
-----------
Onceki turlarda "ham getiri" yaniltici cikti: piyasa yonu ile karisiyor.
Bu yuzden burada:
  * her strateji AYNI maliyet modeliyle kosar,
  * secim SADECE kesif doneminde yapilir,
  * dogrulama donemi SECIM ICIN KULLANILMAZ,
  * coin bazinda tutarlilik (kac coin karda) raporlanir.

KULLANIM
--------
  python tools/research_algo.py fetch
  python tools/research_algo.py scan
  python tools/research_algo.py validate
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core import indicators as ind

# --------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------
RESEARCH_DIR = os.path.join(config.DATA_DIR, "research")
INTERVAL = "4h"
BARS = 3000                 # ~500 gun
FEE_RATE = 0.0005           # Binance Futures taker (%0,05)
SLIPPAGE = 0.0002           # %0,02 (piyasa emri kaysi)
FUNDING_PER_BAR = 0.00005   # %0,01 / 8h -> 4h bar basina, HER iki yonde
WALLET_FRACTION = 0.80
LEVERAGE = 10.0
START_BALANCE = 1000.0
WARMUP = 210                # en uzun indikator penceresi (EMA200 + pay)

COINS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT",
]

# Secimde KULLANILMAYAN coinler — en guclu asiri-uyum testi.
HOLDOUT = [
    "SUIUSDT", "TIAUSDT", "ENAUSDT", "1000PEPEUSDT", "FILUSDT",
    "UNIUSDT", "HBARUSDT", "XMRUSDT", "INJUSDT", "TAOUSDT",
    "APTUSDT", "DOTUSDT", "ARBUSDT", "ONDOUSDT", "HYPEUSDT",
]


# --------------------------------------------------------------------------
# Veri
# --------------------------------------------------------------------------
def _path(symbol: str, interval: Optional[str] = None) -> str:
    return os.path.join(RESEARCH_DIR, f"{interval or INTERVAL}_{symbol}.json")


def fetch_one(symbol: str, interval: Optional[str] = None,
              total: Optional[int] = None) -> dict:
    """Binance'ten geriye dogru sayfalayarak mum indirir."""
    interval = interval or INTERVAL
    total = total or BARS
    url = f"{config.FAPI_REST}/fapi/v1/klines"
    rows: list[list] = []
    end: Optional[int] = None
    while len(rows) < total:
        take = min(1500, total - len(rows))
        params = {"symbol": symbol, "interval": interval, "limit": take}
        if end is not None:
            params["endTime"] = end
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        rows = data + rows
        end = int(data[0][0]) - 1
        time.sleep(0.12)
    rows = rows[-total:]
    return {
        "symbol": symbol,
        "interval": interval,
        "t": [int(k[0]) for k in rows],
        "o": [float(k[1]) for k in rows],
        "h": [float(k[2]) for k in rows],
        "l": [float(k[3]) for k in rows],
        "c": [float(k[4]) for k in rows],
        "v": [float(k[5]) for k in rows],
    }


def fetch_all(coins: Optional[list[str]] = None) -> None:
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    for sym in (coins or COINS):
        p = _path(sym)
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if len(d["c"]) >= BARS:
                    print(f"  {sym:<12} onbellekte ({len(d['c'])} bar)")
                    continue
            except Exception:      # noqa: BLE001
                pass
        print(f"  {sym:<12} indiriliyor...", end="", flush=True)
        d = fetch_one(sym)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f" {len(d['c'])} bar")


def load(symbol: str, interval: Optional[str] = None) -> dict:
    with open(_path(symbol, interval), encoding="utf-8") as f:
        d = json.load(f)
    return {k: np.asarray(v, dtype=np.float64) if k not in
            ("symbol", "interval") else v for k, v in d.items()}


# --------------------------------------------------------------------------
# Indikatorler (core.indicators + yerel ATR/rolling std)
# --------------------------------------------------------------------------
def atr(h, l, c, n: int = 14) -> np.ndarray:
    prev = np.roll(c, 1)
    prev[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - prev), np.abs(l - prev)])
    return ind.rma(tr, n)


def rolling_std(x, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full(x.size, np.nan)
    if x.size < n:
        return out
    win = np.lib.stride_tricks.sliding_window_view(x, n)
    out[n - 1:] = win.std(axis=1)
    return out


def shift1(x) -> np.ndarray:
    """Bir bar geriye kaydirir (karar verirken GELECEĞİ gormemek icin)."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.size, np.nan)
    out[1:] = x[:-1]
    return out


# --------------------------------------------------------------------------
# Simulator — gercekci
# --------------------------------------------------------------------------
@dataclass
class Result:
    name: str
    coin: str
    ret_pct: float
    maxdd_pct: float
    trades: int
    wins: int
    win_rate: float
    profit_factor: float
    liquidations: int
    final_equity: float
    avg_bars: float
    sharpe: float
    avg_lev: float = 0.0


def simulate(name: str, coin: str, o, h, l, c, atr_series, target,
             stop_mult: float, trail_mult: float,
             leverage: float = LEVERAGE,
             wallet: float = WALLET_FRACTION,
             fee: float = FEE_RATE, slip: float = SLIPPAGE,
             funding: float = FUNDING_PER_BAR,
             start_i: int = WARMUP,
             end_i: Optional[int] = None,
             risk_pct: float = 0.0) -> Result:
    """
    Hedef pozisyon dizisini bar bazinda uygular.

    target[i] : i barinin KAPANISINDA verilen karar; i+1 barinin ACILISINDA
                uygulanir (gelecege bakis yok).
    stop_mult : giris ATR'sinin kac kati baslangic stopu.
    trail_mult: kapanista ATR'ye gore takip eden stop.
    """
    n = len(c)
    end_i = n - 1 if end_i is None else min(end_i, n - 1)
    eq = START_BALANCE
    peak = eq
    maxdd = 0.0
    pos = 0
    entry = 0.0
    qty = 0.0
    stop = 0.0
    notional = 0.0
    pos_lev = leverage
    bars_open = 0
    trades: list[tuple[float, float, float]] = []   # (net_pnl, bars, equity)
    liq_count = 0
    lev_sum = 0.0
    lev_n = 0

    def close_at(price: float, i: int) -> None:
        nonlocal eq, pos, qty, entry, notional, bars_open
        px = price * (1 - slip) if pos == 1 else price * (1 + slip)
        pnl = (px - entry) * qty * pos
        eq += pnl - qty * px * fee
        trades.append((pnl - notional * fee - qty * px * fee, bars_open, eq))
        pos = 0
        qty = 0.0
        entry = 0.0
        notional = 0.0
        bars_open = 0

    def open_at(price: float, direction: int, i: int) -> None:
        nonlocal eq, pos, qty, entry, stop, notional, bars_open, pos_lev
        nonlocal lev_sum, lev_n
        px = price * (1 + slip) if direction == 1 else price * (1 - slip)
        sl = stop_mult * atr_series[i]
        stop_frac = sl / px if px > 0 else 0.0
        # LI KIDASYON KORUMASI: stop, likidasyon mesafesinden ONCE
        # tetiklenmeli. Aksi halde yuksek volatilitede stop'a hic
        # gelinmeden pozisyon likide olur (olculdu: 8 kez).
        # Likidasyon mesafesi ~ 1/lev_eff oldugu icin:
        #     lev_eff <= 0.6 / stop_frac
        # sartini uyguluyoruz (0,6 = guvenlik payi).
        lev_eff = leverage
        if stop_frac > 0:
            lev_eff = min(leverage, 0.6 / stop_frac)
        if risk_pct > 0 and sl > 0:
            # RISK BAZLI: stop mesafesi kadar kaybedince sermayenin
            # risk_pct kadari gitsin. Kaldirac yalnizca UST SINIR.
            notional = eq * risk_pct / max(stop_frac, 1e-4)
            notional = min(notional, eq * wallet * lev_eff)
        else:
            notional = eq * wallet * lev_eff
        if notional <= 0 or eq <= 0:
            return
        qty = notional / px
        eq -= notional * fee
        pos = direction
        pos_lev = lev_eff
        entry = px
        stop = px - direction * sl
        bars_open = 0
        lev_sum += notional / max(eq, 1e-9)
        lev_n += 1

    for i in range(start_i, end_i):
        j = i + 1                           # karar -> sonraki bar acilisi
        t = int(target[i]) if np.isfinite(target[i]) else 0

        # ---- istenen yone gec ----
        if t != pos:
            if pos != 0:
                close_at(float(o[j]), j)
            if t != 0 and eq > 1.0:
                open_at(float(o[j]), t, i)

        # ---- bar ici stop / likidasyon ----
        if pos != 0:
            bars_open += 1
            liq_px = (entry * (1 - 1.0 / pos_lev) if pos == 1
                      else entry * (1 + 1.0 / pos_lev))
            if pos == 1:
                if l[j] <= liq_px:
                    close_at(liq_px, j)
                    liq_count += 1
                elif l[j] <= stop:
                    close_at(min(stop, float(o[j])), j)
            else:
                if h[j] >= liq_px:
                    close_at(liq_px, j)
                    liq_count += 1
                elif h[j] >= stop:
                    close_at(max(stop, float(o[j])), j)

        # ---- takip eden stop (kapanista guncelle) ----
        if pos == 1:
            stop = max(stop, float(c[j]) - trail_mult * atr_series[j])
        elif pos == -1:
            stop = min(stop, float(c[j]) + trail_mult * atr_series[j])

        # ---- funding ----
        if pos != 0 and funding:
            eq -= notional * funding

        # ---- isaretle ----
        mark = eq + ((c[j] - entry) * qty * pos if pos != 0 else 0.0)
        peak = max(peak, mark)
        if peak > 0:
            maxdd = max(maxdd, (peak - mark) / peak * 100.0)

    # son pozisyonu kapat
    if pos != 0:
        close_at(float(c[end_i]), end_i)

    wins = sum(1 for t_ in trades if t_[0] > 0)
    gross_win = sum(t_[0] for t_ in trades if t_[0] > 0)
    gross_loss = -sum(t_[0] for t_ in trades if t_[0] < 0)
    pf = gross_win / gross_loss if gross_loss > 0 else (
        float("inf") if gross_win > 0 else 0.0)
    # bar getirilerinden yillik Sharpe (4h -> yilda 6*365 bar)
    rets = []
    prev = START_BALANCE
    # equity egrisini yeniden kurmak yerine islem sonuçlarindan kaba sharpe
    for pnl, _, _ in trades:
        rets.append(pnl / START_BALANCE)
    sharpe = (np.mean(rets) / np.std(rets) * math.sqrt(6 * 365 / 250)
              if len(rets) > 2 and np.std(rets) > 0 else 0.0)

    return Result(
        name=name, coin=coin,
        ret_pct=(eq / START_BALANCE - 1) * 100 if pos == 0 else
        ((eq + (c[end_i] - entry) * qty * pos) / START_BALANCE - 1) * 100,
        maxdd_pct=maxdd,
        trades=len(trades),
        wins=wins,
        win_rate=(wins / len(trades) * 100) if trades else 0.0,
        profit_factor=float(pf),
        liquidations=liq_count,
        final_equity=eq,
        avg_bars=(np.mean([t_[1] for t_ in trades]) if trades else 0.0),
        sharpe=float(sharpe),
        avg_lev=(lev_sum / lev_n) if lev_n else 0.0,
    )


# --------------------------------------------------------------------------
# Stratejiler — her biri KAPANIS bazli hedef pozisyon dizisi dondurur
# --------------------------------------------------------------------------
def strat_donchian(h, l, c, n_entry: int, n_exit: int,
                   trend_ema: int = 0) -> np.ndarray:
    upper = shift1(ind.rolling_max(h, n_entry))
    lower = shift1(ind.rolling_min(l, n_entry))
    xup = shift1(ind.rolling_max(h, n_exit))
    xdn = shift1(ind.rolling_min(l, n_exit))
    ema = ind.ema(c, trend_ema) if trend_ema else np.full(c.size, np.nan)
    out = np.zeros(c.size)
    state = 0
    for i in range(1, c.size):
        if state == 0:
            if np.isfinite(upper[i]) and c[i] > upper[i] and \
                    (not trend_ema or c[i] > ema[i]):
                state = 1
            elif np.isfinite(lower[i]) and c[i] < lower[i] and \
                    (not trend_ema or c[i] < ema[i]):
                state = -1
        elif state == 1:
            if np.isfinite(xdn[i]) and c[i] < xdn[i]:
                state = 0
        else:
            if np.isfinite(xup[i]) and c[i] > xup[i]:
                state = 0
        out[i] = state
    return out


def strat_supertrend(h, l, c, period: int, mult: float) -> np.ndarray:
    a = atr(h, l, c, period)
    hl2 = (h + l) / 2.0
    ub = hl2 + mult * a
    lb = hl2 - mult * a
    n = c.size
    fub = np.full(n, np.nan)
    flb = np.full(n, np.nan)
    out = np.zeros(n)
    trend = 1
    for i in range(1, n):
        if not np.isfinite(a[i]):
            continue
        fub[i] = min(ub[i], fub[i - 1]) if (np.isfinite(fub[i - 1]) and
                                            c[i - 1] <= fub[i - 1]) else ub[i]
        flb[i] = max(lb[i], flb[i - 1]) if (np.isfinite(flb[i - 1]) and
                                            c[i - 1] >= flb[i - 1]) else lb[i]
        if trend == 1 and c[i] < flb[i]:
            trend = -1
        elif trend == -1 and c[i] > fub[i]:
            trend = 1
        out[i] = trend
    return out


def strat_ema_cross(c, fast: int, slow: int, trend_ema: int = 0) -> np.ndarray:
    f = ind.ema(c, fast)
    s = ind.ema(c, slow)
    out = np.zeros(c.size)
    out[f > s] = 1
    out[f < s] = -1
    if trend_ema:
        e = ind.ema(c, trend_ema)
        out[(out == 1) & (c < e)] = 0
        out[(out == -1) & (c > e)] = 0
    return out


def strat_momentum(c, lookback: int, thresh: float,
                   trend_ema: int = 0) -> np.ndarray:
    r = c / ind.shift(c, lookback) - 1.0
    out = np.zeros(c.size)
    out[r > thresh] = 1
    out[r < -thresh] = -1
    if trend_ema:
        e = ind.ema(c, trend_ema)
        out[(out == 1) & (c < e)] = 0
        out[(out == -1) & (c > e)] = 0
    return out


def strat_rsi_mr(c, entry: float, exit_: float, trend_ema: int = 200,
                 max_bars: int = 24) -> np.ndarray:
    r = ind.rsi(c, 14)
    e = ind.ema(c, trend_ema) if trend_ema else np.full(c.size, np.nan)
    out = np.zeros(c.size)
    state = 0
    bars = 0
    for i in range(1, c.size):
        bars += 1
        if state == 0:
            if r[i] < entry and (not trend_ema or c[i] > e[i]):
                state = 1
                bars = 0
            elif r[i] > 100 - entry and (not trend_ema or c[i] < e[i]):
                state = -1
                bars = 0
        elif state == 1:
            if r[i] > exit_ or bars >= max_bars:
                state = 0
        else:
            if r[i] < 100 - exit_ or bars >= max_bars:
                state = 0
        out[i] = state
    return out


def strat_boll_break(c, n: int, mult: float, trend_ema: int = 200,
                     exit_mid: bool = True) -> np.ndarray:
    mid = ind.sma(c, n)
    sd = rolling_std(c, n)
    up = mid + mult * sd
    dn = mid - mult * sd
    e = ind.ema(c, trend_ema) if trend_ema else np.full(c.size, np.nan)
    out = np.zeros(c.size)
    state = 0
    for i in range(1, c.size):
        if state == 0:
            if np.isfinite(up[i]) and c[i] > up[i] and \
                    (not trend_ema or c[i] > e[i]):
                state = 1
            elif np.isfinite(dn[i]) and c[i] < dn[i] and \
                    (not trend_ema or c[i] < e[i]):
                state = -1
        elif state == 1:
            if (exit_mid and c[i] < mid[i]) or \
                    (not exit_mid and np.isfinite(dn[i]) and c[i] < dn[i]):
                state = 0
        else:
            if (exit_mid and c[i] > mid[i]) or \
                    (not exit_mid and np.isfinite(up[i]) and c[i] > up[i]):
                state = 0
        out[i] = state
    return out


def strat_boll_filtered(h, l, c, v, n: int, mult: float,
                        trend_ema: int = 200, exit_mid: bool = True,
                        vol_mult: float = 0.0, adx_min: float = 0.0,
                        long_only: bool = False) -> np.ndarray:
    """
    Bollinger kirilimi + istege bagli hacim / ADX filtreleri.

    vol_mult > 0 : kirilim bari, 20 barlik ortalama hacmin vol_mult kati
                   olmali (gercek katilim).
    adx_min  > 0 : ADX(14) >= adx_min (trend gucu).
    long_only    : SHORT sinyalleri yok say (boga piyasasi egilimi testi).
    """
    mid = ind.sma(c, n)
    sd = rolling_std(c, n)
    up = mid + mult * sd
    dn = mid - mult * sd
    e = ind.ema(c, trend_ema) if trend_ema else np.full(c.size, np.nan)
    vma = ind.rolling_mean(v, 20) if vol_mult > 0 else np.full(c.size, np.nan)
    if adx_min > 0:
        adx_line, _, _ = ind.adx(h, l, c, 14)
    else:
        adx_line = np.full(c.size, np.nan)
    out = np.zeros(c.size)
    state = 0
    for i in range(1, c.size):
        ok_vol = (vol_mult <= 0) or (np.isfinite(vma[i]) and
                                     v[i] >= vol_mult * vma[i])
        ok_adx = (adx_min <= 0) or (np.isfinite(adx_line[i]) and
                                    adx_line[i] >= adx_min)
        if state == 0:
            if ok_vol and ok_adx and np.isfinite(up[i]) and c[i] > up[i] and \
                    (not trend_ema or c[i] > e[i]):
                state = 1
            elif (not long_only) and ok_vol and ok_adx and \
                    np.isfinite(dn[i]) and c[i] < dn[i] and \
                    (not trend_ema or c[i] < e[i]):
                state = -1
        elif state == 1:
            if (exit_mid and c[i] < mid[i]) or \
                    (not exit_mid and np.isfinite(dn[i]) and c[i] < dn[i]):
                state = 0
        else:
            if (exit_mid and c[i] > mid[i]) or \
                    (not exit_mid and np.isfinite(up[i]) and c[i] > up[i]):
                state = 0
        out[i] = state
    return out


def strat_pullback(c, h, l, trend_ema: int = 200, rsi_entry: float = 45,
                   rsi_exit: float = 60) -> np.ndarray:
    """Yukselis trendinde geri cekilme -> LONG; dususte tepki -> SHORT."""
    e = ind.ema(c, trend_ema)
    r = ind.rsi(c, 14)
    out = np.zeros(c.size)
    state = 0
    for i in range(1, c.size):
        if state == 0:
            if c[i] > e[i] and r[i] < rsi_entry:
                state = 1
            elif c[i] < e[i] and r[i] > 100 - rsi_entry:
                state = -1
        elif state == 1:
            if r[i] > rsi_exit or c[i] < e[i]:
                state = 0
        else:
            if r[i] < 100 - rsi_exit or c[i] > e[i]:
                state = 0
        out[i] = state
    return out


def strat_breakout_atr(h, l, c, n: int, atr_mult: float,
                       trend_ema: int = 0) -> np.ndarray:
    """
    Sikisma sonrasi kirilim: son n barin en dar araligi (ATR/close dusuk)
    ve fiyat o araligin disina cikti.
    """
    a = atr(h, l, c, 14) / c
    base = ind.rolling_mean(a, n)
    hi = shift1(ind.rolling_max(h, n))
    lo = shift1(ind.rolling_min(l, n))
    e = ind.ema(c, trend_ema) if trend_ema else np.full(c.size, np.nan)
    out = np.zeros(c.size)
    state = 0
    for i in range(1, c.size):
        squeeze = np.isfinite(base[i]) and a[i] < base[i]
        if state == 0 and squeeze:
            if c[i] > hi[i] and (not trend_ema or c[i] > e[i]):
                state = 1
            elif c[i] < lo[i] and (not trend_ema or c[i] < e[i]):
                state = -1
        elif state == 1 and c[i] < lo[i]:
            state = 0
        elif state == -1 and c[i] > hi[i]:
            state = 0
        out[i] = state
    return out


# --------------------------------------------------------------------------
# Aday listesi
# --------------------------------------------------------------------------
def candidates() -> list[dict]:
    """(isim, fonksiyon, stop_mult, trail_mult, parametreler)"""
    out: list[dict] = []
    # Donchian / Turtle
    for n in (20, 40, 55):
        for m in (10, 20):
            for tr in (0, 200):
                out.append(dict(
                    name=f"donchian_{n}_{m}_ema{tr}",
                    fn=lambda h, l, c, v, n=n, m=m, tr=tr:
                        strat_donchian(h, l, c, n, m, tr),
                    stop=2.5, trail=2.5))
    # Supertrend
    for p in (7, 10, 14, 20):
        for m in (2.0, 3.0, 4.0):
            out.append(dict(
                name=f"supertrend_{p}_{m:g}",
                fn=lambda h, l, c, v, p=p, m=m:
                    strat_supertrend(h, l, c, p, m),
                stop=3.0, trail=3.0))
    # EMA kesisimi
    for f, s in ((9, 21), (20, 50), (21, 55), (50, 200)):
        for tr in (0, 200):
            out.append(dict(
                name=f"emacross_{f}_{s}_ema{tr}",
                fn=lambda h, l, c, v, f=f, s=s, tr=tr:
                    strat_ema_cross(c, f, s, tr),
                stop=3.0, trail=3.0))
    # Momentum
    for lb in (10, 20, 40):
        for th in (0.0, 0.01, 0.02):
            out.append(dict(
                name=f"mom_{lb}_{th:g}_ema200",
                fn=lambda h, l, c, v, lb=lb, th=th:
                    strat_momentum(c, lb, th, 200),
                stop=3.0, trail=3.0))
    # RSI mean reversion
    for en in (20, 30):
        for ex in (55, 65):
            out.append(dict(
                name=f"rsi_mr_{en}_{ex}",
                fn=lambda h, l, c, v, en=en, ex=ex:
                    strat_rsi_mr(c, en, ex, 200, 24),
                stop=2.0, trail=4.0))
    # Bollinger kirilimi
    for n in (20, 40):
        for m in (2.0, 2.5):
            out.append(dict(
                name=f"boll_{n}_{m:g}",
                fn=lambda h, l, c, v, n=n, m=m:
                    strat_boll_break(c, n, m, 200, True),
                stop=2.5, trail=2.5))
    # Bollinger + filtre varyantlari (ana aday ailesi)
    for n, m in ((40, 2.0), (40, 2.5), (20, 2.0)):
        tag = f"bollf_{n}_{m:g}"
        out.append(dict(
            name=f"{tag}_vol",
            fn=lambda h, l, c, v, n=n, m=m:
                strat_boll_filtered(h, l, c, v, n, m, 200, True, 1.2, 0),
            stop=2.0, trail=3.0))
        out.append(dict(
            name=f"{tag}_adx",
            fn=lambda h, l, c, v, n=n, m=m:
                strat_boll_filtered(h, l, c, v, n, m, 200, True, 0, 20),
            stop=2.0, trail=3.0))
        out.append(dict(
            name=f"{tag}_voladx",
            fn=lambda h, l, c, v, n=n, m=m:
                strat_boll_filtered(h, l, c, v, n, m, 200, True, 1.2, 20),
            stop=2.0, trail=3.0))
        out.append(dict(
            name=f"{tag}_nomid",
            fn=lambda h, l, c, v, n=n, m=m:
                strat_boll_filtered(h, l, c, v, n, m, 200, False, 0, 0),
            stop=2.0, trail=3.0))
        out.append(dict(
            name=f"{tag}_long",
            fn=lambda h, l, c, v, n=n, m=m:
                strat_boll_filtered(h, l, c, v, n, m, 200, True, 0, 0, True),
            stop=2.0, trail=3.0))
    # Trend icinde geri cekilme
    for en in (35, 45):
        for ex in (55, 65):
            out.append(dict(
                name=f"pullback_{en}_{ex}",
                fn=lambda h, l, c, v, en=en, ex=ex:
                    strat_pullback(c, h, l, 200, en, ex),
                stop=2.0, trail=3.0))
    # Sikisma kirilimi
    for n in (10, 20):
        out.append(dict(
            name=f"squeeze_{n}",
            fn=lambda h, l, c, v, n=n:
                strat_breakout_atr(h, l, c, n, 0, 200),
            stop=2.5, trail=2.5))
    return out


# --------------------------------------------------------------------------
# Kosu
# --------------------------------------------------------------------------
def run(coins: list[str], split: float = 0.60,
        leverage: float = LEVERAGE) -> dict:
    data = {s: load(s) for s in coins}
    n_min = min(len(d["c"]) for d in data.values())
    cut = int(n_min * split)

    cands = candidates()
    print(f"Veri: {len(coins)} coin x {n_min} bar ({INTERVAL})")
    print(f"Kesif: 0..{cut}  |  Dogrulama: {cut}..{n_min}")
    print(f"Kaldirac {leverage:g}x · teminat %{WALLET_FRACTION*100:.0f} · "
          f"komisyon %{FEE_RATE*100:.3f} · kayma %{SLIPPAGE*100:.3f} · "
          f"funding %{FUNDING_PER_BAR*100:.4f}/bar")
    print()

    rows = []
    for ci, cand in enumerate(cands):
        per_coin = []
        for sym in coins:
            d = data[sym]
            o, h, l, c = d["o"], d["h"], d["l"], d["c"]
            a = atr(h, l, c, 14)
            target = cand["fn"](h, l, c, d["v"])
            # kesif
            r1 = simulate(cand["name"], sym, o, h, l, c, a, target,
                          cand["stop"], cand["trail"], leverage=leverage,
                          start_i=WARMUP, end_i=cut)
            per_coin.append(r1)
        rets = [r.ret_pct for r in per_coin]
        rows.append(dict(
            name=cand["name"],
            med=float(np.median(rets)),
            mean=float(np.mean(rets)),
            worst=float(min(rets)),
            pos=sum(1 for x in rets if x > 0),
            trades=sum(r.trades for r in per_coin),
            pf=float(np.median([r.profit_factor for r in per_coin
                                if np.isfinite(r.profit_factor)] or [0])),
            maxdd=float(np.median([r.maxdd_pct for r in per_coin])),
            per_coin=[round(r.ret_pct, 1) for r in per_coin],
        ))
        if (ci + 1) % 10 == 0:
            print(f"  ... {ci+1}/{len(cands)} aday olculdu")

    rows.sort(key=lambda r: (-r["med"], -r["pos"]))
    print()
    print(f"{'ADAY':<24}{'MED%':>9}{'ORT%':>9}{'EN KOTU':>10}"
          f"{'KAR COIN':>10}{'ISLEM':>7}{'PF':>7}{'MAXDD':>8}")
    print("-" * 86)
    for r in rows[:25]:
        print(f"{r['name']:<24}{r['med']:>9.1f}{r['mean']:>9.1f}"
              f"{r['worst']:>10.1f}{r['pos']:>7}/{len(coins)}"
              f"{r['trades']:>7}{r['pf']:>7.2f}{r['maxdd']:>8.1f}")
    return {"rows": rows, "cut": cut, "bars": n_min, "leverage": leverage}


def validate(top_names: list[str], coins: list[str], split: float = 0.60,
             leverage: float = LEVERAGE) -> None:
    """Secilen adaylari SADECE dogrulama doneminde kosar."""
    data = {s: load(s) for s in coins}
    n_min = min(len(d["c"]) for d in data.values())
    cut = int(n_min * split)
    by_name = {c["name"]: c for c in candidates()}
    print(f"DOGRULAMA (kesifte secilmeyen donem): {cut}..{n_min}")
    print(f"{'ADAY':<24}{'MED%':>9}{'ORT%':>9}{'EN KOTU':>10}"
          f"{'KAR COIN':>10}{'ISLEM':>7}{'PF':>7}{'MAXDD':>8}")
    print("-" * 86)
    for name in top_names:
        cand = by_name[name]
        res = []
        for sym in coins:
            d = data[sym]
            o, h, l, c = d["o"], d["h"], d["l"], d["c"]
            a = atr(h, l, c, 14)
            target = cand["fn"](h, l, c, d["v"])
            res.append(simulate(name, sym, o, h, l, c, a, target,
                                cand["stop"], cand["trail"], leverage=leverage,
                                start_i=max(cut, WARMUP), end_i=n_min - 1))
        rets = [r.ret_pct for r in res]
        print(f"{name:<24}{np.median(rets):>9.1f}{np.mean(rets):>9.1f}"
              f"{min(rets):>10.1f}{sum(1 for x in rets if x>0):>7}/{len(coins)}"
              f"{sum(r.trades for r in res):>7}"
              f"{np.median([r.profit_factor for r in res if np.isfinite(r.profit_factor)] or [0]):>7.2f}"
              f"{np.median([r.maxdd_pct for r in res]):>8.1f}")
        print("    coin: " + "  ".join(
            f"{sym.replace('USDT','')} {r.ret_pct:+.0f}%" for sym, r in zip(coins, res)))


def fold_bounds(n: int, folds: int = 5) -> list[tuple[int, int]]:
    """[start, end) sinirlari. Her fold esit uzunlukta."""
    size = n // folds
    out = []
    for k in range(folds):
        a = k * size
        b = n - 1 if k == folds - 1 else (k + 1) * size
        out.append((max(a, WARMUP), b))
    return out


def run_folds(coins: list[str], fold_range: Optional[list[int]] = None,
              folds: int = 5, risk_pct: float = 0.01,
              leverage: float = LEVERAGE,
              use_funding: bool = True,
              only: Optional[list[str]] = None) -> dict:
    """
    Her adayi her fold'da kosar. Donemler BAGIMSIZ baslar (bakiye sifirlanir).

    risk_pct > 0 ise pozisyon, stop mesafesine gore boyutlandirilir ve
    kaldirac yalnizca ust sinir olur. risk_pct = 0 ise eski (agresif)
    model: teminat x kaldirac.
    """
    data = {s: load(s) for s in coins}
    n_min = min(len(d["c"]) for d in data.values())
    bounds = fold_bounds(n_min, folds)
    if fold_range is None:
        fold_range = list(range(folds))

    cands = candidates()
    if only:
        cands = [c for c in cands if c["name"] in set(only)]
    funding = FUNDING_PER_BAR if use_funding else 0.0
    print(f"Veri {len(coins)} coin x {n_min} bar | fold {fold_range} | "
          f"risk {'%' + str(risk_pct * 100) if risk_pct else 'SABIT'}"
          f" | kaldirac tavani {leverage:g}x")

    rows = []
    for ci, cand in enumerate(cands):
        cells: list[float] = []
        dds: list[float] = []
        pfs: list[float] = []
        ntr = 0
        for fi in fold_range:
            for sym in coins:
                d = data[sym]
                o, h, l, c = d["o"], d["h"], d["l"], d["c"]
                a, b = fold_bounds(len(c), folds)[fi]   # coin basina fold
                at = atr(h, l, c, 14)
                target = cand["fn"](h, l, c, d["v"])
                r = simulate(cand["name"], sym, o, h, l, c, at, target,
                             cand["stop"], cand["trail"],
                             leverage=leverage, funding=funding,
                             risk_pct=risk_pct,
                             start_i=a, end_i=b)
                cells.append(r.ret_pct)
                dds.append(r.maxdd_pct)
                if np.isfinite(r.profit_factor):
                    pfs.append(r.profit_factor)
                ntr += r.trades
        rows.append(dict(
            name=cand["name"],
            med=float(np.median(cells)),
            mean=float(np.mean(cells)),
            pos=sum(1 for x in cells if x > 0) / len(cells) * 100,
            worst=float(min(cells)),
            trades=ntr,
            pf=float(np.median(pfs)) if pfs else 0.0,
            maxdd=float(np.median(dds)),
        ))
        if (ci + 1) % 10 == 0:
            print(f"  ... {ci+1}/{len(cands)}")

    rows.sort(key=lambda r: (-r["med"], -r["pos"]))
    return {"rows": rows, "bounds": bounds, "folds": fold_range,
            "risk_pct": risk_pct, "leverage": leverage}


def print_rows(rows: list[dict], title: str, top: int = 20) -> None:
    print()
    print(title)
    print(f"{'ADAY':<24}{'MED%':>9}{'ORT%':>9}{'EN KOTU':>10}"
          f"{'KAR%':>8}{'ISLEM':>7}{'PF':>7}{'MAXDD':>8}")
    print("-" * 82)
    for r in rows[:top]:
        print(f"{r['name']:<24}{r['med']:>9.1f}{r['mean']:>9.1f}"
              f"{r['worst']:>10.1f}{r['pos']:>7.0f}%{r['trades']:>7}"
              f"{r['pf']:>7.2f}{r['maxdd']:>8.1f}")


def tune(base_name: str, coins: list[str], risk: float = 0.02,
         stops=(1.5, 2.0, 2.5, 3.0, 4.0),
         trails=(1.5, 2.0, 3.0, 4.0, 6.0)) -> None:
    """Bir strateji ailesinin stop/trail izgarasini kesif+dogrulama ayri olcer."""
    by = {c["name"]: c for c in candidates()}
    base = by[base_name]
    data = {s: load(s) for s in coins}
    n = min(len(d["c"]) for d in data.values())
    bounds = fold_bounds(n, 5)
    cache = {}
    for s in coins:
        d = data[s]
        cache[s] = (d["o"], d["h"], d["l"], d["c"], atr(d["h"], d["l"], d["c"], 14),
                    base["fn"](d["h"], d["l"], d["c"], d["v"]))

    def ev(stop, trail, fi_list):
        cells, dds, ntr = [], [], 0
        for fi in fi_list:
            a, b = bounds[fi]
            for s in coins:
                o, h, l, c, at, tg = cache[s]
                r = simulate(base_name, s, o, h, l, c, at, tg, stop, trail,
                             risk_pct=risk, start_i=a, end_i=b)
                cells.append(r.ret_pct)
                dds.append(r.maxdd_pct)
                ntr += r.trades
        return (float(np.median(cells)), float(np.mean(cells)),
                sum(1 for x in cells if x > 0) / len(cells) * 100,
                float(np.median(dds)), ntr)

    rows = []
    for st in stops:
        for tr in trails:
            a1 = ev(st, tr, [0, 1, 2])
            b1 = ev(st, tr, [3, 4])
            rows.append((st, tr, a1, b1))
    rows.sort(key=lambda x: -x[2][0])
    print(f"\n{base_name} — stop/trail izgarasi · risk %{risk*100:g} · "
          f"kaldirac tavani {LEVERAGE:g}x")
    print(f"{'STOP':>5}{'TRAIL':>6} | {'KESIF med':>10}{'ort':>7}{'kar%':>7}"
          f"{'dd':>6}{'islem':>7} | {'DOGR med':>10}{'ort':>7}{'kar%':>7}"
          f"{'dd':>6}{'islem':>7}")
    print("-" * 92)
    for st, tr, a1, b1 in rows:
        print(f"{st:>5.1f}{tr:>6.1f} | {a1[0]:>10.2f}{a1[1]:>7.2f}"
              f"{a1[2]:>6.0f}%{a1[3]:>6.1f}{a1[4]:>7} | "
              f"{b1[0]:>10.2f}{b1[1]:>7.2f}{b1[2]:>6.0f}%{b1[3]:>6.1f}{b1[4]:>7}")


def _target_boll_regime(h, l, c, v, btc_c, mode: str,
                        n: int = 40, mult: float = 2.0,
                        vol_mult: float = 1.2) -> np.ndarray:
    """Bollinger kirilimi + BTC rejimi / BTC'ye gore goreceli guc."""
    mid = ind.sma(c, n)
    sd = rolling_std(c, n)
    up = mid + mult * sd
    dn = mid - mult * sd
    e = ind.ema(c, 200)
    vma = ind.rolling_mean(v, 20)
    if mode in ("btc", "both"):
        bema = ind.ema(btc_c, 200)
        long_ok = btc_c > bema
        short_ok = btc_c < bema
    else:
        long_ok = np.ones(c.size, dtype=bool)
        short_ok = np.ones(c.size, dtype=bool)
    if mode in ("rs", "both"):
        ratio = c / btc_c
        rema = ind.ema(ratio, 50)
        long_ok = long_ok & (ratio > rema)
        short_ok = short_ok & (ratio < rema)
    out = np.zeros(c.size)
    state = 0
    for i in range(1, c.size):
        okv = np.isfinite(vma[i]) and v[i] >= vol_mult * vma[i]
        if state == 0:
            if okv and np.isfinite(up[i]) and c[i] > up[i] and c[i] > e[i] \
                    and long_ok[i]:
                state = 1
            elif okv and np.isfinite(dn[i]) and c[i] < dn[i] and c[i] < e[i] \
                    and short_ok[i]:
                state = -1
        elif state == 1:
            if c[i] < mid[i]:
                state = 0
        else:
            if c[i] > mid[i]:
                state = 0
        out[i] = state
    return out


def test_regime(risk: float = 0.02) -> None:
    """BTC rejimi ve goreceli guc filtrelerini iki kumede olcer."""
    fetch_all(HOLDOUT)
    btc = load("BTCUSDT")
    hold = [s for s in HOLDOUT
            if len(load(s)["c"]) >= max(700, int(BARS * 0.7))]
    variants = [("boll_vol", "none"), ("boll_btc", "btc"),
                ("boll_rs", "rs"), ("boll_btc_rs", "both")]
    print(f"\nRISK %{risk*100:g} · BTC rejim / goreceli guc testi")
    print(f"{'KUME':<10}{'VARYANT':<14}{'med%':>8}{'ort%':>8}{'kar%':>7}"
          f"{'pf':>7}{'islem':>8}")
    print("-" * 64)
    for label, coins in (("SECIM", COINS), ("HOLDOUT", hold)):
        for vname, mode in variants:
            cells, pfs, ntr = [], [], 0
            for s in coins:
                d = load(s)
                o, h, l, c, v = d["o"], d["h"], d["l"], d["c"], d["v"]
                at = atr(h, l, c, 14)
                bc = btc["c"][-len(c):]          # ayni grid varsayimi
                tg = _target_boll_regime(h, l, c, v, bc, mode)
                for a, b in fold_bounds(len(c), 5):
                    r = simulate(vname, s, o, h, l, c, at, tg, 2.0, 3.0,
                                 risk_pct=risk, start_i=a, end_i=b)
                    cells.append(r.ret_pct)
                    if np.isfinite(r.profit_factor):
                        pfs.append(r.profit_factor)
                    ntr += r.trades
            print(f"{label:<10}{vname:<14}{np.median(cells):>8.2f}"
                  f"{np.mean(cells):>8.2f}"
                  f"{sum(x > 0 for x in cells)/len(cells)*100:>6.0f}%"
                  f"{np.median(pfs):>7.2f}{ntr:>8}")


def cross(risk: float = 0.02, folds: int = 5,
          only: Optional[list[str]] = None) -> None:
    """
    Her adayi IKI BAGIMSIZ coin kumesinde kosar.

    Gercek edge'in tek kaniti: aday HER IKI kumede de pozitif olmali.
    Yalnizca secim kumesinde iyi olan = asiri uyum (overfit).
    """
    fetch_all(HOLDOUT)
    hold = [s for s in HOLDOUT
            if len(load(s)["c"]) >= max(700, int(BARS * 0.7))]
    a = run_folds(COINS, list(range(folds)), folds=folds, risk_pct=risk,
                  only=only)
    b = run_folds(hold, list(range(folds)), folds=folds, risk_pct=risk,
                  only=only)
    bm = {r["name"]: r for r in b["rows"]}
    rows = []
    for r in a["rows"]:
        o = bm.get(r["name"], {})
        rows.append((r["name"], r["med"], r["pos"], r["pf"],
                     o.get("med", 0.0), o.get("pos", 0.0), o.get("pf", 0.0),
                     o.get("trades", 0)))
    rows.sort(key=lambda x: -min(x[1], x[4]))
    print(f"\nIKI BAGIMSIZ KUME · risk %{risk*100:g} · {folds} fold · "
          f"kaldirac tavani {LEVERAGE:g}x")
    print(f"{'ADAY':<24}| {'SECIM med':>10}{'kar%':>7}{'pf':>6} | "
          f"{'HOLDOUT med':>12}{'kar%':>7}{'pf':>6}")
    print("-" * 82)
    for n, m1, p1, f1, m2, p2, f2, tr in rows[:30]:
        print(f"{n:<24}| {m1:>10.2f}{p1:>6.0f}%{f1:>6.2f} | "
              f"{m2:>12.2f}{p2:>6.0f}%{f2:>6.2f}")
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    with open(os.path.join(RESEARCH_DIR, "cross.json"), "w",
              encoding="utf-8") as f:
        json.dump([{"name": n, "sel_med": m1, "sel_pos": p1, "sel_pf": f1,
                    "hold_med": m2, "hold_pos": p2, "hold_pf": f2}
                   for n, m1, p1, f1, m2, p2, f2, tr in rows], f,
                  ensure_ascii=False, indent=1)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "fetch":
        print("Veri indiriliyor...")
        fetch_all()
        return
    if cmd == "scan":
        out = run(COINS)
        os.makedirs(RESEARCH_DIR, exist_ok=True)
        with open(os.path.join(RESEARCH_DIR, "scan.json"), "w",
                  encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"\nYazildi: {os.path.join(RESEARCH_DIR, 'scan.json')}")
        return
    if cmd == "folds":
        risk = float(sys.argv[2]) if len(sys.argv) > 2 else 0.01
        lev = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
        tr = run_folds(COINS, [0, 1, 2], risk_pct=risk, leverage=lev)
        print_rows(tr["rows"], f"KESIF (fold 1-3 · risk %{risk*100:g} · "
                               f"tavan {lev:g}x)")
        top = [r["name"] for r in tr["rows"][:15]]
        te = run_folds(COINS, [3, 4], risk_pct=risk, leverage=lev, only=top)
        print_rows(te["rows"], "DOGRULAMA — secimde KULLANILMADI (fold 4-5)")
        os.makedirs(RESEARCH_DIR, exist_ok=True)
        with open(os.path.join(RESEARCH_DIR, f"folds_{risk:g}_{lev:g}.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"train": tr["rows"], "test": te["rows"]}, f,
                      ensure_ascii=False, indent=1)
        return
    if cmd == "holdout":
        fetch_all(HOLDOUT)
        names = sys.argv[2:] or [
            "bollf_40_2.5_voladx", "bollf_40_2.5_adx", "bollf_40_2.5_vol",
            "boll_40_2.5", "boll_40_2",
        ]
        ok = [s for s in HOLDOUT if len(load(s)["c"]) >= 1500]
        print(f"\nHoldout coinler ({len(ok)}): {', '.join(ok)}")
        print("bar sayilari: " + "  ".join(
            f"{s.replace('USDT','')}={len(load(s)['c'])}" for s in ok))
        tr = run_folds(ok, [0, 1, 2], risk_pct=0.02, only=names)
        print_rows(tr["rows"], "HOLDOUT · kesif yarisi")
        te = run_folds(ok, [3, 4], risk_pct=0.02, only=names)
        print_rows(te["rows"], "HOLDOUT · dogrulama yarisi")
        return
    if cmd == "daily":
        global INTERVAL, BARS
        INTERVAL = "1d"
        BARS = 1200
        names = sys.argv[2:] or [
            "donchian_55_10_ema200", "donchian_40_20_ema200",
            "emacross_50_200_ema0", "emacross_50_200_ema200",
            "supertrend_10_3", "supertrend_14_2", "mom_40_0_ema200",
            "boll_40_2", "bollf_40_2_vol",
        ]
        fetch_all()
        fetch_all(HOLDOUT)
        cross(risk=0.02, folds=4, only=names)
        return
    if cmd == "regime":
        risk = float(sys.argv[2]) if len(sys.argv) > 2 else 0.02
        test_regime(risk)
        return
    if cmd == "cross":
        risk = float(sys.argv[2]) if len(sys.argv) > 2 else 0.02
        cross(risk)
        return
    if cmd == "tune":
        name = sys.argv[2] if len(sys.argv) > 2 else "boll_40_2.5"
        risk = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
        tune(name, COINS, risk=risk)
        return
    if cmd == "validate":
        names = sys.argv[2:] or [
            "donchian_55_20_ema200", "supertrend_10_3",
            "rsi_mr_30_65", "pullback_45_65",
        ]
        validate(names, COINS)
        return
    print("Bilinmeyen komut. fetch | scan | validate")


if __name__ == "__main__":
    main()

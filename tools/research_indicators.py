"""
Gosterge arastirmasi — hangi osilator/MA en iyi LONG/SAT noktasini bulur?

YONTEM
------
1) VERI: 18 coin x 3 zaman dilimi, 500 mum her biri (onbelleklenir).
2) HER GOSTERGE icin bar basina sinyal dizisi (-1/0/+1).
   Kurallar analysis.py ile AYNI — boylece "uygulamada gercekten ne
   oluyor" olculur.
3) IKI METRIK (birlikte okunur):

   HAM EDGE (%)  Sinyal yonune gore 8-bar ileri getiri ortalamasi.
                 Yaniltir: piyasa genel yonu bunu tasir.
                 Ornek: yukselen piyasada "AL" diyen her gosterge
                 pozitif edge cikar.

   BILGI KATSAYISI (IC)
                 Sinyal yonu ile fiyat yonunun korelasyonu:
                     IC = ort(sinyal_i * isaret(f_i))
                 -1..+1 arasi; 0 = piyasadan bagimsiz bilgi YOK.
                 Bu, "gosterge gercekten bir sey biliyor mu" olcumu.

   IC olmadan ham edge ranklamasi YANLIS sonuc verir (olculdu).

4) KORELASYON: ayni barda ayni yonu soyleme orani.
5) SECIM: greedy ileri secim, in-sample secim + out-of-sample dogrulama.

    python tools/research_indicators.py --collect
    python tools/research_indicators.py --report
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                   # noqa: E402

import config                                        # noqa: E402
from core import indicators as ind                   # noqa: E402
from core.binance_client import BinanceFuturesClient  # noqa: E402

CACHE = os.path.join(config.DATA_DIR, "research_cache.pkl")

COINLER = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
           "BCHUSDT", "SUIUSDT", "NEARUSDT", "TRUMPUSDT", "APTUSDT",
           "ATOMUSDT", "XMRUSDT", "HBARUSDT"]

HORIZON = 8          # kac bar sonra getiri olculsun
MA_DZ = 0.0002
ICH_DZ = 0.0025


# ----------------------------------------------------------------------
def _cross_up(a, b):
    return (np.roll(a, 1) <= np.roll(b, 1)) & (a > b)


def _cross_dn(a, b):
    return (np.roll(a, 1) >= np.roll(b, 1)) & (a < b)


def _over(a, b):
    out = np.zeros(a.size, dtype=int)
    out[_cross_up(a, b)] = 1
    out[_cross_dn(a, b)] = -1
    out[~np.isfinite(a)] = 0
    out[0] = 0
    return out


def _sgn(x, buy, sell):
    out = np.zeros(x.size, dtype=int)
    ok = np.isfinite(x)
    out[ok & (x >= buy)] = 1
    out[ok & (x <= sell)] = -1
    out[0] = 0
    return out


def _ma_v(c, ma, dz):
    out = np.zeros(c.size, dtype=int)
    with np.errstate(invalid="ignore"):
        up = c > ma * (1.0 + dz)
        dn = c < ma * (1.0 - dz)
    out[up & np.isfinite(ma)] = 1
    out[dn & np.isfinite(ma)] = -1
    return out


def build_signals(c, h, l, v):
    """(ad, sinyal dizisi) listesi — 26 gosterge."""
    r = ind.rsi(c, 14)
    stoch = ind.stochastic_k(h, l, c, 14, 3)
    stoch_d = ind.rolling_mean(stoch, 3)
    cci_v = ind.cci(h, l, c, 20)
    adx_l, _, _ = ind.adx(h, l, c, 14)
    ao = ind.awesome_oscillator(h, l)
    mom = ind.momentum(c, 10)
    macd_l, macd_s, _ = ind.macd(c, 12, 26, 9)
    srsi = ind.stoch_rsi_fast(c, 14, 14, 3, 3)
    srsi_d = ind.rolling_mean(srsi, 3)
    wr = ind.williams_r(h, l, c, 14)
    bull, bear = ind.bull_bear_power(h, l, c, 13)
    uo = ind.ultimate_oscillator(h, l, c, 7, 14, 28)

    out = [
        ("RSI(14)", _sgn(r, 70, 30)),
        ("Stokastik %K", _over(stoch, stoch_d)),
        ("CCI(20)", _sgn(cci_v, 100, -100)),
        ("ADX(14)", _over(adx_l, np.full(adx_l.size, 25.0))),
        ("Müthiş Osilatör", _over(ao, np.zeros(ao.size))),
        ("Momentum(10)", _sgn(mom, 0, 0)),
        ("MACD(12,26)", _sgn(macd_l - macd_s, 0, 0)),
        ("Stokastik RSI", _over(srsi, srsi_d)),
    ]

    w = np.zeros(wr.size, dtype=int)
    pw = np.roll(wr, 1)
    w[(pw <= -80) & (wr > -80)] = 1
    w[(pw >= -20) & (wr < -20)] = -1
    w[~np.isfinite(wr)] = 0
    out.append(("Williams %R", w))

    bb = np.zeros(c.size, dtype=int)
    pb, pr = np.roll(bull, 1), np.roll(bear, 1)
    bb[(pb <= 0) & (bull > 0)] = 1
    bb[(pr >= 0) & (bear < 0)] = -1
    bb[~np.isfinite(bull)] = 0
    out.append(("Boğa Ayı Gücü", bb))
    out.append(("Nihai Osilatör", _sgn(uo, 70, 30)))

    for p in (10, 20, 30, 50, 100, 200):
        out.append((f"EMA({p})", _ma_v(c, ind.ema(c, p), MA_DZ)))
        out.append((f"SMA({p})", _ma_v(c, ind.sma(c, p), MA_DZ)))
    out.append(("İchimoku Ana Hat",
                _ma_v(c, ind.ichimoku_base_line(h, l), ICH_DZ)))
    out.append(("VWMA(20)", _ma_v(c, ind.vwma(c, v, 20), MA_DZ)))
    out.append(("HMA(9)", _ma_v(c, ind.hma(c, 9), MA_DZ)))
    return out


def fwd_return(c: np.ndarray, horizon: int = HORIZON) -> np.ndarray:
    f = np.full(c.size, np.nan)
    if c.size > horizon:
        f[:c.size - horizon] = (c[horizon:] - c[:-horizon]) / c[:-horizon]
    return f


def collect() -> dict:
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    veri: dict = {}
    for sym in COINLER:
        for tf in config.TIMEFRAMES:
            try:
                c = BinanceFuturesClient(sym)
                k = c.fetch_klines(tf, config.CANDLE_LIMIT)
                veri[(sym, tf)] = {
                    "o": np.array([x.open for x in k]),
                    "h": np.array([x.high for x in k]),
                    "l": np.array([x.low for x in k]),
                    "c": np.array([x.close for x in k]),
                    "v": np.array([x.volume for x in k]),
                }
            except Exception as exc:                  # noqa: BLE001
                print(f"  {sym}/{tf} ATLANDI: {exc}")
    with open(CACHE, "wb") as f:
        pickle.dump(veri, f)
    print(f"onbellek yazildi: {len(veri)} dizi -> {CACHE}")
    return veri


def hazirla(veri: dict):
    paketler = []
    adlar = None
    for (sym, tf), d in veri.items():
        c, h, l, v = d["c"], d["h"], d["l"], d["v"]
        if not np.isfinite(c).all() or (c <= 0).any():
            continue
        sig = build_signals(c, h, l, v)
        if adlar is None:
            adlar = [a for a, _ in sig]
        M = np.vstack([s for _, s in sig]).T.astype(np.int8)
        paketler.append({"sym": sym, "tf": tf, "M": M, "c": c,
                         "fwd": fwd_return(c), "sgf": np.sign(fwd_return(c))})
    return adlar, paketler


def olcum(paketler, cols, split: float):
    """(edge %, hit %, IC, n). IC = bilgi katsayisi."""
    net = hit = n = ic_t = 0.0
    for p in paketler:
        s = p["M"][:, cols].mean(axis=1) if len(cols) > 1 else p["M"][:, cols[0]]
        f, sgf = p["fwd"], p["sgf"]
        k = int(len(s) * split)
        s, f, sgf = s[:k], f[:k], sgf[:k]
        m = (s != 0) & np.isfinite(f)
        if not m.any():
            continue
        yonlu = np.where(s[m] > 0, f[m], -f[m])
        net += yonlu.sum()
        hit += (yonlu > 0).sum()
        ic_t += (np.sign(s[m]) * sgf[m]).sum()
        n += len(yonlu)
    if n == 0:
        return 0.0, 0.0, 0.0, 0
    return net / n * 100.0, hit / n * 100.0, ic_t / n, int(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    veri = collect()
    if not args.report:
        return 0

    adlar, paketler = hazirla(veri)
    print()
    print("=" * 84)
    print(f"VERI: {len(paketler)} dizi · {len(adlar)} gosterge · "
          f"{HORIZON}-bar ileri ufuk")
    print("=" * 84)

    # ---------- 1) TEK GOSTERGE ----------
    print()
    print("1) TEK GOSTERGE — BILGI KATSAYISI (IC) sirasiyla")
    print("   IC = sinyal yonu ile fiyat yonunun uyumu. 0 = bilgi yok.")
    print("%-24s %8s %10s %10s %8s" %
          ("GOSTERGE", "IC", "EDGE %", "ISABET %", "ADET"))
    print("-" * 64)
    tek = []
    for i, ad in enumerate(adlar):
        e, h, ic, n = olcum(paketler, [i], 0.70)
        tek.append((ad, ic, e, h, n))
    tek.sort(key=lambda r: -abs(r[1]))
    for ad, ic, e, h, n in tek:
        y = "  <== GUVCLU" if abs(ic) >= 0.10 else ""
        print("%-24s %8.4f %9.3f%% %9.1f%% %8d%s" % (ad, ic, e, h, n, y))

    print()
    print("2) Ayni olcum ama OUT-OF-SAMPLE (son %30) — genelleniyor mu?")
    print("%-24s %8s %8s" % ("GOSTERGE", "IC(IS)", "IC(OOS)"))
    print("-" * 44)
    for ad, ic, e, h, n in tek[:12]:
        idx = adlar.index(ad)
        _, _, ic_oos, _ = olcum(paketler, [idx], 1.0)
        # OOS = tum veriden cikarilip sadece son %30
        net = ic_t = cnt = 0.0
        for p in paketler:
            s = p["M"][:, idx]
            sgf = p["sgf"]
            k = int(len(s) * 0.70)
            s2, g2 = s[k:], sgf[k:]
            m = (s2 != 0) & np.isfinite(g2)
            if not m.any():
                continue
            ic_t += (np.sign(s2[m]) * g2[m]).sum()
            cnt += len(s2[m])
        ic_oos = ic_t / cnt if cnt else 0.0
        print("%-24s %8.4f %8.4f" % (ad, ic, ic_oos))

    with open(os.path.join(config.DATA_DIR, "research_single.pkl"), "wb") as f:
        pickle.dump({"adlar": adlar, "tek": tek}, f)

    # ---------- 3) KORELASYON ----------
    print()
    print("3) KORELASYON — ikisi ne kadar sik ayni yonu soyluyor?")
    print("   (Yuksek = birbirinin yerine gecer, birlikte eklemek mantiksiz)")
    print()
    en_yuksek = []
    for i in range(len(adlar)):
        for j in range(i + 1, len(adlar)):
            a = tot = 0
            for p in paketler:
                s = p["M"][:, i]
                t = p["M"][:, j]
                m = (s != 0) & (t != 0)
                if not m.any():
                    continue
                a += (s[m] == t[m]).sum()
                tot += len(s[m])
            if tot > 800:
                en_yuksek.append((adlar[i], adlar[j], a / tot * 100, tot))
    en_yuksek.sort(key=lambda r: -r[2])
    print("%-22s %-22s %9s %9s" % ("A", "B", "UYUM %", "ORTAK BAR"))
    print("-" * 64)
    for x, y, p, n in en_yuksek[:12]:
        print("%-22s %-22s %8.1f%% %9d" % (x, y, p, n))
    print()
    en_dusuk = sorted(en_yuksek, key=lambda r: r[2])[:8]
    print("EN DUSUK uyum (tamamen farkli konusuyorlar → birlikte degerli olabilir):")
    for x, y, p, n in en_dusuk:
        print("  %-22s %-22s %8.1f%%  (n=%d)" % (x, y, p, n))

    # ---------- 4) KOMBINASYON ARAMASI ----------
    print()
    print("4) KOMBINASYON — greedy ileri secim (in-sample %70)")
    print("   Her adimda mevcut kume en iyi eklenir. Hedef: |IC| maks.")
    print()
    # in-sample IC fonksiyonu
    def ic_is(cols):
        _, _, ic, _ = olcum(paketler, cols, 0.70)
        return abs(ic)

    secim: list[int] = []
    gecen = [tek[0][1]] * 0
    print("%-3s %-46s %8s" % ("ADIM", "KUME", "IC(IS)"))
    print("-" * 60)
    for adim in range(1, 8):
        en_iyi = None
        for i in range(len(adlar)):
            if i in secim:
                continue
            d = ic_is(secim + [i])
            if en_iyi is None or d > en_iyi[0]:
                en_iyi = (d, i)
        if en_iyi is None:
            break
        secim.append(en_iyi[1])
        print("%-3d %-46s %8.4f" %
              (adim, ", ".join(adlar[i] for i in secim), en_iyi[0]))

    # secimin OOS dogrulamasi
    def ic_aralik(cols, lo, hi):
        net = cnt = 0.0
        for p in paketler:
            s = p["M"][:, cols].mean(axis=1)
            sgf = p["sgf"]
            k = int(len(s) * lo)
            s2, g2 = s[k:int(len(s) * hi)], sgf[k:int(len(s) * hi)]
            m = (s2 != 0) & np.isfinite(g2)
            if not m.any():
                continue
            net += (np.sign(s2[m]) * g2[m]).sum()
            cnt += len(s2[m])
        return net / cnt if cnt else 0.0

    print()
    print("OOS DOGRULAMA (son %30) — asiri uyum kontrolu")
    print("%-46s %8s %8s" % ("KUME", "IC(IS)", "IC(OOS)"))
    print("-" * 64)
    tek_sira = sorted(range(len(adlar)), key=lambda i: -abs(tek[i][1]))
    adaylar = [([i], f"tek: {adlar[i]}") for i in tek_sira[:5]]
    for k in (2, 3, 4, 5):
        adaylar.append((secim[:k], f"greedy ilk {k}"))
    # sinyallerin TERSI de aday (IC negatifse yon terse cevir)
    adaylar.append(([tek_sira[0]], f"tek ters: {adlar[tek_sira[0]]}"))
    for cols, ad in adaylar:
        print("%-46s %8.4f %8.4f" %
              (ad, ic_aralik(cols, 0, 0.70), ic_aralik(cols, 0.70, 1.0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
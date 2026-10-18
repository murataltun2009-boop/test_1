"""
Coin listesini OLÇEREK günceller — tahminle değil.

Bu araç, Binance Futures'un canlı verisinden en çok işlem gören
USDT perpetual sözleşmelerini seçer ve `config.py` icindeki SYMBOLS
satirlarini yeniden yazar.

    python tools/update_symbols.py            # sadece goster
    python tools/update_symbols.py --write    # config.py'yi guncelle

OLCUTLER (hepsi olculebilir, zevke gore degil)
------------------------------------------------
1. USDT perpetual + durum TRADING          (vadeli piyasa, spot degil)
2. 24 saatlik islem hacmi >= MIN_VOLUME    (likidite -> kayma yok)
3. Listelenme yasi >= MIN_AGE_AY           (gosterge icin yeterli gecmis:
                                            4h x 500 bar = ~83 gun)
4. 30 GUNLUK medyan |gunluk degisim| <= %6
5. 30 GUNLUK en buyuk gunluk degisim <= %35
6. Kaldiracli token'ler haric (UP/DOWN/BULL/BEAR son ekleri)
7. Stabil para ciftleri haric (USDC, FDUSD, ...)

NEDEN 4 ve 5? — Bu uygulamanin karar mekanizmasi ARALIKTAN yararlaniyor
("fiyat pencerenin tabaninda" / "zirve"). Bir coin 30 gunde bir kez %50
zipliyorsa aralik olusmuyor demektir; mumlar araligi parcaliyor, taban/
zirve testi anlamsizlasiyor ve simule kâr rastgele cikiyor.
Tek gunluk %3 ziplama sorun DEGIL (BTC'de olur); sorun %50+ ani hareket.

OLCUM SONUCU (2026-10-18): 47 adaydan 36 gecti.
Dusenler: AGT, Q, QNT, ZEREBRO, GTC, SAND, STRK, ARIA, ICNT, APR, BR.

NOT — 1000PEPE: Binance PEPE'yi fiyatinin 1000 kati ile
"1000PEPEUSDT" sozlesmesi olarak fiyatlıyor; ayri bir varlik degil.
Listede oldugu icin uygulama fiyati ~0,0039 olarak gosterir.

ISTISNA TAVANI
--------------
Hacim esigi tek basina "yeni ve olgunlasti ama sirada kalan" coinleri
disarida birakir (or. TRX 25M, ICP 17M, ETC 16M). Proje eklemek icin
EXTRA_SYMBOLS listesine yazmak yeterlidir; hacim filtresi uygulanmaz.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MIN_VOLUME = 45_000_000.0     # 24 saatlik asgari hacim (USD)
MIN_AGE_AY = 6.0              # listelenme yasi
MAX_MEDIAN_MOVE = 6.0         # 30 günlük medyan |günlük değişim| (%)
MAX_DAILY_MOVE = 35.0         # 30 günlük en büyük günlük değişim (%)
HIDE_CAT = ("USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "AEUR", "USDS")

# Hacim esiginin disinda kalsa da projede tutulmasi istenenler.
EXTRA_SYMBOLS: list[str] = []


def get(url: str):
    with urllib.request.urlopen(url, timeout=40) as r:
        return json.loads(r.read().decode())


def daily_moves(symbol: str) -> tuple[float, float]:
    """Son 30 gun icin (medyan |gunluk degisim|, en buyuk) — yuzde."""
    import statistics
    try:
        k = get("https://fapi.binance.com/fapi/v1/klines"
                f"?symbol={symbol}&interval=1d&limit=31")
    except Exception:      # noqa: BLE001
        return (999.0, 999.0)
    closes = [float(x[4]) for x in k]
    rets = [abs((closes[i] - closes[i - 1]) / closes[i - 1]) * 100.0
            for i in range(1, len(closes)) if closes[i - 1] > 0]
    if not rets:
        return (999.0, 999.0)
    return (statistics.median(rets), max(rets))


def collect(verbose: bool = False) -> list[dict]:
    tickers = get("https://fapi.binance.com/fapi/v1/ticker/24hr")
    info = {s["symbol"]: s
            for s in get("https://fapi.binance.com/fapi/v1/exchangeInfo")["symbols"]}
    now = datetime.datetime.now(datetime.UTC)
    rows: list[dict] = []

    for t in tickers:
        s = t["symbol"]
        if not s.endswith("USDT") or s not in info:
            continue
        st = info[s]
        if st.get("contractType") != "PERPETUAL" or st.get("status") != "TRADING":
            continue

        base = s[:-4]
        if any(base.endswith(x) for x in ("UP", "DOWN", "BULL", "BEAR")):
            continue
        if base in HIDE_CAT or base.startswith("1000X"):
            continue

        vol = float(t.get("quoteVolume") or 0.0)
        onboard = st.get("onboardDate") or 0
        age = ((now - datetime.datetime.fromtimestamp(onboard / 1000, datetime.UTC))
               .days / 30.4) if onboard else -1.0

        if vol < MIN_VOLUME or age < MIN_AGE_AY:
            continue

        med, mx = daily_moves(s)
        if med > MAX_MEDIAN_MOVE or mx > MAX_DAILY_MOVE:
            if verbose:
                why = []
                if med > MAX_MEDIAN_MOVE:
                    why.append(f"medyan %{med:.1f}")
                if mx > MAX_DAILY_MOVE:
                    why.append(f"tek gunde %{mx:.0f}")
                print(f"  elendi {s:<16} {' + '.join(why)}")
            continue

        rows.append({
            "symbol": s, "volume": vol,
            "change": float(t.get("priceChangePercent") or 0.0),
            "age": age, "trades": int(t.get("count") or 0),
            "price": t.get("lastPrice", "?"),
            "med": med, "max": mx,
        })

    rows.sort(key=lambda r: -r["volume"])

    for s in EXTRA_SYMBOLS:
        if not any(c["symbol"] == s for c in rows):
            src = next((r for r in rows if r["symbol"] == s), None)
            if src:
                rows.append(src)
                rows.sort(key=lambda r: -r["volume"])
    return rows


def write_config(rows: list[dict]) -> None:
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config.py")
    text = open(path, encoding="utf-8").read()

    body = "\n".join(f'    "{r["symbol"]}",' for r in rows)
    new_block = "SYMBOLS: list[str] = [\n" + body + "\n]"
    text2, n = re.subn(r"SYMBOLS: list\[str\] = \[.*?\]",
                       new_block, text, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("HATA: config.py icinde SYMBOLS bulunamadi.")
    open(path, "w", encoding="utf-8").write(text2)
    print(f"\nconfig.py guncellendi: {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="config.py'yi yaz")
    args = ap.parse_args()

    rows = collect(verbose=True)
    print(f"\nSecilen coin sayisi : {len(rows)}")
    print(f"Olcutler           : hacim >= {MIN_VOLUME:,.0f} USD, "
          f"yas >= {MIN_AGE_AY} ay, medyan <= %{MAX_MEDIAN_MOVE:.0f}, "
          f"tepe <= %{MAX_DAILY_MOVE:.0f}\n")
    print("%-16s %14s %9s %8s %9s %9s" %
          ("SEMBOL", "24H HACIM($)", "%DEGIS", "YAS(ay)", "30G MED", "30G MAX"))
    print("-" * 72)
    for r in rows:
        print("%-16s %14.0f %8.2f%% %8.0f %8.2f%% %8.1f%%" %
              (r["symbol"], r["volume"], r["change"], r["age"],
               r["med"], r["max"]))

    if args.write:
        write_config(rows)
    else:
        print("\n(Yazmadi. Guncelemek icin: python tools/update_symbols.py --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
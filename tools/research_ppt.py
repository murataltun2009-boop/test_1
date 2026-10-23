"""
PPT (Pivot Point Supertrend) parametre taramasi — olcumlu oneri.
Uretim motorunun KENDISINI kullanir (PaperTrader.backtest, mode="ppt").

Taranan eksenler (AL/SAT esigi karsiliginda):
  mult     : bant genisligi (BUYUK = daha az ama daha guvenli sinyal)
  pull_atr : optimum nokta filtresi (tepeye yakin AL -> bekle)
  period   : pivot donemi
  stop_atr : giris stopu; trail = stop x 5/3

Calistirma:
  python tools/research_ppt.py      -> genis tarama (tum modlar)
  python tools/research_ppt.py p2   -> dar tarama + Supertrend taban cizgisi
"""
from __future__ import annotations

import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as cfg


def fetch(symbol: str, interval: str, total: int = 1500):
    url = f"{cfg.FAPI_REST}/fapi/v1/klines"
    out = []
    end = None
    while len(out) < total:
        take = min(1500, total - len(out))
        params = {"symbol": symbol, "interval": interval, "limit": take}
        if end is not None:
            params["endTime"] = end
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out = rows + out
        end = rows[0][0] - 1
    return out


def to_candles(rows):
    from core.binance_client import candle_from_payload
    out = []
    for r in rows:
        c = candle_from_payload(r)
        c.closed = True
        out.append(c)
    return out


def run(candles, tf, mode="ppt", **ppt):
    from core.paper import PaperTrader
    lock = ppt.pop("lock", None)
    p = PaperTrader(cfg.Settings())
    p.configure(balance=1000.0, leverage=10, fee_rate=0.0005,
                wallet_fraction=0.8, mode=mode, risk_pct=0.03)
    for k, v in ppt.items():
        setattr(p, f"mode_ppt_{k}", v)
    if lock is not None:
        p.trend_lock_pct = float(lock)
    p.running = True
    p.start_balance = 1000.0
    p.balance = 1000.0
    return p.backtest(candles, tf)


def show(label, bt):
    n = bt["trades"]
    wins = bt["wins"]
    wr = (100.0 * wins / n) if n else 0.0
    print(f"{label:>26} | {n:>5} islem | {bt['profit']:>8.2f}$ "
          f"{bt['return_pct']:>7.2f}% | kazan {wr:>5.1f}% ({wins}/{n})")


def _path(sym, itv, total):
    import config as cfg
    d = os.path.join(cfg.DATA_DIR, "research")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "ppt_datas.json")


def jobs():
    """Her koini bir kez ceker, lokal dosyaya cache'ler (DNS cokumlerine dayanikli)."""
    import json
    import config as cfg
    path = _path(None, None, None)
    cache = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:      # noqa: BLE001
            cache = {}
    out = []
    specs = [(f"{s} 5m x1500 (~5 gun)", s, "5m", 1500) for s in
             ("BTCUSDT", "ETHUSDT", "SOLUSDT")]
    specs.append(("BTCUSDT 1h x1500 (~2 ay)", "BTCUSDT", "1h", 1500))
    for name, sym, itv, total in specs:
        key = f"{sym}:{itv}:{total}"
        if key in cache:
            rows = cache[key]
        else:
            rows = fetch(sym, itv, total)
            cache[key] = rows
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cache, f)
        out.append((name, to_candles(rows), itv))
    return out


def pass1():
    for name, cdl, tf in jobs():
        print(f"\n############ {name} ############")
        for mult in (2.0, 2.5, 3.0, 3.5, 4.0):
            for pull in (0.0, 0.5, 1.0):
                bt = run(cdl, tf, mult=mult, pull_atr=pull,
                         stop_atr=3.0, trail_atr=5.0)
                show(f"mult={mult} pull={pull} s=3", bt)
        for stop in (2.0, 4.0):
            bt = run(cdl, tf, mult=3.0, pull_atr=0.0,
                     stop_atr=stop, trail_atr=round(stop * 5 / 3, 1))
            show(f"mult=3 pull=off s={stop}", bt)


def pass2():
    for name, cdl, tf in jobs():
        print(f"\n############ {name} ############")
        for period in (10, 14, 20):
            for mult in (3.0, 3.5, 4.0):
                for pull in (0.5, 1.0):
                    bt = run(cdl, tf, period=period, mult=mult,
                             pull_atr=pull, pull_bars=20,
                             stop_atr=3.0, trail_atr=5.0)
                    show(f"P={period} m={mult} pull={pull}", bt)
        # Taban cizgisi: ayni motor, klasik Supertrend modu.
        bt = run(cdl, tf, mode="trend", period=10, mult=3.0)
        show("TABAN: Supertrend(10,3)", bt)


def pass3():
    """Butunlesme: stop/trail izolasyonu + lock/kar kilidi esigi."""
    for name, cdl, tf in jobs():
        print(f"\n############ {name} ############")
        for stop, trail in ((3.0, 5.0), (4.0, 5.0), (4.0, 6.5), (5.0, 6.0)):
            bt = run(cdl, tf, period=10, mult=3.5, pull_atr=1.0,
                     stop_atr=stop, trail_atr=trail)
            show(f"s={stop} tr={trail}", bt)
        for pull in (0.75, 1.0, 1.25):
            bt = run(cdl, tf, period=10, mult=3.5, pull_atr=pull,
                     stop_atr=3.0, trail_atr=5.0)
            show(f"pull={pull}", bt)
        for lock in (0.0, 0.01, 0.015, 0.02, 0.03, 0.04):
            bt = run(cdl, tf, period=10, mult=3.5, pull_atr=1.0,
                     stop_atr=3.0, trail_atr=5.0, lock=lock)
            show(f"lock={lock}", bt)


if __name__ == "__main__":
    if "p3" in sys.argv:
        pass3()
    elif "p2" in sys.argv:
        pass2()
    else:
        pass1()

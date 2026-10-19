"""
MURO algoritmasi arastirmasi.

AMAC
----
Kullanicinin istegi:
  "En iyi long ve short noktalarini yakalayan super bir algoritma bul.
   Long en dipten tespit etsin; long'da elde edilen kazanci kaybetmeden
   short'a gecsin (ornek: %3 kazanc sagladikca cuzdana atsin, yeniden
   long'a girsin); short'a zarar ederek girmesin, en optimum noktayi
   yakalasin. Bunlari test ederek MURO adinda bir algoritma olustur."

BU ARAC NE YAPAR
----------------
1) Ayni veriyi (4h / 1d, Binance Futures) kullanir.
2) MURO'yu AYNI simulatorle, gercekci maliyetlerle (komisyon %0,05,
   kayma %0,02, funding) olcer.
3) 10 secim coin + 15 holdout coin uzerinde, 4 parca zaman diliminde
   ve uygulamanin 500 bar penceresinde test eder.
4) Gecis kalitesini olcer: long->short ve short->long gecislerinde
   cycle'in NET karini raporlar ("kazanci kaybetmeden gecis" isteginin
   sayisal karsiligi).

CALISTIR
--------
    python tools/research_muro.py grid
    python tools/research_muro.py cross
    python tools/research_muro.py last500
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core import muro as M
from tools.research_algo import (COINS, HOLDOUT, FEE_RATE, SLIPPAGE,
                                 WALLET_FRACTION, START_BALANCE, WARMUP,
                                 load, atr)

RESEARCH_DIR = os.path.join(config.DATA_DIR, "research")
FUND_4H = 0.00005        # %0,01 / 8h -> 4h bar basina
FUND_1D = 0.00015        # 3 x 8h


# --------------------------------------------------------------------------
# Sonuc
# --------------------------------------------------------------------------
@dataclass
class MuroResult:
    coin: str
    ret_pct: float = 0.0
    maxdd_pct: float = 0.0
    entries: int = 0
    locks: int = 0
    wins: int = 0
    losses: int = 0
    profit_factor: float = 0.0
    liquidations: int = 0
    final_equity: float = 0.0
    avg_lev: float = 0.0
    fees: float = 0.0
    cycles: int = 0
    cycle_wins: int = 0
    cycle_pnls: list = field(default_factory=list)
    cycle_locks: list = field(default_factory=list)
    transitions: list = field(default_factory=list)
    bars: int = 0

    @property
    def cycle_win_rate(self) -> float:
        return (self.cycle_wins / self.cycles * 100) if self.cycles else 0.0

    @property
    def avg_cycle_pnl(self) -> float:
        return float(np.mean(self.cycle_pnls)) if self.cycle_pnls else 0.0

    @property
    def med_cycle_pnl(self) -> float:
        return float(np.median(self.cycle_pnls)) if self.cycle_pnls else 0.0

    @property
    def trans_count(self) -> int:
        return len(self.transitions)

    @property
    def trans_win_rate(self) -> float:
        if not self.transitions:
            return 0.0
        return sum(1 for t in self.transitions if t[2] > 0) / \
            len(self.transitions) * 100

    @property
    def trans_avg_pnl(self) -> float:
        if not self.transitions:
            return 0.0
        return float(np.mean([t[2] for t in self.transitions]))


# --------------------------------------------------------------------------
# Simulator — uygulamanin backtest motoruyla AYNI siralamayi kullanir
#   1) mevcut pozisyon: likidasyon / stop / kar kilidi (bar ici h/l)
#   2) MURO aksiyonu: kapanis @ c[j] (kayma ile)
#   3) trailing stop guncelle (c[j])
#   4) funding + equity isareti
# --------------------------------------------------------------------------
def run(symbol: str, o, h, l, c, cfg: M.MuroConfig,
        leverage: float = 10.0, wallet: float = WALLET_FRACTION,
        fee: float = FEE_RATE, slip: float = SLIPPAGE,
        funding: float = FUND_4H, risk_pct: float = 0.0,
        start_i: int = WARMUP, end_i: Optional[int] = None) -> MuroResult:
    n = c.size
    end_i = n - 1 if end_i is None else min(end_i, n - 1)
    res = MuroResult(coin=symbol, bars=max(0, end_i - start_i))

    acts = M.actions(o, h, l, c, cfg)
    a_series = atr(h, l, c, cfg.atr_n)

    eq = START_BALANCE
    peak = eq
    maxdd = 0.0
    pos = 0                # 0 / +1 (LONG) / -1 (SHORT)
    entry = qty = stop = notional = 0.0
    pos_lev = leverage
    locks = 0
    lev_sum = lev_n = 0.0
    fees_paid = 0.0
    gw = gl = 0.0
    wins = losses = 0
    liq = 0
    cycle_dir = 0
    cycle_pnl = 0.0
    cycles = 0
    cycle_wins = 0
    cycle_pnls: list[float] = []
    cycle_locks: list[int] = []      # dongudeki kâr kilitleme sayısı
    cur_locks = 0
    dir_losses = 0                   # ayni yonde art arda kayip
    transitions: list[tuple] = []
    pos_locked = False

    def close_at(price: float, reason: str) -> None:
        nonlocal eq, pos, qty, entry, notional, cycle_pnl, gw, gl
        nonlocal wins, losses, fees_paid, dir_losses
        if pos == 0:
            return
        px = price * (1 - slip) if pos == 1 else price * (1 + slip)
        gross = (px - entry) * qty * pos
        f = qty * px * fee
        eq += gross - f
        fees_paid += f
        net = gross - f
        cycle_pnl += net
        if net > 0:
            gw += net
            wins += 1
            dir_losses = 0
        else:
            gl += -net
            losses += 1
            dir_losses += 1
        pos = 0
        qty = entry = notional = 0.0

    def open_at(price: float, side: int, i: int,
                stop_dist: Optional[float] = None,
                force: bool = False) -> None:
        nonlocal eq, pos, qty, entry, stop, notional, pos_lev
        nonlocal cycle_dir, cycle_pnl, cycles, cycle_wins, lev_sum, lev_n
        nonlocal fees_paid, pos_locked, cur_locks, dir_losses
        if eq <= 1.0 or price <= 0:
            return
        # YON DEGISTI: kayip sayaci sifirlanir (aksi halde sayaç
        # kilitlenir ve hicbir islem acilmaz).
        if side != cycle_dir:
            dir_losses = 0
        # ART ARDA KAYIP KORUMASI: ayni yonde N kez kaybedildiyse o
        # yonde yeni islem ACILMAZ. Boylece "kazanci kaybetmeden gecis"
        # kurali korunur: yon degistirmeden ayni yone defalarca dalip
        # kârı eritmek engellenir.
        if (not force) and cfg.max_losses > 0 and \
                dir_losses >= cfg.max_losses:
            return
        px = price * (1 + slip) if side == 1 else price * (1 - slip)
        # --- stop ---
        if stop_dist is not None:
            # KILIT SONRASI YENI GIRIS: ayni risk mesafesi korunur
            # (basi bas seviyesi stop OLMAZ — mesafe ~0 olursa stop
            # gurultude tetiklenir ve kaldirac patlar).
            stop = px * (1 - stop_dist) if side == 1 else px * (1 + stop_dist)
        else:
            lo_seg = [float(x) for x in l[max(0, i - cfg.k):i + 1]]
            hi_seg = [float(x) for x in h[max(0, i - cfg.k):i + 1]]
            stop = M.structural_stop(side, px, lo_seg, hi_seg, cfg.k + 1, cfg)
        stop_frac = abs(px - stop) / px
        if stop_frac <= 0:
            return
        # --- pozisyon boyutu ---
        # likidasyon korumasi: stop, likidasyondan ONCE gelmeli.
        lev_eff = min(leverage, 0.6 / stop_frac) if stop_frac > 0 else leverage
        if risk_pct > 0:
            # RISK BAZLI: stop mesafesi kadar gidince sermayenin
            # risk_pct kadari gider. Kaldirac yalnizca ust sinirdir.
            notional = eq * risk_pct / stop_frac
            notional = min(notional, eq * wallet * lev_eff)
            # likidasyon stop'un 1,5 katinda (teminat = notional*liq_dist)
            liq_dist = 1.5 * stop_frac
        else:
            # TAM KULLANIM: teminat = eq*wallet, notional = teminat*lev
            notional = eq * wallet * lev_eff
            liq_dist = 1.0 / lev_eff
        if notional <= 0:
            return
        margin = notional * liq_dist
        qty = notional / px
        f = notional * fee
        eq -= f
        fees_paid += f
        entry = px
        pos = side
        pos_lev = 1.0 / liq_dist
        pos_locked = False
        lev_sum += notional / max(eq, 1e-9)
        lev_n += 1
        # --- cycle (yon dongusu) ---
        if cycle_dir != side:
            if cycle_dir != 0:
                cycles += 1
                cycle_pnls.append(cycle_pnl)
                if cycle_pnl > 0:
                    cycle_wins += 1
                transitions.append((cycle_dir, side, cycle_pnl))
            cycle_dir = side
            cycle_pnl = 0.0

    for j in range(start_i, end_i + 1):
        # ---- 1) mevcut pozisyonun bar ici kontrolu ----
        if pos != 0:
            liq_px = (entry * (1 - 1.0 / pos_lev) if pos == 1
                      else entry * (1 + 1.0 / pos_lev))
            # ONCE STOP: fiyat stop'a dogru yolunda likidasyondan ONCE
            # gelir. Likidasyon ancak stop'un ATLANDIGI (gap) durumda
            # olur. Aksi halde her stop, yanlisca likidasyon sayilir.
            hit_stop = (l[j] <= stop) if pos == 1 else (h[j] >= stop)
            hit_liq = (l[j] <= liq_px) if pos == 1 else (h[j] >= liq_px)
            if hit_stop:
                exit_px = min(stop, float(o[j])) if pos == 1 else \
                    max(stop, float(o[j]))
                if (pos == 1 and exit_px <= liq_px) or \
                        (pos == -1 and exit_px >= liq_px):
                    close_at(liq_px, "LIK")
                    liq += 1
                else:
                    close_at(exit_px, "STOP")
            elif hit_liq:
                close_at(liq_px, "LIK")
                liq += 1

            # ---- kar kilidi: %3 kazanc -> cuzdana yaz, ayni yonde gir ----
            if pos != 0:
                side = pos
                lock_px = M.lock_price(side, entry, cfg)
                hit_lock = (h[j] >= lock_px) if side == 1 else (l[j] <= lock_px)
                if hit_lock:
                    # once mevcut bacagi kapat (kazanc realize)
                    dist = abs(entry - stop) / entry if entry > 0 else cfg.stop_pct
                    close_at(lock_px, "KILIT")
                    # sonra ayni yonde yeniden gir: ayni risk mesafesi,
                    # stop kilitlenen kâr seviyesinin ALTINDA (long) kalir
                    # -> banka edilen kâr korunur.
                    new_dist = min(dist, cfg.lock_pct)
                    open_at(lock_px, side, j, stop_dist=new_dist, force=True)
                    if pos != 0:
                        pos_locked = True
                        locks += 1
                        cur_locks += 1

        # ---- 2) MURO aksiyonu (kapanis fiyatinda) ----
        act = acts[j] if j < len(acts) else ""
        if act == M.LONG_KAPAT:
            if pos == 1 and cfg.flip_exit:
                close_at(float(c[j]), "YAPI")
        elif act == M.SHORT_KAPAT:
            if pos == -1 and cfg.flip_exit:
                close_at(float(c[j]), "YAPI")
        elif act == M.AL:
            if pos == -1:
                close_at(float(c[j]), "YAPI")
                open_at(float(c[j]), 1, j)
            elif pos == 0:
                open_at(float(c[j]), 1, j)
        elif act == M.SAT:
            if pos == 1:
                close_at(float(c[j]), "YAPI")
                open_at(float(c[j]), -1, j)
            elif pos == 0:
                open_at(float(c[j]), -1, j)

        # ---- 3) trailing stop (kapanista) ----
        if pos != 0 and (pos_locked or cfg.trail_always):
            t = cfg.trail_pct
            if pos == 1:
                stop = max(stop, float(c[j]) * (1 - t))
            else:
                stop = min(stop, float(c[j]) * (1 + t))

        # ---- 4) funding + isaret ----
        if pos != 0 and funding:
            eq -= notional * funding
        mark = eq + ((c[j] - entry) * qty * pos if pos != 0 else 0.0)
        peak = max(peak, mark)
        if peak > 0:
            maxdd = max(maxdd, (peak - mark) / peak * 100.0)

    if pos != 0:
        close_at(float(c[end_i]), "SON")
    if cycle_dir != 0:
        cycles += 1
        cycle_pnls.append(cycle_pnl)
        cycle_locks.append(cur_locks)
        if cycle_pnl > 0:
            cycle_wins += 1

    res.ret_pct = (eq / START_BALANCE - 1) * 100
    res.maxdd_pct = maxdd
    res.entries = wins + losses
    res.locks = locks
    res.wins = wins
    res.losses = losses
    res.profit_factor = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)
    res.liquidations = liq
    res.final_equity = eq
    res.avg_lev = (lev_sum / lev_n) if lev_n else 0.0
    res.fees = fees_paid
    res.cycles = cycles
    res.cycle_wins = cycle_wins
    res.cycle_pnls = cycle_pnls
    res.cycle_locks = cycle_locks
    res.transitions = transitions
    return res


# --------------------------------------------------------------------------
# Toplama
# --------------------------------------------------------------------------
def eval_set(coins: list[str], cfg: M.MuroConfig, interval: str = "4h",
             leverage: float = 10.0, risk_pct: float = 0.0,
             last_n: int = 0) -> dict:
    fund = FUND_4H if interval == "4h" else FUND_1D
    rets, dds, pfs, levs = [], [], [], []
    nt = nl = nliq = 0
    cycles = cwin = 0
    cpnls: list[float] = []
    clocks: list[int] = []
    trans: list[tuple] = []
    fees: list[float] = []
    for sym in coins:
        try:
            d = load(sym, interval)
        except Exception:      # noqa: BLE001
            continue
        o, h, l, c = d["o"], d["h"], d["l"], d["c"]
        if last_n and len(c) > last_n:
            o, h, l, c = o[-last_n:], h[-last_n:], l[-last_n:], c[-last_n:]
            start = max(WARMUP, len(c) // 2)
        else:
            start = WARMUP
        if len(c) <= start + 30:
            continue
        r = run(sym, o, h, l, c, cfg, leverage=leverage, funding=fund,
                risk_pct=risk_pct, start_i=start)
        rets.append(r.ret_pct)
        dds.append(r.maxdd_pct)
        levs.append(r.avg_lev)
        if np.isfinite(r.profit_factor):
            pfs.append(r.profit_factor)
        nt += r.entries
        nl += r.locks
        nliq += r.liquidations
        cycles += r.cycles
        cwin += r.cycle_wins
        cpnls.extend(r.cycle_pnls)
        clocks.extend(r.cycle_locks)
        trans.extend(r.transitions)
        fees.append(r.fees)
    if not rets:
        return {}
    n_coin = len(rets)
    return {
        "med": float(np.median(rets)), "mean": float(np.mean(rets)),
        "pos_pct": sum(1 for x in rets if x > 0) / len(rets) * 100,
        "med_dd": float(np.median(dds)), "max_dd": float(max(dds)),
        "pf": float(np.median(pfs)) if pfs else 0.0,
        "lev": float(np.mean(levs)) if levs else 0.0,
        "trades": nt, "locks": nl, "liq": nliq,
        "tpc": nt / n_coin, "lock_tpc": nl / n_coin,
        "fee_pct": float(np.mean(fees)) / START_BALANCE * 100,
        "cycles": cycles,
        "cycle_win": (cwin / cycles * 100) if cycles else 0.0,
        "cycle_med": float(np.median(cpnls)) if cpnls else 0.0,
        "cycle_mean": float(np.mean(cpnls)) if cpnls else 0.0,
        "clocks": len(clocks),
        "lock_win": (sum(1 for p_, n_ in zip(cpnls, clocks)
                         if n_ > 0 and p_ > 0) /
                     max(1, sum(1 for n_ in clocks if n_ > 0)) * 100),
        "lock_med": float(np.median([p_ for p_, n_ in zip(cpnls, clocks)
                                     if n_ > 0])) if any(
                                         n_ > 0 for n_ in clocks) else 0.0,
        "lock_n": sum(1 for n_ in clocks if n_ > 0),
        "trans": len(trans),
        "trans_win": (sum(1 for t in trans if t[2] > 0) / len(trans) * 100)
        if trans else 0.0,
        "trans_med": float(np.median([t[2] for t in trans])) if trans else 0.0,
        "n": n_coin,
    }


def show(tag: str, d: dict) -> None:
    if not d:
        print(f"{tag}: veri yok")
        return
    print("%-10s med %+6.1f  ort %+6.1f  poz %3.0f%%  medDD %5.1f  "
          "maxDD %5.1f  pf %4.2f  lev %4.2fx  islem %4d  kilit %4d  "
          "liq %3d  gecis %3d (kar %3.0f%%)  kilitliDongu %3d "
          "(kar %3.0f%%, med %+6.1f)"
          % (tag, d["med"], d["mean"], d["pos_pct"], d["med_dd"], d["max_dd"],
             d["pf"], d["lev"], d["trades"], d["locks"], d["liq"],
             d["trans"], d["trans_win"], d["lock_n"], d["lock_win"],
             d["lock_med"]))


# --------------------------------------------------------------------------
# Komutlar
# --------------------------------------------------------------------------
def cmd_grid(args) -> None:
    """Kaba izgara: 4h, secim coinleri, 10x/20x."""
    interval = args[0] if args else "4h"
    levs = [10.0, 20.0]
    ks = [2, 3, 4]
    stops = [0.015, 0.02, 0.025, 0.03, 0.04]
    locks = [0.02, 0.03, 0.05]
    trails = [0.02, 0.03, 0.05]
    maxstops = [0.04, 0.05, 0.08]
    retests = [0.4, 0.6, 1.0]
    rows = []
    total = len(levs) * len(ks) * len(stops) * len(locks) * len(trails) * \
        len(maxstops) * len(retests)
    done = 0
    for lev in levs:
        for k in ks:
            for st in stops:
                for lk in locks:
                    for tr in trails:
                        for ms in maxstops:
                            for rt in retests:
                                cfg = M.MuroConfig(k=k, stop_pct=st,
                                                   max_stop_pct=ms,
                                                   lock_pct=lk, trail_pct=tr,
                                                   retest_atr=rt)
                                d = eval_set(COINS, cfg, interval, lev)
                                done += 1
                                if not d:
                                    continue
                                rows.append((d["med"], d, (lev, k, st, lk, tr, ms, rt)))
                                if done % 50 == 0:
                                    print("  ... %d/%d" % (done, total), flush=True)
    rows.sort(key=lambda r: -r[0])
    print()
    print("EN IYI 25 (secim coinleri, %s)" % interval)
    print("%7s %7s %6s %6s %6s %6s %6s %6s | %5s %6s %6s %5s %5s %7s"
          % ("med", "ort", "lev", "k", "stop", "lock", "trail", "mstop",
             "pf", "DD", "cycMed", "lev", "liq", "islem"))
    for med, d, p in rows[:25]:
        print("%+7.2f %+7.2f %6.0f %6d %6.3f %6.3f %6.3f %6.2f | %5.2f %6.1f "
              "%+6.1f %5.2f %5d %7d"
              % (med, d["mean"], p[0], p[1], p[2], p[3], p[4], p[5], d["pf"],
                 d["med_dd"], d["cycle_med"], d["lev"], d["liq"], d["trades"]))
    with open(os.path.join(RESEARCH_DIR, f"muro_grid_{interval}.json"),
              "w", encoding="utf-8") as f:
        json.dump([{"med": r[0], "params": r[2], **{k: v for k, v in r[1].items()
                                                   if k != "n"}}
                   for r in rows[:200]], f, indent=1)


def cmd_cross(args) -> None:
    """Secim + holdout, 4 parca zaman dilimi."""
    interval = args[0] if args else "4h"
    lev = float(args[1]) if len(args) > 1 else 10.0
    k = int(args[2]) if len(args) > 2 else 3
    st = float(args[3]) if len(args) > 3 else 0.025
    lk = float(args[4]) if len(args) > 4 else 0.03
    tr = float(args[5]) if len(args) > 5 else 0.03
    ms = float(args[6]) if len(args) > 6 else 0.05
    rt = float(args[7]) if len(args) > 7 else 0.6
    cfg = M.MuroConfig(k=k, stop_pct=st, max_stop_pct=ms, lock_pct=lk,
                       trail_pct=tr, retest_atr=rt)
    print("MURO · %s · lev %.0fx · k%d · stop%.3f lock%.3f trail%.3f "
          "mstop%.2f retest%.1f" % (interval, lev, k, st, lk, tr, ms, rt))
    show("SECIM", eval_set(COINS, cfg, interval, lev))
    show("HOLDOUT", eval_set(HOLDOUT, cfg, interval, lev))


def cmd_last500(args) -> None:
    """Uygulamanin 500 bar penceresi."""
    interval = args[0] if args else "4h"
    lev = float(args[1]) if len(args) > 1 else 10.0
    k = int(args[2]) if len(args) > 2 else 3
    st = float(args[3]) if len(args) > 3 else 0.025
    lk = float(args[4]) if len(args) > 4 else 0.03
    tr = float(args[5]) if len(args) > 5 else 0.03
    ms = float(args[6]) if len(args) > 6 else 0.05
    rt = float(args[7]) if len(args) > 7 else 0.6
    cfg = M.MuroConfig(k=k, stop_pct=st, max_stop_pct=ms, lock_pct=lk,
                       trail_pct=tr, retest_atr=rt)
    print("MURO · SON 500 BAR · %s · lev %.0fx" % (interval, lev))
    show("SECIM", eval_set(COINS, cfg, interval, lev, last_n=500))
    show("HOLDOUT", eval_set(HOLDOUT, cfg, interval, lev, last_n=500))


def cmd_sweep(args) -> None:
    """Risk bazli karsilastirma (10x yerine gercekte kucuk kaldirac)."""
    interval = args[0] if args else "4h"
    lev = float(args[1]) if len(args) > 1 else 20.0
    for risk in (0.02, 0.05, 0.10):
        cfg = M.MuroConfig()
        print("--- risk %%%d (tavan %.0fx) ---" % (risk * 100, lev))
        show("SECIM", eval_set(COINS, cfg, interval, lev, risk_pct=risk))
        show("HOLDOUT", eval_set(HOLDOUT, cfg, interval, lev, risk_pct=risk))


def cmd_search(args) -> None:
    """Rastgele arama: secim coinleri uzerinde en iyi parametre seti."""
    interval = args[0] if args else "4h"
    n_iter = int(args[1]) if len(args) > 1 else 200
    risk = float(args[2]) if len(args) > 2 else 0.02
    lev = float(args[3]) if len(args) > 3 else 20.0
    mode = args[4] if len(args) > 4 else "structure"
    rng = np.random.default_rng(20261019)
    rows = []
    for i in range(n_iter):
        # KILIT/TRAIL CIFTLERI: trailing, kilitten SONRA devreye girmeli
        # (aksi halde stop kâr kilidinden once kapanir ve "kârı cüzdana
        # at" mekanizmasi calismaz). Bu yuzden trail >= lock.
        lk_tr = [(0.01, 0.012), (0.015, 0.018), (0.02, 0.022), (0.02, 0.03),
                 (0.03, 0.032), (0.03, 0.04), (0.04, 0.045), (0.05, 0.06),
                 (0.02, 0.015), (0.03, 0.025)]
        lk, tr = lk_tr[int(rng.integers(len(lk_tr)))]
        base = dict(
            min_stop_pct=float(rng.choice([0.008, 0.01, 0.015, 0.02, 0.03])),
            max_stop_pct=float(rng.choice([0.03, 0.04, 0.05, 0.08])),
            lock_pct=lk,
            trail_pct=tr,
            cooldown=int(rng.choice([5, 10, 20, 30, 50])),
            trail_always=bool(rng.integers(2)),
            max_losses=int(rng.choice([0, 0, 1, 2, 3])),
        )
        if mode == "trend":
            base.update(
                mode="trend",
                st_period=int(rng.choice([5, 8, 10, 14, 20])),
                st_mult=float(rng.choice([2.0, 2.5, 3.0, 3.5, 4.0])),
                pull_ema=int(rng.choice([10, 20, 30, 50, 100])),
                pull_atr=float(rng.choice([0.2, 0.5, 1.0, 1.5, 2.0])),
            )
        else:
            base.update(
                mode="structure",
                k=int(rng.choice([2, 3, 4, 5, 6, 8])),
                retest_atr=float(rng.choice([0.3, 0.5, 0.6, 1.0, 1.5])),
                max_retest=int(rng.choice([6, 12, 24, 48])),
                trend_ema=int(rng.choice([0, 20, 50, 100, 200])),
            )
        cfg = M.MuroConfig(**base)
        d = eval_set(COINS, cfg, interval, lev, risk_pct=risk)
        if not d:
            continue
        # ISLEM SAYISI SINIRI: cok fazla islem -> komisyon yer.
        if d["tpc"] > 55:
            continue
        rows.append((d["med"], d, cfg))
        if (i + 1) % 20 == 0:
            print("  ... %d/%d" % (i + 1, n_iter), flush=True)
    rows.sort(key=lambda r: -r[0])
    print()
    print("EN IYI 20 (secim, %s, risk %%%d, %s) -- islem/coin <= 70" %
          (interval, risk * 100, mode))
    print("%7s %7s %5s %5s %6s %5s %6s %5s | %5s %5s %5s %5s %10s %10s"
          % ("med", "ort", "poz%", "tpc", "fee%", "pf", "medDD", "lev",
             "lock", "trail", "mstop", "minst", "k/st", "pull"))
    for med, d, c in rows[:20]:
        print("%+7.2f %+7.2f %5.0f %5.0f %6.1f %5.2f %6.1f %5.2f | %5.3f "
              "%5.3f %5.2f %5.3f %10s %10s"
              % (med, d["mean"], d["pos_pct"], d["tpc"], d["fee_pct"], d["pf"],
                 d["med_dd"], d["lev"], c.lock_pct, c.trail_pct, c.max_stop_pct,
                 c.min_stop_pct,
                 ("k%d" % c.k) if c.mode == "structure"
                 else ("st%d/%.1f" % (c.st_period, c.st_mult)),
                 ("ema%d/%.1f" % (c.pull_ema, c.pull_atr))
                 if c.mode == "trend" else "-"))
    name = "muro_search_%s_%s.json" % (mode, interval)
    with open(os.path.join(RESEARCH_DIR, name), "w", encoding="utf-8") as f:
        json.dump([{"med": r[0], "params": r[2].__dict__,
                    **{k: v for k, v in r[1].items() if k != "n"}}
                   for r in rows[:60]], f, indent=1)


def cmd_holdout(args) -> None:
    """En iyi parametre setini holdout + 500 bar penceresinde dogrula."""
    interval = args[0] if args else "4h"
    risk = float(args[1]) if len(args) > 1 else 0.02
    lev = float(args[2]) if len(args) > 2 else 20.0
    mode = args[3] if len(args) > 3 else "structure"
    path = os.path.join(RESEARCH_DIR,
                       "muro_search_%s_%s.json" % (mode, interval))
    data = json.load(open(path, encoding="utf-8"))
    print("%-4s %7s %7s | %-28s | %-28s" %
          ("#", "SECIM", "HOLD", "secim (med/poz/pf/tpc)", "holdout (med/poz/pf/tpc)"))
    for i, row in enumerate(data[:12]):
        p = row["params"]
        cfg = M.MuroConfig(**p)
        a = eval_set(COINS, cfg, interval, lev, risk_pct=risk)
        b = eval_set(HOLDOUT, cfg, interval, lev, risk_pct=risk)
        c = eval_set(COINS, cfg, interval, lev, risk_pct=risk, last_n=500)
        d = eval_set(HOLDOUT, cfg, interval, lev, risk_pct=risk, last_n=500)
        print("%-4d %+7.2f %+7.2f | med %+6.1f poz %3.0f%% pf %4.2f tpc %4.0f "
              "| med %+6.1f poz %3.0f%% pf %4.2f tpc %4.0f  | 500bar: "
              "sec %+6.1f / hold %+6.1f"
              % (i, a["med"], b["med"],
                 a["med"], a["pos_pct"], a["pf"], a["tpc"],
                 b["med"], b["pos_pct"], b["pf"], b["tpc"],
                 c["med"], d["med"]))


def eval_folds(coins: list[str], cfg: M.MuroConfig, interval: str = "1d",
               leverage: float = 20.0, risk_pct: float = 0.02,
               folds: int = 4) -> list[dict]:
    """Her fold ayri baslar (bakiye sifirlanir) — zaman saglamligi testi."""
    fund = FUND_4H if interval == "4h" else FUND_1D
    out = []
    for k in range(folds):
        rets, dds, tpc = [], [], []
        trans_win, trans_n = 0, 0
        cyc_med = []
        for sym in coins:
            try:
                d = load(sym, interval)
            except Exception:      # noqa: BLE001
                continue
            o, h, l, c = d["o"], d["h"], d["l"], d["c"]
            n = c.size
            size = n // folds
            a = max(k * size, WARMUP)
            b = n - 1 if k == folds - 1 else (k + 1) * size
            if b <= a + 30:
                continue
            r = run(sym, o, h, l, c, cfg, leverage=leverage, funding=fund,
                    risk_pct=risk_pct, start_i=a, end_i=b)
            rets.append(r.ret_pct)
            dds.append(r.maxdd_pct)
            tpc.append(r.entries)
            if r.transitions:
                trans_n += len(r.transitions)
                trans_win += sum(1 for t in r.transitions if t[2] > 0)
            cyc_med.extend(r.cycle_pnls)
        if not rets:
            continue
        out.append({
            "fold": k + 1,
            "med": float(np.median(rets)), "mean": float(np.mean(rets)),
            "pos": sum(1 for x in rets if x > 0) / len(rets) * 100,
            "dd": float(np.median(dds)),
            "tpc": float(np.mean(tpc)),
            "trans_win": (trans_win / trans_n * 100) if trans_n else 0.0,
            "trans_n": trans_n,
            "cyc_med": float(np.median(cyc_med)) if cyc_med else 0.0,
        })
    return out


def cmd_best(args) -> None:
    """En iyi parametre setinin kapsamli raporu."""
    interval = args[0] if args else "1d"
    mode = args[1] if len(args) > 1 else "trend"
    lev = float(args[2]) if len(args) > 2 else 20.0
    path = os.path.join(RESEARCH_DIR,
                        "muro_search_%s_%s.json" % (mode, interval))
    data = json.load(open(path, encoding="utf-8"))
    p = data[0]["params"]
    cfg = M.MuroConfig(**p)
    print("EN IYI PARAMETRE SETI (%s, %s)" % (mode, interval))
    for k, v in cfg.__dict__.items():
        print("   %-14s %s" % (k, v))
    print()
    for risk in (0.01, 0.02, 0.05, 0.10):
        print("--- risk %%%d (kaldirac tavan %.0fx) ---" % (risk * 100, lev))
        show("SECIM", eval_set(COINS, cfg, interval, lev, risk_pct=risk))
        show("HOLDOUT", eval_set(HOLDOUT, cfg, interval, lev, risk_pct=risk))
    print("--- TAM KULLANIM (risk 0: kaldirac gercekten kullanilir) ---")
    show("SECIM", eval_set(COINS, cfg, interval, lev, risk_pct=0.0))
    show("HOLDOUT", eval_set(HOLDOUT, cfg, interval, lev, risk_pct=0.0))
    print()
    print("--- ZAMAN DILIMLERI (4 fold, risk %2) ---" % 2.0)
    for tag, coins in (("SECIM", COINS), ("HOLDOUT", HOLDOUT)):
        print("  %s:" % tag)
        for f in eval_folds(coins, cfg, interval, lev, 0.02, 4):
            print("    fold %d: med %+6.1f  ort %+6.1f  poz %3.0f%%  "
                  "medDD %5.1f  tpc %4.0f  gecisKar %3.0f%% (n=%d)  "
                  "cycleMed %+7.1f"
                  % (f["fold"], f["med"], f["mean"], f["pos"], f["dd"],
                     f["tpc"], f["trans_win"], f["trans_n"], f["cyc_med"]))
    print()
    print("--- 500 BAR PENCERESI (uygulamanin penceresi) ---")
    for risk in (0.02, 0.05):
        show("SECIM", eval_set(COINS, cfg, interval, lev, risk_pct=risk,
                               last_n=500))
        show("HOLDOUT", eval_set(HOLDOUT, cfg, interval, lev, risk_pct=risk,
                                 last_n=500))


def cmd_variants(args) -> None:
    """Ayni parametre setinde davranis varyantlari."""
    interval = args[0] if args else "1d"
    mode = args[1] if len(args) > 1 else "trend"
    risk = float(args[2]) if len(args) > 2 else 0.05
    lev = float(args[3]) if len(args) > 3 else 20.0
    path = os.path.join(RESEARCH_DIR,
                        "muro_search_%s_%s.json" % (mode, interval))
    data = json.load(open(path, encoding="utf-8"))
    base = data[0]["params"]
    print("VARYANT KARSILASTIRMASI (risk %%%d, %s, %s)" %
          (risk * 100, mode, interval))
    for trail_always in (True, False):
        for flip_exit in (True, False):
            p2 = dict(base)
            p2["trail_always"] = trail_always
            p2["flip_exit"] = flip_exit
            cfg = M.MuroConfig(**p2)
            a = eval_set(COINS, cfg, interval, lev, risk_pct=risk)
            b = eval_set(HOLDOUT, cfg, interval, lev, risk_pct=risk)
            print("  trail=%-5s flip_exit=%-5s | SECIM med %+6.1f poz %3.0f%% "
                  "pf %4.2f gecisKar %3.0f%% (med %+6.1f) | HOLD med %+6.1f "
                  "poz %3.0f%% pf %4.2f gecisKar %3.0f%% (med %+6.1f)"
                  % (trail_always, flip_exit, a["med"], a["pos_pct"], a["pf"],
                     a["trans_win"], a["trans_med"], b["med"], b["pos_pct"],
                     b["pf"], b["trans_win"], b["trans_med"]))


def cmd_final(args) -> None:
    """
    SECIM BIYANLILIGINDAN KURTULMA: arama sonucu listesindeki en iyi
    adaylar hem secim hem holdout hem de 500 bar penceresi ile
    birlikte degerlendirilir. Sadece "secimde en iyi" olana degil,
    IKISINDE de saglam olan parametre seti secilir.
    """
    interval = args[0] if args else "1d"
    mode = args[1] if len(args) > 1 else "trend"
    risk = float(args[2]) if len(args) > 2 else 0.05
    lev = float(args[3]) if len(args) > 3 else 20.0
    top = int(args[4]) if len(args) > 4 else 30
    path = os.path.join(RESEARCH_DIR,
                        "muro_search_%s_%s.json" % (mode, interval))
    data = json.load(open(path, encoding="utf-8"))[:top]
    rows = []
    for i, row in enumerate(data):
        cfg = M.MuroConfig(**row["params"])
        a = eval_set(COINS, cfg, interval, lev, risk_pct=risk)
        b = eval_set(HOLDOUT, cfg, interval, lev, risk_pct=risk)
        c = eval_set(COINS, cfg, interval, lev, risk_pct=risk, last_n=500)
        d = eval_set(HOLDOUT, cfg, interval, lev, risk_pct=risk, last_n=500)
        if not (a and b and c and d):
            continue
        # SKOR: iki kumenin medyani (min = daha zayif olan) + 500 bar
        # penceresinin medyani. Boylece "sadece secimde iyi" olan elenir.
        score = min(a["med"], b["med"]) + 0.5 * (c["med"] + d["med"])
        rows.append((score, i, a, b, c, d, cfg))
    rows.sort(key=lambda r: -r[0])
    print("ADAY ELITESI (risk %%%d, %s, %s) -- skor = min(secim,hold) + "
          "0,5*(500bar secim+hold)" % (risk * 100, mode, interval))
    print("%-4s %8s %8s %8s %8s %8s | %5s %5s %5s %5s | %6s %6s"
          % ("#", "SKOR", "SECIM", "HOLD", "500s", "500h",
             "pfs", "pfh", "poss", "posh", "gecK%", "gecMed"))
    for score, i, a, b, c, d, cfg in rows[:15]:
        print("%-4d %8.1f %8.1f %8.1f %8.1f %8.1f | %5.2f %5.2f %5.0f %5.0f "
              "| %6.0f %6.1f"
              % (i, score, a["med"], b["med"], c["med"], d["med"],
                 a["pf"], b["pf"], a["pos_pct"], b["pos_pct"],
                 b["trans_win"], b["trans_med"]))
    if not rows:
        return
    score, i, a, b, c, d, cfg = rows[0]
    print()
    print("KAZANAN PARAMETRE SETI")
    for k, v in cfg.__dict__.items():
        print("   %-14s %s" % (k, v))
    print()
    show("SECIM", a)
    show("HOLDOUT", b)
    show("SECIM500", c)
    show("HOLD500", d)
    print()
    print("ZAMAN DILIMLERI (4 fold)")
    for tag, coins in (("SECIM", COINS), ("HOLDOUT", HOLDOUT)):
        print("  %s:" % tag)
        for f in eval_folds(coins, cfg, interval, lev, risk, 4):
            print("    fold %d: med %+7.1f  ort %+7.1f  poz %3.0f%%  medDD "
                  "%5.1f  tpc %4.0f  gecisKar %3.0f%% (n=%d)"
                  % (f["fold"], f["med"], f["mean"], f["pos"], f["dd"],
                     f["tpc"], f["trans_win"], f["trans_n"]))
    with open(os.path.join(RESEARCH_DIR,
                            "muro_best_%s_%s.json" % (mode, interval)),
              "w", encoding="utf-8") as f:
        json.dump({"params": cfg.__dict__, "sel": a, "hold": b,
                   "sel500": c, "hold500": d}, f, indent=1)


def cmd_sens(args) -> None:
    """
    DUYARLILIK: kazanan parametre setinin etrafinda tek tek parametre
    degistirilir. "Bicak agzi" (knife-edge) bir ayar varsa burasi
    gorunur: komsu degerler de calisiyorsa ayar saglamdir.
    """
    interval = args[0] if args else "1d"
    mode = args[1] if len(args) > 1 else "trend"
    risk = float(args[2]) if len(args) > 2 else 0.05
    lev = float(args[3]) if len(args) > 3 else 20.0
    path = os.path.join(RESEARCH_DIR,
                        "muro_best_%s_%s.json" % (mode, interval))
    data = json.load(open(path, encoding="utf-8"))
    base = dict(data["params"])
    print("DUYARLILIK (risk %%%d, %s, %s)" % (risk * 100, mode, interval))
    print("%-16s %-8s %8s %8s %6s %6s %8s" %
          ("parametre", "deger", "SECIM", "HOLD", "pfs", "pfh", "gecKar%"))
    for key, values in (
            ("lock_pct", [0.008, 0.01, 0.015, 0.02, 0.03, 0.05]),
            ("trail_pct", [0.012, 0.015, 0.02, 0.03]),
            ("st_period", [5, 8, 10, 14, 20]),
            ("st_mult", [2.0, 2.5, 3.0, 3.5, 4.0]),
            ("pull_ema", [20, 50, 100, 200]),
            ("pull_atr", [0.2, 0.5, 1.0, 1.5, 2.0]),
            ("cooldown", [5, 10, 20, 30, 50]),
            ("min_stop_pct", [0.008, 0.01, 0.015, 0.02, 0.03]),
            ("max_stop_pct", [0.03, 0.04, 0.05, 0.08]),
            ("max_losses", [0, 1, 2, 3]),
            ("risk", [0.02, 0.03, 0.05, 0.08]),
    ):
        for v in values:
            p2 = dict(base)
            if key == "risk":
                r = v
            else:
                p2[key] = v
                r = risk
            cfg = M.MuroConfig(**p2)
            a = eval_set(COINS, cfg, interval, lev, risk_pct=r)
            b = eval_set(HOLDOUT, cfg, interval, lev, risk_pct=r)
            if not (a and b):
                continue
            mark = " *" if abs(v - base.get(key, -99)) < 1e-9 else ""
            print("%-16s %-8s %8.1f %8.1f %6.2f %6.2f %8.0f%s" %
                  (key, v, a["med"], b["med"], a["pf"], b["pf"],
                   b["trans_win"], mark))
        print()


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "grid"
    rest = args[1:]
    if cmd == "grid":
        cmd_grid(rest)
    elif cmd == "search":
        cmd_search(rest)
    elif cmd == "holdout":
        cmd_holdout(rest)
    elif cmd == "best":
        cmd_best(rest)
    elif cmd == "variants":
        cmd_variants(rest)
    elif cmd == "final":
        cmd_final(rest)
    elif cmd == "sens":
        cmd_sens(rest)
    elif cmd == "cross":
        cmd_cross(rest)
    elif cmd == "last500":
        cmd_last500(rest)
    elif cmd == "sweep":
        cmd_sweep(rest)
    else:
        print("komut: search | holdout | grid | cross | last500 | sweep")


if __name__ == "__main__":
    main()

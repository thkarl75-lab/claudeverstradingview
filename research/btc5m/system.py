# -*- coding: utf-8 -*-
"""
system.py — Score de confluence (0-100), signaux BUY/SELL/NEUTRAL et moteur de backtest réaliste.

Thème retenu (le seul cohérent train -> validation, voir RAPPORT.md) :
  "continuation du flux en phase d'expansion" — une pression acheteuse/vendeuse soutenue sur 4h
  (imbalance de volume signé) accompagnée d'une expansion du range tend à se prolonger ~2h.
"""
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


@dataclass
class Params:
    thr80: float = 0.0        # seuil |imb_48| (quantile 80 % du train)
    thr90: float = 0.0        # seuil |imb_48| (quantile 90 % du train)
    vol_p5: float = 0.0       # percentile 5 % du volume (train) : filtre de liquidité
    min_pts: int = 70         # points minimum pour déclencher un signal
    hold: int = 24            # sortie temporelle (bougies)
    sl_k: float = 5.0         # stop = sl_k × vol_unit (médiane 4h du range relatif)
    tp_k: float = 10.0        # objectif = tp_k × vol_unit
    risk: float = 0.01        # risque par trade (fraction du capital)
    max_lev: float = 3.0      # levier maximum
    fee: float = 0.0004       # frais par côté (taker)
    slip: float = 0.0001      # slippage par exécution
    part: float = 0.01        # participation max : 1 % du volume de la bougie d'exécution
    funding_8h: float = 0.0   # funding par 8h (0 = "spot-like" ; 0.0001 = perp typique)
    long_only: bool = False
    worst_entry: bool = False  # stress : entrée au pire prix (high/low) de la bougie d'exécution


def fit_thresholds(F: pd.DataFrame, df: pd.DataFrame, p: Params) -> Params:
    """Calibre les seuils dépendant des données sur la fenêtre d'entraînement UNIQUEMENT."""
    a = F.imb_48.abs().dropna()
    p.thr80, p.thr90 = float(a.quantile(0.80)), float(a.quantile(0.90))
    p.vol_p5 = float(df.volume.quantile(0.05))
    return p


def score(F: pd.DataFrame, df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Score de confluence 0-100 (50 = neutre ; >50 haussier ; <50 baissier) + signal."""
    d = np.sign(F.imb_48).fillna(0)
    a = F.imb_48.abs()
    press = a >= p.thr80                     # porte n°1 : pression 4h
    expan = F.vol_ratio >= 1.0               # porte n°2 : expansion (filtre de régime)
    pts = (30 * press + 10 * (a >= p.thr90)
           + 20 * expan + 10 * (F.vol_ratio >= 1.2)
           + 10 * (F.rel_vol_6 >= 1.5)
           + 10 * (F.eff_48 >= 0.15)
           + 10 * ((np.sign(F.mom_3) != d) & (d != 0)))
    liquid = df.volume >= p.vol_p5           # filtre de liquidité
    ok = press & expan & liquid & (pts >= p.min_pts) & F.vol_unit.notna()
    out = pd.DataFrame(index=F.index)
    out["score"] = (50 + d * pts / 2).clip(0, 100)
    out["signal"] = np.where(ok, d, 0).astype(int)
    if p.long_only:
        out.loc[out.signal < 0, "signal"] = 0
    return out


def simulate(df: pd.DataFrame, sig: pd.Series, vol_unit: pd.Series, p: Params, capital: float = 10_000.0):
    """
    Backtest événementiel, une position à la fois.
      * signal figé à la clôture de t  ->  exécution à l'OPEN de t+1 (+ slippage défavorable)
      * stop / objectif testés intrabar à partir de la bougie d'entrée ; si les deux sont
        touchés dans la même bougie, on suppose le STOP en premier (hypothèse pessimiste)
      * gap au-delà du stop : sortie à l'open (pire que le stop)
      * sortie temporelle à l'open de la bougie suivant la fin de la durée de détention
      * taille : risque fixe / distance au stop, plafonnée par le levier max ET par une
        participation de `part` au volume de la bougie d'exécution (fill partiel)
    Retourne (trades DataFrame, equity Series marquée au close de chaque bougie, ordres).
    """
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    qv = df.quote_volume.values
    s, vu = sig.values, vol_unit.values
    n = len(df)
    eq = capital
    equity = np.empty(n)
    trades, orders = [], []          # orders : (index bougie, phase 0=open 1=intrabar, qty signée, prix brut)
    pos = 0; qty = 0.0; entry = sl = tp = 0.0; t_in = 0; exit_at_open = False; cost_in = 0.0
    fund_bar = p.funding_8h / 96.0

    def close_pos(i, raw, phase, reason):
        nonlocal eq, pos, qty
        px = raw * (1 - p.slip * pos)                       # slippage défavorable à la sortie
        pnl = pos * qty * (px - entry) - qty * px * p.fee - cost_in - fund_bar * qty * entry * (i - t_in + 1)
        eq += pnl
        orders.append((i, phase, -pos * qty, raw))
        trades.append(dict(entry_time=df.index[t_in], exit_time=df.index[i], side=pos, entry=entry, exit=px,
                           qty=qty, pnl=pnl, ret_equity=pnl / (eq - pnl), bars=i - t_in + 1, reason=reason,
                           gross_bp=pos * (raw / entry_raw - 1) * 1e4,
                           net_bp=(pos * (px / entry - 1) - 2 * p.fee) * 1e4))
        pos = 0; qty = 0.0

    entry_raw = 0.0
    for i in range(n):
        # 1) sortie temporelle à l'open
        if pos != 0 and exit_at_open:
            close_pos(i, o[i], 0, "time"); exit_at_open = False
        # 2) entrée à l'open (signal de la bougie précédente, on devait être à plat à sa clôture)
        elif pos == 0 and i > 0 and s[i - 1] != 0 and flat_prev and vu[i - 1] > 0:
            d = int(s[i - 1])
            entry_raw = (h[i] if d > 0 else l[i]) if p.worst_entry else o[i]
            entry = entry_raw * (1 + p.slip * d)
            dist = p.sl_k * vu[i - 1]                          # distance au stop (fraction du prix)
            notional = min(eq * p.risk / dist, eq * p.max_lev, p.part * qv[i])
            if notional > 10:
                pos, qty, t_in = d, notional / entry, i
                sl, tp = entry * (1 - d * dist), entry * (1 + d * p.tp_k * vu[i - 1])
                cost_in = qty * entry * p.fee
                orders.append((i, 0, d * qty, entry_raw))
        # 3) stop / objectif intrabar (stop prioritaire)
        if pos != 0:
            if pos > 0:
                if l[i] <= sl: close_pos(i, min(sl, o[i]), 1, "stop")
                elif h[i] >= tp: close_pos(i, tp, 1, "target")
            else:
                if h[i] >= sl: close_pos(i, max(sl, o[i]), 1, "stop")
                elif l[i] <= tp: close_pos(i, tp, 1, "target")
            if pos != 0 and i - t_in + 1 >= p.hold:
                exit_at_open = True
        flat_prev = (pos == 0)
        equity[i] = eq + (pos * qty * (c[i] - entry) - cost_in if pos != 0 else 0.0)
    return pd.DataFrame(trades), pd.Series(equity, index=df.index), orders


def metrics(trades: pd.DataFrame, equity: pd.Series, capital: float = 10_000.0) -> dict:
    """Métriques sur rendements JOURNALIERS (annualisation √365, crypto 24/7)."""
    if len(trades) == 0:
        return dict(trades=0)
    d_eq = equity.resample("1D").last()
    daily = pd.concat([pd.Series([capital]), d_eq]).pct_change().dropna()   # 1er jour inclus
    dd = equity / equity.cummax() - 1
    days = (equity.index[-1] - equity.index[0]).total_seconds() / 86400
    tot = equity.iloc[-1] / capital - 1
    cagr = (1 + tot) ** (365 / days) - 1 if tot > -1 else -1
    neg = daily[daily < 0]
    w, lo = trades.pnl[trades.pnl > 0], trades.pnl[trades.pnl <= 0]
    return dict(trades=len(trades), winrate=len(w) / len(trades),
                profit_factor=w.sum() / abs(lo.sum()) if lo.sum() != 0 else np.inf,
                total_return=tot, cagr=cagr, max_dd=dd.min(),
                sharpe=daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else np.nan,
                sortino=daily.mean() / np.sqrt((neg ** 2).sum() / len(daily)) * np.sqrt(365) if len(neg) else np.nan,
                calmar=cagr / abs(dd.min()) if dd.min() < 0 else np.nan,
                avg_gross_bp=trades.gross_bp.mean(), avg_net_bp=trades.net_bp.mean(),
                avg_bars=trades.bars.mean(), pct_long=(trades.side > 0).mean(),
                stop_rate=(trades.reason == "stop").mean(), target_rate=(trades.reason == "target").mean())

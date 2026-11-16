# -*- coding: utf-8 -*-
"""
backtest_mtf.py — Test multi-timeframe : indicateurs classiques comme FILTRES de contexte
(1H : EMA 200 + RSI 14 ; 15m : EMA 50) et déclencheurs 5m = événements de prix.

20 combinaisons fixées À L'AVANCE (5 déclencheurs × 4 configurations de filtres), aucune
optimisation de paramètres : les sorties sont celles du système précédent (stop 4 × et objectif
12 × la médiane 4h du range relatif, sortie après 24 bougies) pour que la comparaison soit directe.

Anti-repaint : une valeur 1H / 15m n'est utilisée par une bougie 5m que si la bougie de
timeframe supérieur est entièrement CLÔTURÉE à la clôture de cette bougie 5m.

Usage : python backtest_mtf.py <dossier_des_csv> [results_mtf]
"""
import sys, os, json, warnings
from dataclasses import asdict
import numpy as np
import pandas as pd
from features import load, build_features
from system import Params, simulate, metrics

warnings.filterwarnings("ignore")
CAPITAL = 10_000.0
N_COMBOS = 20
ALPHA = 0.05 / N_COMBOS                      # correction de Bonferroni
BASE = Params(hold=24, sl_k=4.0, tp_k=12.0)  # sorties figées (identiques au système précédent)
FULL = ("2025-10-15", "2026-07-31")          # 2 semaines d'amorçage pour l'EMA 200 en 1H
NEW = ("2026-03-01", "2026-07-31")           # période où le système "from scratch" perdait 65 %
WF_TESTS = pd.period_range("2026-02", "2026-07", freq="M")


# ----------------------------------------------------------------------------- indicateurs
def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s, n=14):
    """RSI de Wilder."""
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn)


def resample(df, rule):
    """Reconstruit des bougies de timeframe supérieur à partir des 5m (étiquette = ouverture)."""
    o = df.resample(rule, label="left", closed="left").agg(
        dict(open="first", high="max", low="min", close="last", volume="sum"))
    n = df.close.resample(rule, label="left", closed="left").count()
    return o[n == n.max()]                    # on écarte toute bougie incomplète


def align(htf_series, rule, idx):
    """Valeur de la dernière bougie HTF clôturée, vue depuis la CLÔTURE de chaque bougie 5m."""
    avail = htf_series.copy()
    avail.index = avail.index + pd.Timedelta(rule)          # instant où la bougie HTF est close
    out = avail.reindex(idx + pd.Timedelta("5min"), method="ffill")
    out.index = idx
    return out


# ----------------------------------------------------------------------------- signaux
def build(df):
    o, h, l, c, v = df.open, df.high, df.low, df.close, df.volume
    h1, m15 = resample(df, "1h"), resample(df, "15min")
    c1, e200, r14 = (align(x, "1h", df.index) for x in (h1.close, ema(h1.close, 200), rsi(h1.close, 14)))
    c15, e50 = (align(x, "15min", df.index) for x in (m15.close, ema(m15.close, 50)))
    f1h = pd.Series(np.where((c1 > e200) & (r14 > 50), 1, np.where((c1 < e200) & (r14 < 50), -1, 0)), df.index)
    f15 = pd.Series(np.where(c15 > e50, 1, np.where(c15 < e50, -1, 0)), df.index)
    ok = e200.notna() & e50.notna()

    rng = h - l
    rs = rng.replace(0, np.nan)
    lw, uw = (np.minimum(o, c) - l) / rs, (h - np.maximum(o, c)) / rs
    mr, mv = rng.rolling(20).mean().shift(1), v.rolling(20).mean().shift(1)
    S = lambda up, dn: pd.Series(np.where(up, 1, np.where(dn, -1, 0)), df.index)
    trig = {
        "T1 cassure bougie préc.": S(c > h.shift(1), c < l.shift(1)),
        "T2 rejet (mèche > 50 %)": S((lw > 0.5) & (rng >= mr), (uw > 0.5) & (rng >= mr)),
        "T3 expansion + volume": S((rng > 1.5 * mr) & (v > mv) & (c > o), (rng > 1.5 * mr) & (v > mv) & (c < o)),
        "T4 cassure après repli": S((c.shift(1) < c.shift(4)) & (c > h.shift(1)), (c.shift(1) > c.shift(4)) & (c < l.shift(1))),
        "T5 cassure range 1h": S(c > h.shift(1).rolling(12).max(), c < l.shift(1).rolling(12).min()),
    }
    filt = {
        "aucun filtre": lambda t: t,
        "1H seul": lambda t: t.where(t == f1h, 0),
        "15m seul": lambda t: t.where(t == f15, 0),
        "1H + 15m": lambda t: t.where((t == f1h) & (t == f15), 0),
    }
    # liquidité : volume >= percentile 5 % des 7 jours précédents (causal)
    liquid = v >= v.rolling(2016).quantile(0.05).shift(1)
    combos = {}
    for tn, t in trig.items():
        for fn, f in filt.items():
            combos[f"{tn} | {fn}"] = f(t).where(liquid & ok, 0).astype(int)
    assert len(combos) == N_COMBOS
    return combos, dict(f1h=f1h, f15=f15)


def run(df, vu, sig, period, p=BASE):
    s = slice(*period)
    tr, eq, _ = simulate(df[s], sig[s], vu[s], p, CAPITAL)
    return tr, metrics(tr, eq, CAPITAL)


def p_net(tr, n_boot=10000):
    """p-value unilatérale H0 : net moyen par trade <= 0 (bootstrap par jour d'entrée)."""
    if len(tr) < 30:
        return 1.0
    g = tr.groupby(tr.entry_time.dt.normalize()).net_bp.agg(["sum", "size"]).values
    i = np.random.default_rng(0).integers(0, len(g), (n_boot, len(g)))
    return float((g[i, 0].sum(1) / g[i, 1].sum(1) <= 0).mean())


def main(data_dir, out):
    df = load(data_dir)
    vu = build_features(df).vol_unit
    combos, ctx = build(df)
    print(f"Filtre 1H : long {np.mean(ctx['f1h'] == 1):.0%} / short {np.mean(ctx['f1h'] == -1):.0%} / neutre "
          f"{np.mean(ctx['f1h'] == 0):.0%} du temps | 15m : long {np.mean(ctx['f15'] == 1):.0%} / short {np.mean(ctx['f15'] == -1):.0%}")
    stress = Params(**{**asdict(BASE), "fee": 0.0008, "slip": 0.0002})
    rows = []
    for name, sig in combos.items():
        tr, m = run(df, vu, sig, FULL)
        _, mn = run(df, vu, sig, NEW)
        _, ms = run(df, vu, sig, FULL, stress)
        pv = p_net(tr)
        verdict = ("EDGE RÉEL" if m["avg_net_bp"] > 0 and pv < ALPHA and ms["avg_net_bp"] > 0 else
                   "marginal" if m["avg_net_bp"] > 0 else "pas d'edge")
        rows.append(dict(combinaison=name, trades=m["trades"], brut_bp=m["avg_gross_bp"], net_bp=m["avg_net_bp"],
                         winrate=m["winrate"], pf=m["profit_factor"], sharpe=m["sharpe"], max_dd=m["max_dd"],
                         ret=m["total_return"], p_net=pv, ret_mars_juil=mn["total_return"],
                         net_bp_stress=ms["avg_net_bp"], ret_stress=ms["total_return"], verdict=verdict))
    R = pd.DataFrame(rows)
    R.to_csv(f"{out}/combos.csv", index=False)
    pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 40)
    print(f"\n10 mois ({FULL[0]} -> {FULL[1]}), seuil de Bonferroni p < {ALPHA:.4f}")
    print(R.round(3).to_string(index=False))

    # walk-forward : à chaque fold, on choisit la combinaison au meilleur Sharpe sur 4 mois, on la trade 1 mois
    print("\nWalk-forward 4 mois -> 1 mois (sélection de la meilleure combinaison sur le train)")
    wf, trs = [], []
    for k, tm in enumerate(WF_TESTS, 1):
        t0 = max(pd.Timestamp(FULL[0]), (tm - 4).start_time)
        trn = (str(t0.date()), str((tm - 1).end_time.date())); tst = (str(tm.start_time.date()), str(tm.end_time.date()))
        best, bs = None, -np.inf
        for name, sig in combos.items():
            m = run(df, vu, sig, trn)[1]
            if m.get("trades", 0) >= 30 and m["sharpe"] > bs:
                best, bs = name, m["sharpe"]
        tr, m = run(df, vu, combos[best], tst)
        wf.append(dict(fold=k, test=str(tm), choisie=best, sharpe_train=bs, trades=m["trades"], net_bp=m["avg_net_bp"],
                       brut_bp=m["avg_gross_bp"], pf=m["profit_factor"], ret=m["total_return"], max_dd=m["max_dd"]))
        trs.append(tr)
    W = pd.DataFrame(wf); W.to_csv(f"{out}/walk_forward.csv", index=False)
    print(W.round(3).to_string(index=False))
    allt = pd.concat(trs)
    tot = dict(trades=len(allt), net_bp=float(allt.net_bp.mean()), compounded=float(np.prod(1 + W.ret) - 1),
               positive_folds=int((W.ret > 0).sum()), p_net=p_net(allt))
    print("cumul :", tot)
    json.dump(dict(combos=rows, walk_forward=wf, wf_total=tot, alpha=ALPHA), open(f"{out}/results_mtf.json", "w"),
              indent=1, default=float)


if __name__ == "__main__":
    out = sys.argv[2] if len(sys.argv) > 2 else "results_mtf"
    os.makedirs(out, exist_ok=True)
    main(sys.argv[1], out)

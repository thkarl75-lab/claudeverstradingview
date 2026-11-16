# -*- coding: utf-8 -*-
"""
backtest_wf.py — Pipeline complet : minage strict des règles, système figé + test final
out-of-sample, walk-forward 3 folds, stress tests, contrôle croisé vectorbt.

Usage :  python backtest_wf.py <dossier_des_csv> [dossier_resultats]

Découpage (5 mois de données : 2025-10 -> 2026-02) :
  * TRAIN       : 2025-10-08 -> 2025-11-30  (la 1re semaine sert d'amorçage aux fenêtres 7 jours)
  * VALIDATION  : 2025-12
  * TEST FINAL  : 2026-01 -> 2026-02  (jamais consulté pendant la conception)
  * WALK-FORWARD: 3 folds, 2 mois de train glissants -> 1 mois de test (déc., janv., fév.)
Avec 13 mois, remplacer les constantes ci-dessous par 4 mois train / 1 mois test et 3 mois de test final.
"""
import sys, json, itertools, warnings
from dataclasses import asdict
import numpy as np
import pandas as pd
import vectorbt as vbt
from features import load, build_features, forward_returns, HORIZONS
from mine_rules import mine, rf_importance
from system import Params, fit_thresholds, score, simulate, metrics

warnings.filterwarnings("ignore")
CAPITAL = 10_000.0
TRAIN, VALID, TEST = ("2025-10-08", "2025-11-30"), ("2025-12-01", "2025-12-31"), ("2026-01-01", "2026-02-28")
FOLDS = [(("2025-10-08", "2025-11-30"), ("2025-12-01", "2025-12-31")),
         (("2025-11-01", "2025-12-31"), ("2026-01-01", "2026-01-31")),
         (("2025-12-01", "2026-01-31"), ("2026-02-01", "2026-02-28"))]
# Paramètres structurels FIGÉS (choisis sur le train uniquement : meilleur Sharpe de la grille)
FROZEN = dict(min_pts=80, hold=24, sl_k=4.0, tp_k=12.0)
GRID = dict(min_pts=(70, 80), hold=(12, 24), sl_k=(4.0, 6.0, 8.0), tp_k=(8.0, 12.0, 16.0))


def sl_(t):
    return slice(t[0], t[1])


def run(df, F, period, p):
    """Backtest sur une période ; les features sont calculées sur tout l'historique (causales)."""
    d, f = df[sl_(period)], F[sl_(period)]
    sg = score(f, d, p)
    tr, eq, orders = simulate(d, sg.signal, f.vol_unit, p, CAPITAL)
    return tr, eq, orders, metrics(tr, eq, CAPITAL)


def trade_bootstrap(tr, n_boot=10000, seed=0):
    """p-value unilatérale H0 : rendement net moyen par trade <= 0 (bootstrap par jour d'entrée)."""
    if len(tr) < 10:
        return np.nan
    g = tr.groupby(tr.entry_time.dt.normalize()).ret_equity.agg(["sum", "size"]).values
    rng = np.random.default_rng(seed)
    i = rng.integers(0, len(g), (n_boot, len(g)))
    m = g[i, 0].sum(1) / g[i, 1].sum(1)
    return float((m <= 0).mean())


def vbt_check(df, orders, p):
    """
    Contrôle croisé avec vectorbt : on rejoue le flux d'ordres dans Portfolio.from_orders
    (frais + slippage appliqués par vectorbt). Chaque bougie est dédoublée en 2 phases
    (open / intrabar) pour autoriser une entrée et un stop dans la même bougie.
    """
    n = len(df)
    idx = pd.DatetimeIndex(np.repeat(df.index.values, 2) + np.tile([0, 150], n).astype("timedelta64[s]"))
    close = np.empty(2 * n); close[0::2] = df.open.values; close[1::2] = df.close.values
    size = np.zeros(2 * n); price = close.copy()
    for i, phase, q, raw in orders:
        size[2 * i + phase] += q; price[2 * i + phase] = raw
    size[size == 0] = np.nan
    pf = vbt.Portfolio.from_orders(pd.Series(close, idx), size=pd.Series(size, idx), price=pd.Series(price, idx),
                                   fees=p.fee, slippage=p.slip, init_cash=CAPITAL * 100, freq="150s")
    # (cash volontairement surdimensionné : vectorbt n'a pas de marge/levier natif ; on compare le PnL)
    return pf


def fmt(m):
    if m.get("trades", 0) == 0:
        return "aucun trade"
    return (f"trades={m['trades']:4d}  win={m['winrate']:.1%}  PF={m['profit_factor']:.2f}  "
            f"ret={m['total_return']:+.2%}  maxDD={m['max_dd']:.2%}  Sharpe={m['sharpe']:+.2f}  "
            f"Sortino={m['sortino']:+.2f}  Calmar={m['calmar']:+.2f}  brut={m['avg_gross_bp']:+.1f}bp  "
            f"net={m['avg_net_bp']:+.1f}bp/trade")


def main(data_dir, out_dir):
    df = load(data_dir)
    F = build_features(df)
    Y = forward_returns(df)
    res = {}
    feats = [c for c in F.columns if c != "vol_unit"]

    # ------------------------------------------------------------------ 1. minage strict
    print("=" * 100, "\n1. MINAGE STRICT DES RÈGLES (train -> validation, p < 0.01 des deux côtés)")
    liq = df.volume >= df.volume[sl_(TRAIN)].quantile(0.05)
    R = mine(F[sl_(TRAIN)], Y[sl_(TRAIN)], F[sl_(VALID)], Y[sl_(VALID)], liq[sl_(TRAIN)], liq[sl_(VALID)], feats)
    n_sig = int((R.p_tr < 0.01).sum())
    print(f"   tests (règle × horizon) : {len(R)} | significatifs train p<0.01 : {n_sig} "
          f"(attendu par pur hasard : {len(R) * 0.01:.0f}) | répliqués en validation : {int(R.keep.sum())}")
    R.drop(columns=["conds", "n_tests"]).sort_values("p_tr").to_csv(f"{out_dir}/rules_all.csv", index=False)
    res["mining"] = dict(tests=len(R), sig_train=n_sig, replicated=int(R.keep.sum()))
    imp = rf_importance(F[sl_(TRAIN)], Y[sl_(TRAIN)], feats, 12)
    imp.to_csv(f"{out_dir}/rf_importance_h12.csv")

    # ------------------------------------------------------------------ 2. système figé
    print("=" * 100, "\n2. SYSTÈME FIGÉ (seuils calibrés sur oct.-déc., paramètres choisis sur le train)")
    p_tr = fit_thresholds(F[sl_(TRAIN)], df[sl_(TRAIN)], Params(**FROZEN))
    for name, per in (("train", TRAIN), ("validation", VALID)):
        _, _, _, m = run(df, F, per, p_tr); res[name] = m
        print(f"   {name:<12}: {fmt(m)}")
    pre = (TRAIN[0], VALID[1])
    p = fit_thresholds(F[sl_(pre)], df[sl_(pre)], Params(**FROZEN))
    tr, eq, orders, m = run(df, F, TEST, p)
    m["p_value_net_gt_0"] = trade_bootstrap(tr)
    res["test_final"] = m; res["params"] = asdict(p)
    print(f"   TEST FINAL  : {fmt(m)}   p(net>0)={m['p_value_net_gt_0']:.3f}")
    tr.to_csv(f"{out_dir}/trades_test_final.csv", index=False)
    eq.resample("1h").last().to_csv(f"{out_dir}/equity_test_final.csv")
    bh = df.close[sl_(TEST)]
    res["buy_hold_test"] = float(bh.iloc[-1] / bh.iloc[0] - 1)
    print(f"   (buy & hold sur la même période : {res['buy_hold_test']:+.2%})")
    by_side = tr.groupby("side").agg(n=("pnl", "size"), net_bp=("net_bp", "mean"), pnl=("pnl", "sum"))
    print("   par sens (-1 = short, 1 = long) :\n", by_side.round(2).to_string())
    res["test_by_side"] = by_side.reset_index().to_dict("records")

    # contrôle croisé vectorbt
    pf = vbt_check(df[sl_(TEST)], orders, p)
    v_end = float(pf.value().iloc[-1]) - CAPITAL * 100 + CAPITAL
    print(f"   contrôle vectorbt : capital final moteur = {eq.iloc[-1]:.2f} | vectorbt = {v_end:.2f} "
          f"(écart {abs(v_end - eq.iloc[-1]):.4f})")
    res["vbt_check"] = dict(engine=float(eq.iloc[-1]), vectorbt=v_end)

    # ------------------------------------------------------------------ 3. walk-forward
    print("=" * 100, "\n3. WALK-FORWARD (2 mois train -> 1 mois test, paramètres ré-optimisés à chaque fold)")
    wf_tr, wf = [], []
    keys = list(GRID)
    for k, (trn, tst) in enumerate(FOLDS, 1):
        best, best_sh = None, -np.inf
        for combo in itertools.product(*GRID.values()):
            pk = fit_thresholds(F[sl_(trn)], df[sl_(trn)], Params(**dict(zip(keys, combo))))
            mm = run(df, F, trn, pk)[3]
            if mm.get("trades", 0) >= 30 and mm["sharpe"] > best_sh:
                best, best_sh = pk, mm["sharpe"]
        t, e, _, mm = run(df, F, tst, best)
        wf.append(dict(fold=k, test=tst[0][:7], train_sharpe=best_sh,
                       **{q: getattr(best, q) for q in keys}, **mm))
        wf_tr.append(t)
        print(f"   fold {k} test {tst[0][:7]} [pts>={best.min_pts} hold={best.hold} sl={best.sl_k} tp={best.tp_k} "
              f"| Sharpe train {best_sh:+.2f}] -> {fmt(mm)}")
    pd.DataFrame(wf).to_csv(f"{out_dir}/walk_forward.csv", index=False)
    allt = pd.concat(wf_tr)
    res["walk_forward"] = wf
    res["wf_total"] = dict(trades=len(allt), avg_net_bp=float(allt.net_bp.mean()), winrate=float((allt.pnl > 0).mean()),
                           compounded_return=float(np.prod([1 + w["total_return"] for w in wf]) - 1),
                           p_value_net_gt_0=trade_bootstrap(allt))
    print(f"   cumul des 3 folds : {res['wf_total']}")

    # ------------------------------------------------------------------ 4. stress tests
    print("=" * 100, "\n4. STRESS TESTS sur le test final (système figé)")
    base = asdict(p)
    scen = {"base (frais 0.04 %, slippage 0.01 %)": {},
            "frais ×2": dict(fee=0.0008),
            "slippage ×2": dict(slip=0.0002),
            "frais ×2 + slippage ×2": dict(fee=0.0008, slip=0.0002),
            "funding perp 0.01 %/8h": dict(funding_8h=0.0001),
            "entrée au pire prix (high/low de t+1)": dict(worst_entry=True),
            "long seul (compatible spot)": dict(long_only=True),
            "sans frais ni slippage (edge brut)": dict(fee=0.0, slip=0.0)}
    res["stress"] = {}
    for name, ov in scen.items():
        mm = run(df, F, TEST, Params(**{**base, **ov}))[3]
        res["stress"][name] = mm
        print(f"   {name:<40}: {fmt(mm)}")

    json.dump(res, open(f"{out_dir}/results.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    out = sys.argv[2] if len(sys.argv) > 2 else "results"
    import os; os.makedirs(out, exist_ok=True)
    main(sys.argv[1], out)

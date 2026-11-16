# -*- coding: utf-8 -*-
"""
backtest_10m.py — Extension sur 10 mois (2025-10 -> 2026-07).

  A. Système FIGÉ en décembre 2025 (seuils et paramètres inchangés, lus dans results/results.json)
     appliqué à mars-juillet 2026 : 5 mois réellement jamais vus, aucun réglage refait.
  B. Réplication du thème "flux" au niveau des règles sur mars-juillet (seuils d'oct.-nov.).
  C. Nouveau minage strict avec plus de données : train oct.-fév., validation mars-avril,
     test final mai-juillet (les 3 derniers mois) pour toute règle qui survivrait.
  D. Walk-forward 4 mois train -> 1 mois test, 6 folds (tests : fév. à juil.).

Usage :  python backtest_10m.py <dossier_des_csv> [results_10m]
"""
import sys, os, json, itertools, warnings
from dataclasses import asdict
import numpy as np
import pandas as pd
from features import load, build_features, forward_returns, HORIZONS
from mine_rules import mine, evaluate, day_bootstrap
from system import Params, fit_thresholds
from backtest_wf import run, trade_bootstrap, vbt_check, fmt, sl_, GRID, CAPITAL

warnings.filterwarnings("ignore")
NEW = ("2026-03-01", "2026-07-31")
MONTHS = pd.period_range("2026-03", "2026-07", freq="M")


def month_span(m):
    return (str(m.start_time.date()), str(m.end_time.date()))


def main(data_dir, out_dir):
    df = load(data_dir); F = build_features(df); Y = forward_returns(df)
    res = {}
    feats = [c for c in F.columns if c != "vol_unit"]

    # ---------------------------------------------------------------- A. système figé
    print("=" * 100, "\nA. SYSTÈME FIGÉ EN DÉC. 2025 -> mars-juillet 2026 (aucun réglage refait)")
    here = os.path.dirname(os.path.abspath(__file__))
    p = Params(**json.load(open(f"{here}/results/results.json"))["params"])
    tr, eq, orders, m = run(df, F, NEW, p)
    m["p_value_net_gt_0"] = trade_bootstrap(tr)
    lo, hi = np.percentile(np.random.default_rng(0).choice(tr.net_bp.values, (10000, len(tr))).mean(1), [2.5, 97.5])
    m["net_bp_ci95"] = [float(lo), float(hi)]
    res["frozen_new"] = m
    print(f"   mars-juil.  : {fmt(m)}   p(net>0)={m['p_value_net_gt_0']:.3f}  IC95 net/trade [{lo:+.1f}, {hi:+.1f}] bp")
    bh = df.close[sl_(NEW)]; res["buy_hold_new"] = float(bh.iloc[-1] / bh.iloc[0] - 1)
    print(f"   (buy & hold : {res['buy_hold_new']:+.2%})")
    pf = vbt_check(df[sl_(NEW)], orders, p)
    v_end = float(pf.value().iloc[-1]) - CAPITAL * 100 + CAPITAL
    print(f"   contrôle vectorbt : moteur = {eq.iloc[-1]:.2f} | vectorbt = {v_end:.2f}")
    res["vbt_check"] = dict(engine=float(eq.iloc[-1]), vectorbt=v_end)
    tr.to_csv(f"{out_dir}/trades_frozen_new.csv", index=False)
    eq.resample("1h").last().to_csv(f"{out_dir}/equity_frozen_new.csv")
    res["frozen_by_month"] = []
    for mth in MONTHS:
        mm = run(df, F, month_span(mth), p)[3]; mm["month"] = str(mth); res["frozen_by_month"].append(mm)
        print(f"   {mth}     : {fmt(mm)}")
    by_side = tr.groupby("side").agg(n=("pnl", "size"), net_bp=("net_bp", "mean"), pnl=("pnl", "sum"))
    print("   par sens :", by_side.round(1).reset_index().to_dict("records"))
    res["frozen_by_side"] = by_side.reset_index().to_dict("records")
    scen = {"frais ×2": dict(fee=0.0008), "slippage ×2": dict(slip=0.0002),
            "frais ×2 + slippage ×2": dict(fee=0.0008, slip=0.0002),
            "funding perp 0.01 %/8h": dict(funding_8h=0.0001),
            "entrée au pire prix (high/low de t+1)": dict(worst_entry=True),
            "long seul (compatible spot)": dict(long_only=True),
            "sans frais ni slippage (edge brut)": dict(fee=0.0, slip=0.0)}
    res["stress"] = {}
    for name, ov in scen.items():
        mm = run(df, F, NEW, Params(**{**asdict(p), **ov}))[3]; res["stress"][name] = mm
        print(f"   {name:<40}: {fmt(mm)}")

    # ---------------------------------------------------------------- B. thème "flux" au niveau des règles
    print("=" * 100, "\nB. RÉPLICATION DU THÈME « FLUX » (|imb_48| >= q80 & vol_ratio > 1 ; seuil d'oct.-nov.)")
    d = np.sign(F.imb_48); base = (F.imb_48.abs() >= 0.13887) & (F.vol_ratio > 1.0)
    res["flow_theme"] = {}
    for name, per in (("train oct.-nov.", ("2025-10-08", "2025-11-30")), ("validation déc.", ("2025-12-01", "2025-12-31")),
                      ("janv.-fév.", ("2026-01-01", "2026-02-28")), ("mars-juil. (nouveau)", NEW)):
        row = f"   {name:<22}"
        for n in (12, 24):
            y = (Y[f"fwd_{n}"] * d)[sl_(per)][base[sl_(per)]]
            mu, pv, k = day_bootstrap(y)
            res["flow_theme"][f"{name} h{n}"] = dict(edge_bp=mu, p=pv, n=k)
            row += f" h={n}: {mu:+6.1f} bp (p={pv:.3f}, n={k})  |"
        print(row)

    # ---------------------------------------------------------------- C. nouveau minage strict
    print("=" * 100, "\nC. NOUVEAU MINAGE STRICT : train oct.-fév. -> validation mars-avril -> test mai-juil.")
    T, V, X = ("2025-10-08", "2026-02-28"), ("2026-03-01", "2026-04-30"), ("2026-05-01", "2026-07-31")
    liq = df.volume >= df.volume[sl_(T)].quantile(0.05)
    R = mine(F[sl_(T)], Y[sl_(T)], F[sl_(V)], Y[sl_(V)], liq[sl_(T)], liq[sl_(V)], feats)
    n_sig = int((R.p_tr < 0.01).sum())
    same = float((np.sign(R.edge_tr) == np.sign(R.edge_va))[R.p_tr < 0.01].mean())
    print(f"   tests : {len(R)} | significatifs train p<0.01 : {n_sig} (hasard : {len(R) * 0.01:.0f}) | "
          f"même signe en validation : {same:.0%} | répliqués p<0.01 : {int(R.keep.sum())}")
    res["mining_v2"] = dict(tests=len(R), sig_train=n_sig, same_sign=same, replicated=int(R.keep.sum()), survivors=[])
    for _, r in R[R.keep].iterrows():
        mu, pv, k = evaluate(F[sl_(X)], Y[sl_(X)], r.conds, liq[sl_(X)])[r.h]
        ok = (pv < 0.01) and (np.sign(mu) == np.sign(r.edge_tr))
        res["mining_v2"]["survivors"].append(dict(rule=r.rule, h=int(r.h), edge_tr=r.edge_tr, p_tr=r.p_tr, edge_va=r.edge_va,
                                                  p_va=r.p_va, edge_test=mu, p_test=pv, n_test=k, confirmed=bool(ok)))
        print(f"   {r.rule} [h={r.h}] train {r.edge_tr:+.1f} (p={r.p_tr:.3f}) | val {r.edge_va:+.1f} (p={r.p_va:.3f}) "
              f"| TEST {mu:+.1f} bp (p={pv:.3f}, n={k}) -> {'CONFIRMÉE' if ok else 'non confirmée'}")
    R.drop(columns=["conds", "n_tests"]).sort_values("p_tr").to_csv(f"{out_dir}/rules_all_v2.csv", index=False)

    # ---------------------------------------------------------------- D. walk-forward 4m / 1m
    print("=" * 100, "\nD. WALK-FORWARD 4 mois train -> 1 mois test (6 folds, paramètres ré-optimisés)")
    wf, wf_tr, keys = [], [], list(GRID)
    for k, tm in enumerate(pd.period_range("2026-02", "2026-07", freq="M"), 1):
        t0 = max(pd.Timestamp("2025-10-08"), (tm - 4).start_time)
        trn, tst = (str(t0.date()), str((tm - 1).end_time.date())), month_span(tm)
        best, best_sh = None, -np.inf
        for combo in itertools.product(*GRID.values()):
            pk = fit_thresholds(F[sl_(trn)], df[sl_(trn)], Params(**dict(zip(keys, combo))))
            mm = run(df, F, trn, pk)[3]
            if mm.get("trades", 0) >= 30 and mm["sharpe"] > best_sh:
                best, best_sh = pk, mm["sharpe"]
        t, e, _, mm = run(df, F, tst, best)
        wf.append(dict(fold=k, test=str(tm), train_sharpe=best_sh, **{q: getattr(best, q) for q in keys}, **mm)); wf_tr.append(t)
        print(f"   fold {k} test {tm} [pts>={best.min_pts} hold={best.hold} sl={best.sl_k} tp={best.tp_k} "
              f"| Sharpe train {best_sh:+.2f}] -> {fmt(mm)}")
    pd.DataFrame(wf).to_csv(f"{out_dir}/walk_forward_4m1m.csv", index=False)
    allt = pd.concat(wf_tr)
    res["walk_forward"] = wf
    res["wf_total"] = dict(trades=len(allt), avg_net_bp=float(allt.net_bp.mean()), winrate=float((allt.pnl > 0).mean()),
                           compounded_return=float(np.prod([1 + w["total_return"] for w in wf]) - 1),
                           positive_folds=int(sum(w["total_return"] > 0 for w in wf)), p_value_net_gt_0=trade_bootstrap(allt))
    print(f"   cumul : {res['wf_total']}")
    json.dump(res, open(f"{out_dir}/results_10m.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    out = sys.argv[2] if len(sys.argv) > 2 else "results_10m"
    os.makedirs(out, exist_ok=True)
    main(sys.argv[1], out)

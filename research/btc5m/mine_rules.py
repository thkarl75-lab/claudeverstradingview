# -*- coding: utf-8 -*-
"""
mine_rules.py — Découverte de règles (quantiles univariés + feuilles d'arbres de décision)
et validation statistique (bootstrap par blocs journaliers, réplication train -> validation).

Garde-fous anti-surapprentissage :
  * les seuils sont calculés sur le TRAIN uniquement ;
  * les rendements sont mesurés en EXCÈS de la moyenne de la période (sinon, dans un marché
    baissier, "vendre tout le temps" passerait pour une règle) ;
  * les p-values utilisent un bootstrap par JOUR (les rendements futurs se chevauchent et les
    signaux arrivent en grappes : un t-test naïf surestime massivement la significativité) ;
  * une règle n'est retenue que si elle est significative (p < 0.01) sur le train ET
    répliquée avec le même signe (p < 0.01) sur la validation.
"""
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor
from features import HORIZONS

NO_RULE = {"vol_unit", "hour", "ngram3"}        # pas de règle par quantile sur ces colonnes


def day_bootstrap(x: pd.Series, n_boot: int = 4000, seed: int = 0):
    """Moyenne + p-value bilatérale (H0 : moyenne = 0) par bootstrap de jours entiers."""
    x = x.dropna()
    if len(x) < 30:
        return np.nan, 1.0, len(x)
    day = x.index.normalize()
    s = x.groupby(day).sum().values
    n = x.groupby(day).size().values
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(s), size=(n_boot, len(s)))
    m = s[idx].sum(1) / n[idx].sum(1)
    mean = x.mean()
    p = 2 * min((m <= 0).mean(), (m >= 0).mean())
    return mean, max(p, 1 / n_boot), len(x)


def candidate_rules(F: pd.DataFrame, Y: pd.DataFrame, feats, q=(0.1, 0.9), depth=3, leaf_frac=0.03):
    """Génère les règles candidates sur le TRAIN. Une règle = liste de (feature, op, seuil)."""
    cands = []
    for col in feats:
        if col in NO_RULE:
            continue
        lo, hi = F[col].quantile(q[0]), F[col].quantile(q[1])
        cands.append([(col, "<=", float(lo))])
        cands.append([(col, ">", float(hi))])
    # n-grammes de 3 bougies : 8 motifs
    for code in range(8):
        cands.append([("ngram3", "==", float(code))])
    # feuilles d'arbres peu profonds (une forêt de 1 arbre par horizon)
    X = F[feats].copy()
    ok = X.notna().all(1)
    for n in HORIZONS:
        y = Y[f"fwd_{n}"]
        m = ok & y.notna()
        tree = DecisionTreeRegressor(max_depth=depth, min_samples_leaf=int(leaf_frac * m.sum()),
                                     random_state=0).fit(X[m], y[m] - y[m].mean())
        t = tree.tree_

        def walk(node, conds):
            if t.children_left[node] == -1:
                if conds:
                    cands.append(conds)
                return
            name, thr = feats[t.feature[node]], float(t.threshold[node])
            walk(t.children_left[node], conds + [(name, "<=", thr)])
            walk(t.children_right[node], conds + [(name, ">", thr)])
        walk(0, [])
    # dédoublonnage
    seen, out = set(), []
    for c in cands:
        key = tuple(sorted((a, b, round(d, 6)) for a, b, d in c))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def rule_mask(F: pd.DataFrame, conds) -> pd.Series:
    m = pd.Series(True, index=F.index)
    for col, op, thr in conds:
        m &= (F[col] <= thr) if op == "<=" else (F[col] > thr) if op == ">" else (F[col] == thr)
    return m


def rule_name(conds) -> str:
    return " & ".join(f"{c} {op} {thr:.3g}" for c, op, thr in conds)


def evaluate(F, Y, conds, liquid):
    """Edge (bp, en excès de la moyenne de période) + p-value pour chaque horizon."""
    m = rule_mask(F, conds) & liquid
    res = {}
    for n in HORIZONS:
        y = Y[f"fwd_{n}"]
        res[n] = day_bootstrap((y - y.mean())[m])
    return res


def mine(F_tr, Y_tr, F_va, Y_va, liq_tr, liq_va, feats, alpha=0.01, verbose=False):
    """Retourne la table des règles retenues (significatives train ET répliquées en validation)."""
    cands = candidate_rules(F_tr, Y_tr, feats)
    rows = []
    for conds in cands:
        e_tr, e_va = evaluate(F_tr, Y_tr, conds, liq_tr), evaluate(F_va, Y_va, conds, liq_va)
        for n in HORIZONS:
            (mt, pt, nt), (mv, pv, nv) = e_tr[n], e_va[n]
            rows.append(dict(rule=rule_name(conds), conds=conds, h=n, edge_tr=mt, p_tr=pt, n_tr=nt,
                             edge_va=mv, p_va=pv, n_va=nv))
    R = pd.DataFrame(rows)
    R["keep"] = (R.p_tr < alpha) & (R.p_va < alpha) & (np.sign(R.edge_tr) == np.sign(R.edge_va))
    R["n_tests"] = len(R)
    return R


def rf_importance(F, Y, feats, n=12):
    """Importance des features par permutation-free MDI d'une forêt aléatoire (indicatif)."""
    X = F[feats]
    m = X.notna().all(1) & Y[f"fwd_{n}"].notna()
    rf = RandomForestRegressor(n_estimators=150, max_depth=6, min_samples_leaf=200, n_jobs=-1,
                               random_state=0, max_features=0.33).fit(X[m], Y.loc[m, f"fwd_{n}"])
    return pd.Series(rf.feature_importances_, index=feats).sort_values(ascending=False)

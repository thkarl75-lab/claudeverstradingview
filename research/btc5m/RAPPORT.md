# BTC/USDT 5m — Recherche de règles « from scratch » : rapport

## Verdict (mis à jour avec 10 mois de données)

**Aucun edge exploitable. Les 5 mois supplémentaires (mars–juillet 2026) invalident le seul thème retenu.**

- Le système figé en décembre 2025, appliqué sans aucun réglage à mars–juillet 2026 : **−65,3 %**, 396 trades, profit factor 0,55, les 5 mois perdants. Même l'edge **brut** est négatif (−4,3 bp par trade).
- Le thème « continuation du flux » s'éteint puis s'inverse : +27 bp (train) → +16 bp (déc.) → +8 bp (janv.–fév.) → **−7 bp** (mars–juil.). C'est la signature d'un sur-apprentissage.
- Nouveau minage strict avec 5 mois de train : 384 tests, 7 significatifs à p < 0,01 (4 attendus par hasard), **0 répliqué** en validation.
- Walk-forward 4 mois → 1 mois : **0 fold positif sur 6**, −44,9 % cumulé.

Le code Pine et le backtest sont livrés comme outils de recherche. **Ce système ne doit pas être tradé.**

## Mise à jour : extension à 10 mois

Données : 2025-10-01 → 2026-07-31, 87 552 bougies, aucune manquante. Les nouveaux mois couvrent d'autres régimes que la baisse initiale (mars +2 %, avril +12 %, mai −3 %, juin −20 %, juillet +7 %), avec une volatilité 5m plus basse en avril–mai (12 et 9 bp contre 16 bp en moyenne auparavant). Script : `backtest_10m.py`, sorties dans `results_10m/`.

**A. Système figé (seuils et paramètres de décembre 2025, inchangés) sur mars–juillet 2026**

| Période | Trades | Winrate | PF | Rendement | Drawdown max | Sharpe | Brut / trade | Net / trade |
|---|---|---|---|---|---|---|---|---|
| **Mars–juillet** | **396** | **30,3 %** | **0,55** | **−65,3 %** | **−69,4 %** | **−7,8** | **−4,3 bp** | **−14,3 bp** |
| Mars | 76 | 31,6 % | 0,78 | −8,1 % | −17,1 % | −2,2 | +3,7 bp | −6,3 bp |
| Avril | 77 | 24,7 % | 0,44 | −23,6 % | −24,3 % | −14,9 | −10,7 bp | −20,7 bp |
| Mai | 64 | 26,6 % | 0,33 | −25,6 % | −26,8 % | −12,4 | −11,4 bp | −21,4 bp |
| Juin | 86 | 33,7 % | 0,55 | −19,6 % | −21,3 % | −8,6 | −6,9 bp | −16,9 bp |
| Juillet | 93 | 33,3 % | 0,64 | −17,4 % | −25,4 % | −6,5 | +1,8 bp | −8,2 bp |

Sortino −8,6, Calmar −1,3. Intervalle de confiance à 95 % du net par trade : [−20,8 ; −7,8] bp. Longs (183 trades, −11,1 bp) et shorts (213 trades, −17,1 bp) perdent tous les deux. Acheter et conserver : −6,2 %. Contrôle vectorbt : capital final identique (3 467,65 USDT).

La perte en capital est amplifiée par la taille : en basse volatilité le stop est plus serré, donc la position atteint le plafond de levier de 3×.

Stress tests sur la même période : frais ×2 → −81,1 % ; slippage ×2 → −71,1 % ; **frais ×2 et slippage ×2 → −84,2 %** ; funding → −65,8 % ; entrée au pire prix → −94,4 % ; long seul → −36,5 % ; sans aucun coût → −28,8 %. La variante « long seul », légèrement positive sur janv.–fév., perd elle aussi : c'était bien du bruit.

**B. Le thème « flux » au niveau des règles** (rendement dans le sens du flux, `|imb_48|` ≥ 0,139 et `vol_ratio > 1`)

| Période | 12 bougies | 24 bougies |
|---|---|---|
| Train oct.–nov. | +15,6 bp (p = 0,016) | +27,3 bp (p = 0,017) |
| Validation déc. | +9,2 bp (p = 0,16) | +15,7 bp (p = 0,15) |
| Janv.–fév. | +1,5 bp (p = 0,84) | +7,7 bp (p = 0,54) |
| Mars–juil. | −4,4 bp (p = 0,12) | −7,1 bp (p = 0,11) |

L'inversion de mars–juillet n'est pas significative non plus : elle ne justifie pas de trader la règle à l'envers.

**C. Nouveau minage strict** (train oct.–fév., validation mars–avril, test mai–juillet réservé) : 384 tests, 7 significatifs en train, dont 43 % seulement gardent leur signe en validation, 0 répliqué. Avec deux fois et demie plus de données d'entraînement, le nombre de « découvertes » en train se rapproche du niveau du hasard. Le test mai–juillet n'a pas eu à servir.

**D. Walk-forward 4 mois → 1 mois** (paramètres ré-optimisés à chaque fold)

| Fold | Test | Trades | Winrate | PF | Rendement | Net / trade |
|---|---|---|---|---|---|---|
| 1 | 2026-02 | 65 | 43,1 % | 0,98 | −0,3 % | −0,5 bp |
| 2 | 2026-03 | 67 | 37,3 % | 0,88 | −2,1 % | −4,0 bp |
| 3 | 2026-04 | 78 | 26,9 % | 0,42 | −14,3 % | −23,0 bp |
| 4 | 2026-05 | 60 | 26,7 % | 0,26 | −16,7 % | −27,7 bp |
| 5 | 2026-06 | 101 | 37,6 % | 0,54 | −12,9 % | −21,1 bp |
| 6 | 2026-07 | 85 | 41,2 % | 0,68 | −9,3 % | −7,0 bp |
| Cumul | | 456 | 35,7 % | | −44,9 % | −14,2 bp |

Le Sharpe du meilleur jeu de paramètres en train est négatif sur les 6 folds : en conditions réelles, un tel système n'aurait jamais été mis en production.

**Conclusion** : sur 10 mois et plusieurs régimes, des features dérivées de l'OHLCV 5m ne donnent aucune règle directionnelle qui survive à 10 bp de coûts. Les sections ci-dessous décrivent l'étude initiale sur 5 mois et restent valables comme description de la méthode ; leurs chiffres de performance sont remplacés par ceux ci-dessus.

## Test multi-timeframe avec indicateurs classiques comme filtres

**Aucun edge : les 20 combinaisons sont perdantes, et l'edge brut est déjà nul avant frais.** Direction à abandonner.

Script : `backtest_mtf.py`, sorties dans `results_mtf/`. Filtre 1H : close au-dessus de l'EMA 200 et RSI 14 > 50 (long), l'inverse pour short. Filtre 15m : close au-dessus ou en dessous de l'EMA 50. Bougies 1H et 15m reconstruites depuis les 5m ; une valeur de timeframe supérieur n'est utilisée qu'une fois sa bougie clôturée. 5 déclencheurs 5m (événements de prix) × 4 configurations de filtres, fixés à l'avance, sans optimisation. Sorties identiques au système précédent (stop 4 ×, objectif 12 × la volatilité maison, 24 bougies). Période : 2025-10-15 → 2026-07-31. Seuil de Bonferroni : p < 0,0025.

| Déclencheur | Filtres | Trades | Brut / trade | Net / trade | PF | Sharpe | Net / trade (frais et slippage ×2) | Verdict |
|---|---|---|---|---|---|---|---|---|
| T1 cassure de la bougie précédente | aucun | 3 619 | −1,9 bp | −11,9 bp | 0,54 | −14,5 | −22,1 bp | pas d'edge |
| | 1H | 2 643 | −2,4 bp | −12,4 bp | 0,57 | −13,2 | −22,4 bp | pas d'edge |
| | 15m | 3 592 | −0,7 bp | −10,7 bp | 0,59 | −13,6 | −19,5 bp | pas d'edge |
| | 1H + 15m | 2 274 | −2,2 bp | −12,2 bp | 0,59 | −12,4 | −21,2 bp | pas d'edge |
| T2 rejet (mèche > 50 % du range) | aucun | 2 906 | +0,2 bp | −9,8 bp | 0,65 | −10,8 | −19,5 bp | pas d'edge |
| | 1H | 1 493 | −0,3 bp | −10,3 bp | 0,64 | −8,0 | −20,1 bp | pas d'edge |
| | 15m | 1 928 | +0,6 bp | −9,4 bp | 0,64 | −8,8 | −19,3 bp | pas d'edge |
| | 1H + 15m | 1 171 | +0,7 bp | −9,3 bp | 0,67 | −6,6 | −19,4 bp | pas d'edge |
| T3 expansion de range + volume > moyenne 20 | aucun | 3 187 | −3,4 bp | −13,4 bp | 0,57 | −14,6 | −23,0 bp | pas d'edge |
| | 1H | 1 730 | −1,8 bp | −11,8 bp | 0,60 | −9,4 | −21,8 bp | pas d'edge |
| | 15m | 2 532 | −2,1 bp | −12,1 bp | 0,60 | −11,2 | −21,3 bp | pas d'edge |
| | 1H + 15m | 1 454 | −1,3 bp | −11,3 bp | 0,62 | −8,2 | −21,6 bp | pas d'edge |
| T4 cassure après repli de 3 bougies | aucun | 3 443 | −2,0 bp | −12,0 bp | 0,62 | −14,8 | −21,0 bp | pas d'edge |
| | 1H | 2 214 | −2,0 bp | −12,0 bp | 0,58 | −11,4 | −21,5 bp | pas d'edge |
| | 15m | 2 798 | −0,9 bp | −10,9 bp | 0,58 | −13,2 | −20,8 bp | pas d'edge |
| | 1H + 15m | 1 743 | −1,1 bp | −11,1 bp | 0,61 | −10,0 | −21,1 bp | pas d'edge |
| T5 cassure du range des 12 bougies | aucun | 3 242 | −2,1 bp | −12,1 bp | 0,62 | −13,4 | −22,1 bp | pas d'edge |
| | 1H | 1 524 | −1,8 bp | −11,8 bp | 0,61 | −10,2 | −21,6 bp | pas d'edge |
| | 15m | 2 585 | −1,9 bp | −11,9 bp | 0,62 | −12,7 | −22,0 bp | pas d'edge |
| | 1H + 15m | 1 451 | −1,5 bp | −11,5 bp | 0,61 | −9,7 | −21,3 bp | pas d'edge |

Le drawdown maximal dépasse 87 % pour les 20 combinaisons (le compte est pratiquement vidé) ; p(net > 0) = 1,00 partout.

- **Les filtres réduisent le nombre de trades, pas la perte par trade.** Ils font passer le net par trade de −12 à −11 bp au mieux : ils limitent les dégâts en tradant moins.
- **Les filtres n'ont pas de contenu directionnel.** Le rendement dans le sens du filtre 1H, mesuré seul, vaut −0,7 bp à 1 h, −1,2 bp à 2 h, −2,4 bp à 4 h et −2,2 bp à 12 h (p entre 0,4 et 0,8). Le résultat ne dépend donc pas du choix des sorties.
- **Walk-forward 4 mois → 1 mois** (meilleure combinaison du train tradée le mois suivant) : « T2 + 1H + 15m » est choisie aux 6 folds avec un Sharpe d'entraînement toujours négatif ; 0 fold positif, −75,3 % cumulé, −11,6 bp nets par trade sur 719 trades.
- **Comparaison** : sur mars–juillet 2026, le système « from scratch » perdait 65,3 % ; ici la meilleure combinaison perd 71,2 % et la pire 98,8 %. Les systèmes multi-timeframe tradent 3 à 9 fois plus souvent et paient donc plus de frais.

Aucun code Pine n'est fourni pour cette direction, faute d'edge à coder.

## Écarts par rapport à la demande

| Demande | Réalité | Conséquence |
|---|---|---|
| ~13 mois, ~112 000 bougies | 5 mois au départ, puis **10 mois** (2025-10 → 2026-07, 87 552 bougies) | Étude initiale sur 5 mois ; extension sur 10 mois ci-dessus |
| Spot | Les fichiers sont au format klines **Binance USDT-M Futures** (perpétuel) | Longs et shorts testés ; funding testé en scénario ; variante « long seul » fournie |
| 3 derniers mois en test final | 2 derniers mois (sinon il ne restait que 2 mois pour tout le reste) | Test final = janv.–fév. 2026 |
| Walk-forward 4 mois / 1 mois | 3 folds de 2 mois train → 1 mois test | Le fold 1 teste décembre, qui a aussi servi de validation à la conception |
| Indicateur Pine testé | **Non compilé ni exécuté dans TradingView** (pas d'accès depuis cet environnement) | À vérifier à la première compilation |

Le téléchargement des 8 mois manquants depuis l'archive publique Binance a été bloqué par la politique réseau de l'environnement. Le pipeline est relançable tel quel sur 13 mois (constantes de dates en tête de `backtest_wf.py`).

Découpage : train 2025-10-08 → 2025-11-30 (la première semaine amorce les fenêtres longues), validation décembre 2025, test final janvier–février 2026.

## 1. Analyse exploratoire (5 mois réels)

**Contexte de marché** : 113 989 → 66 937 USDT, soit −41 % (plus haut 126 208, plus bas 59 800). C'est un marché baissier quasi continu : toute règle « short » paraît bonne si on ne corrige pas la dérive. Tous les edges ci-dessous sont donc mesurés en excès de la moyenne de la période.

**Rendements 5m**

| Statistique | Valeur |
|---|---|
| Écart-type | 16,4 bp (volatilité annualisée 53 %) |
| Médiane de \|r\| | 6,5 bp |
| Skewness / kurtosis en excès | −2,1 / 165 (queues très épaisses) |
| Min / max | −807 bp / +475 bp |
| Médiane de \|r\| à 3 / 6 / 12 / 24 bougies | 11 / 16 / 22 / 30 bp |

Le coût aller-retour imposé (0,08 % de frais + 0,02 % de slippage = **10 bp**) dépasse le mouvement médian d'une bougie et représente un tiers du mouvement médian à 2 h. C'est la contrainte qui domine tout le reste.

**Autocorrélation** : rendements légèrement anti-corrélés (lag 1 : −0,017 ; lag 2 : −0,026 ; seuil de bruit ±0,010), ratio de variance 0,96 à 3 bougies et 0,87 à 24. Retour à la moyenne réel mais minuscule (bien moins d'un bp). La volatilité, elle, est très persistante (autocorrélation de \|r\| : 0,36 au lag 1, 0,14 à 24 h).

**Saisonnalité intraday (UTC)**

| Session | Écart-type 5m | Range moyen | Volume moyen | Rendement moyen (t) |
|---|---|---|---|---|
| Asie 0–7h | 14,1 bp | 16,9 bp | 446 BTC | −0,10 bp (−0,8) |
| Europe 7–13h | 12,3 bp | 15,3 bp | 446 BTC | −0,05 bp (−0,4) |
| US 13–21h | 19,1 bp | 25,1 bp | 835 BTC | −0,28 bp (−1,8) |
| Fin de journée 21–24h | 20,1 bp | 18,4 bp | 413 BTC | +0,10 bp (+0,4) |

La saisonnalité porte sur la **volatilité et le volume** (pic 14–16h UTC : range ×2, volume ×2,5 ; week-end : range −40 %), pas sur la direction. Aucune heure ni aucun jour n'a de rendement moyen significatif une fois corrigé pour 24 + 7 tests.

**Microstructure** : body ratio moyen 0,50, mèches 0,25 / 0,25, position du close 0,50, 49,8 % de bougies haussières : symétrie parfaite. Gaps inexistants (moyenne 0,007 bp), ce qui est normal sur un perpétuel coté en continu. N-grammes de 3 bougies : seul « UUU » ressort (−1,5 bp à 3 bougies, t = −4,5), trop petit pour être tradé.

**Volume** : corrélation volume / \|rendement\| de 0,69 dans la même bougie et de 0,42 avec la bougie suivante (le volume prédit l'amplitude). Corrélation volume / rendement signé : −0,09. Le ratio d'achats taker explique le rendement de la bougie courante (0,47) mais pas celui de la suivante (−0,005).

**Régimes** : KMeans à 4 clusters sur des features 4h (range, tendance, efficacité, volume relatif) donne un régime calme (34 % du temps, range 10 bp, persistance 0,96), un régime volatil sans direction (32 %), une tendance baissière (13 %) et une tendance haussière (15 %). Un HMM à 3 états sur (rendement, log-range) sépare trois niveaux de volatilité : 4 / 10 / 31 bp d'écart-type. Les régimes distinguent très bien la volatilité, très peu la direction future.

## 2. Features créées

38 features, toutes causales (calculées à la clôture de t), définies dans `features.py`.

| Famille | Features | Constat statistique (train → validation) |
|---|---|---|
| Anatomie de bougie | `body_ratio`, `upper_wick`, `lower_wick`, `close_pos`, `wick_asym_12` | Aucun pouvoir prédictif répliqué |
| Volatilité maison | `vol_unit` (médiane 4h de (high−low)/close), `rng_rel`, `vol_ratio` (1h/24h), `vol_regime` (4h/7j) | `vol_ratio` : 1re importance en forêt aléatoire (0,145) ; conditionne l'amplitude, pas le sens |
| Momentum normalisé | `mom_1…288`, `eff_12/48`, `chan_pos_12/48/288`, `vw_dev_48/288` | IC poolés non significatifs (\|z\| < 2) |
| Moments glissants | `skew_48`, `kurt_48` | Rien |
| Volume | `rel_vol`, `rel_vol_6`, `imb_3/12/48` (volume signé par la position du close), `effort` | `imb_48` : 2e importance (0,105) ; base du seul thème cohérent |
| Séquences | `ngram3`, `run_len`, `up_frac_12` | Effet « UUU » trop faible |
| Temps | `hour_sin/cos`, `dow_sin/cos` | Rien sur la direction |
| Taker (hors Pine) | `tk_imb_1/12/48`, `tk_trade_size` | `tk_imb_48` : IC +0,06 à +0,08 en train (z ≈ 2,4), +0,04 à +0,06 en validation (z ≈ 1,2) ; non retenu |

Piège évité : un premier calcul d'IC « par jour » donnait des t-stats de −10 pour `vw_dev_288` et `chan_pos_288`. C'est un artefact : classer un niveau de prix et un rendement futur à l'intérieur de la même fenêtre crée une corrélation négative mécanique. En IC poolé avec bootstrap par jour, l'effet disparaît.

## 3. Règles découvertes

**Méthode** (`mine_rules.py`) : déciles extrêmes de chaque feature, 8 motifs n-grammes, feuilles d'arbres de décision de profondeur 3 (une par horizon), soit 101 règles × 4 horizons. Seuils calculés sur le train. P-values par bootstrap de jours entiers, parce que les rendements futurs se chevauchent et que les signaux arrivent en grappes.

**Résultat strict : 0 règle retenue.** Parmi les 21 significatives en train, seules 62 % gardent le même signe en validation.

Les candidates les plus proches (edge en bp, en excès de la moyenne de période) :

| Règle | Horizon | Train (p) | Validation (p) |
|---|---|---|---|
| `imb_48 ≤ −0,18` et `vol_ratio > 1,19` | 24 | −61,4 (0,010) | −32,2 (0,060) |
| idem | 12 | −39,3 (0,002) | −15,6 (0,108) |
| `imb_48 > −0,18`, `vol_ratio ≤ 0,91`, `eff_12 > 0,50` | 12 | −10,8 (0,002) | −8,4 (0,020) |
| `imb_48 > −0,17`, `vol_ratio > 0,87`, `kurt_48 ≤ 1,52` | 6 | +4,3 (0,001) | +2,6 (0,230) |

**Thème exploratoire retenu faute de mieux** : continuation du flux. Quand `|imb_48|` dépasse son quantile 80 % et que `vol_ratio > 1`, le rendement dans le sens du flux est de +27,3 bp à 24 bougies en train (p = 0,018) et de +15,7 bp en validation (p = 0,13). L'effet a le bon signe côté long et côté short, ce qui le distingue d'un simple biais baissier, mais il ne passe pas le seuil de 1 %.

Ces chiffres sont des moyennes sur des bougies qui se chevauchent. En simulation à une position à la fois, l'edge brut tombe à 8–13 bp par trade : les signaux arrivent en grappes et le backtest n'en prend qu'un par grappe.

## 4. Système construit

Défini dans `system.py`, reproduit dans `btc5m_flow_confluence.pine`.

**Score de confluence** (points, sens = signe de `imb_48`, score affiché = 50 ± points/2) :

| Condition | Points |
|---|---|
| Pression 4h : `\|imb_48\|` ≥ quantile 80 % (0,138) | 30 (obligatoire) |
| Pression forte : ≥ quantile 90 % (0,176) | 10 |
| Expansion : `vol_ratio` ≥ 1,0 (filtre de régime) | 20 (obligatoire) |
| Expansion forte : `vol_ratio` ≥ 1,2 | 10 |
| Volume relatif 30 min ≥ 1,5 | 10 |
| Efficacité 4h ≥ 0,15 | 10 |
| Repli de 3 bougies contre le flux | 10 |

- **Signal** : BUY ou SELL si les deux conditions obligatoires sont vraies, volume ≥ percentile 5 % (66,5 BTC) et points ≥ 80 ; NEUTRAL sinon.
- **Stop / objectif** : 4 × et 12 × `vol_unit` (médiane 4h du range relatif, ≈ 16 bp en médiane, soit un stop d'environ 64 bp). Sortie temporelle après 24 bougies.
- **Taille** : risque de 1 % du capital par trade, levier plafonné à 3×, participation plafonnée à 1 % du volume de la bougie d'exécution.
- **Exécution** : signal à la clôture de t, entrée à l'open de t+1 avec slippage défavorable ; si stop et objectif sont touchés dans la même bougie, le stop passe en premier ; gap au-delà du stop exécuté à l'open.

Les paramètres (points, durée, stop, objectif) sont le meilleur Sharpe d'une grille de 72 combinaisons sur le train. **Toutes les combinaisons de la grille ont un Sharpe négatif sur le train**, et la meilleure vaut −0,45.

Les trois conditions à 10 points (volume relatif, efficacité, repli) ont été choisies en regardant train et validation ensemble : la validation n'est donc pas un test indépendant pour elles.

## 5. Performance

Capital initial 10 000 USDT, frais 0,04 % par côté, slippage 0,01 % par exécution.

| Période | Trades | Winrate | Profit factor | Rendement | Drawdown max | Sharpe | Sortino | Calmar | Brut / trade | Net / trade |
|---|---|---|---|---|---|---|---|---|---|---|
| Train (oct.–nov.) | 136 | 47,1 % | 0,92 | −3,6 % | −11,7 % | −0,45 | −0,76 | −1,90 | +12,6 bp | +2,6 bp |
| Validation (déc.) | 86 | 39,5 % | 1,08 | +3,2 % | −12,2 % | +1,09 | +1,76 | +3,63 | +8,5 bp | −1,5 bp |
| **Test final (janv.–fév.)** | **145** | **35,9 %** | **0,89** | **−7,8 %** | **−18,5 %** | **−1,15** | **−1,68** | **−2,14** | **+9,1 bp** | **−0,9 bp** |

Sur le test final : 54 stops (−78 bp nets en moyenne), 15 objectifs (+133 bp), 76 sorties temporelles (+27 bp). Les 95 shorts perdent 840 USDT (−4,6 bp par trade), les 50 longs gagnent 56 USDT (+6,1 bp). Le rendement en capital est pire que la moyenne par trade ne le suggère parce que la taille est plus grosse quand la volatilité est basse. Acheter et conserver sur la même période : −23,7 %.

Sharpe, Sortino et Calmar sont calculés sur rendements journaliers annualisés en √365. Sur un ou deux mois, ces ratios sont très bruités.

**Walk-forward** (paramètres ré-optimisés sur chaque fenêtre de train)

| Fold | Test | Paramètres choisis | Trades | Winrate | PF | Rendement | Sharpe | Net / trade |
|---|---|---|---|---|---|---|---|---|
| 1 | 2025-12 | pts ≥ 80, 24 bougies, stop 4, objectif 12 | 86 | 39,5 % | 1,08 | +3,2 % | +1,09 | −1,5 bp |
| 2 | 2026-01 | pts ≥ 80, 24 bougies, stop 8, objectif 16 | 63 | 31,7 % | 0,69 | −6,8 % | −3,53 | −14,0 bp |
| 3 | 2026-02 | pts ≥ 70, 24 bougies, stop 8, objectif 12 | 75 | 48,0 % | 1,06 | +1,1 % | +0,77 | +2,0 bp |
| Cumul | | | 224 | 40,2 % | | −2,7 % | | −3,9 bp |

p(net > 0) sur les 224 trades : 0,56. Rien ne distingue ce résultat du hasard.

**Contrôle croisé** : le flux d'ordres rejoué dans `vectorbt.Portfolio.from_orders` donne le même capital final que le moteur maison (9 216,07 USDT, écart nul).

## 6. Stress tests (test final, système figé)

| Scénario | Rendement | Drawdown max | Sharpe | PF | Net / trade |
|---|---|---|---|---|---|
| Base | −7,8 % | −18,5 % | −1,15 | 0,89 | −0,9 bp |
| Frais ×2 | −24,5 % | −29,0 % | −4,30 | 0,68 | −8,9 bp |
| Slippage ×2 | −15,2 % | −23,8 % | −2,41 | 0,79 | −3,5 bp |
| **Frais ×2 et slippage ×2** | **−30,8 %** | **−34,6 %** | **−5,37** | **0,60** | **−11,5 bp** |
| Funding perp 0,01 % / 8 h | −8,2 % | −18,7 % | −1,21 | 0,89 | −0,9 bp |
| Entrée au pire prix (high/low de t+1) | −67,9 % | −68,3 % | −11,3 | 0,28 | −31,0 bp |
| Long seul (compatible spot) | +0,7 % | −8,0 % | +0,31 | 1,03 | +6,1 bp |
| Sans frais ni slippage | +15,9 % | −12,7 % | +2,57 | 1,24 | +8,4 bp |

La variante « long seul » est positive sur 50 trades dans un marché à −24 % : c'est un résultat a posteriori sur un échantillon minuscule, pas une découverte. La ligne sans coûts montre qu'il y a peut-être un petit effet brut, mais il est inférieur aux frais taker.

## 7. Limites et risque de sur-apprentissage

- **Un seul régime de marché.** 5 mois de baisse continue. Rien ne dit comment ces features se comportent en marché haussier ou latéral.
- **Tests multiples.** 404 tests de règles, puis 72 combinaisons de paramètres, puis une vingtaine de conditions de confirmation. Les p-values affichées ne sont pas corrigées ; avec correction, rien ne survit.
- **Validation contaminée.** Les conditions de confirmation et le thème lui-même ont été choisis en regardant décembre. Seuls janvier et février sont réellement hors échantillon, et ils ont été évalués une seule fois.
- **Échantillons courts.** 145 trades sur le test final ; l'intervalle de confiance sur le net par trade est large (de l'ordre de ±15 bp).
- **Hypothèses d'exécution.** Le slippage fixe de 1 bp est optimiste pendant les phases d'expansion, qui sont précisément celles où le système trade. Le scénario « pire prix » borne l'autre extrême.
- **Frais.** Le taker USDT-M standard de Binance est aujourd'hui plutôt à 0,05 % qu'à 0,04 %, ce qui aggrave le résultat.
- **Pine.** Le script n'utilise aucun `ta.*` (boucles, sommes et médianes écrites à la main). Il n'a pas été compilé dans TradingView. Ses seuils sont figés sur BINANCE:BTCUSDT.P en 5m ; le KMeans et le HMM n'y sont pas portés, le filtre de régime y est le seuil d'expansion.

**Ce qui pourrait changer la conclusion** : une exécution maker (frais 0,02 %, mais risque de non-exécution et de sélection adverse à modéliser), un horizon plus long (15m à 1h, où les coûts pèsent moins), ou les 13 mois complets pour retester le thème « flux » sur d'autres régimes.

## Fichiers

| Fichier | Contenu |
|---|---|
| `features.py` | Chargement des CSV et feature engineering |
| `mine_rules.py` | Génération de règles, bootstrap par jour, importance par forêt aléatoire |
| `system.py` | Score de confluence, signaux, moteur de backtest, métriques |
| `backtest_wf.py` | Pipeline initial (5 mois) : minage, test final, walk-forward, stress tests, contrôle vectorbt |
| `backtest_10m.py` | Extension 10 mois : système figé sur mars–juil., réplication du thème, nouveau minage, walk-forward 4 mois / 1 mois |
| `btc5m_flow_confluence.pine` | Indicateur Pine Script v6 |
| `backtest_mtf.py` | Test multi-timeframe : filtres EMA/RSI en 1H et 15m, déclencheurs de prix en 5m, 20 combinaisons |
| `results_mtf/` | `combos.csv`, `walk_forward.csv`, `results_mtf.json` |
| `results_10m/` | Résultats de l'extension (`results_10m.json`, trades, equity, walk-forward, 384 tests) |
| `results/` | `rules_all.csv` (les 404 tests), `walk_forward.csv`, `trades_test_final.csv`, `equity_test_final.csv`, `results.json` |

Relancer : `python backtest_wf.py <dossier_des_csv> results` (dépendances : pandas, numpy, scipy, scikit-learn, vectorbt).

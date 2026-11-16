# BTC/USDT 5m — Recherche de règles « from scratch » : rapport

## Verdict

**Aucun edge exploitable net de frais n'a été trouvé.**

- Minage strict : 404 tests (règle × horizon), 21 significatifs à p < 0,01 sur le train (≈ 4 attendus par hasard), **0 répliqué à p < 0,01 en validation**.
- Le meilleur thème « exploratoire » (continuation du flux en phase d'expansion) a un edge **brut** d'environ +9 bp par trade hors échantillon, soit moins que le coût aller-retour de 10 bp.
- Test final jamais vu (janv.–fév. 2026) : **−7,8 %**, Sharpe −1,15, profit factor 0,89, p(net > 0) = 0,70.
- Avec frais ×2 et slippage ×2 : **−30,8 %**. L'edge ne « disparaît » pas au stress test, il n'existait déjà pas en base.

Le code Pine et le backtest sont livrés comme outils de recherche, pas comme système à trader.

## Écarts par rapport à la demande

| Demande | Réalité | Conséquence |
|---|---|---|
| ~13 mois, ~112 000 bougies | **5 mois** (2025-10-01 → 2026-02-28), 43 488 bougies, aucune manquante | Découpage adapté (ci-dessous) ; puissance statistique plus faible |
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
| `backtest_wf.py` | Pipeline complet : minage, test final, walk-forward, stress tests, contrôle vectorbt |
| `btc5m_flow_confluence.pine` | Indicateur Pine Script v6 |
| `results/` | `rules_all.csv` (les 404 tests), `walk_forward.csv`, `trades_test_final.csv`, `equity_test_final.csv`, `results.json` |

Relancer : `python backtest_wf.py <dossier_des_csv> results` (dépendances : pandas, numpy, scipy, scikit-learn, vectorbt).

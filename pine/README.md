# Scripts Pine

Sources Pine Script versionnées du dépôt. Contrairement à `scripts/current.pine`
(fichier de travail, ignoré par git, utilisé par la boucle push/pull), les fichiers
d'ici sont suivis par git : une version connue comme fonctionnelle peut donc toujours
être renvoyée vers TradingView.

## Scripts

| Fichier | Type | Pine | Overlay | Licence |
|---|---|---|---|---|
| `smart-money-concepts.pine` | Indicateur | v5 | Oui | CC BY-NC-SA 4.0 — © LuxAlgo |

### `smart-money-concepts.pine`

Indicateur de structure Smart Money Concepts (SMC). Il dessine, sur le graphique de prix :

- **Structure swing** — lignes et labels BOS / CHoCH sur les pivots swing (`Show Swing Structure`, longueur de pivot via `Show Swings Points`, 50 par défaut)
- **Structure interne** — la même chose sur les pivots internes à 5 barres, en pointillés, avec un filtre de confluence optionnel
- **Order blocks** — internes (5 par défaut) et swing (désactivés par défaut), filtrés par ATR ou par moyenne cumulée du range, mitigés sur la clôture ou sur les plus hauts/plus bas
- **EQH / EQL** — plus hauts et plus bas égaux, dans un seuil proportionnel à l'ATR
- **Fair value gaps** — désactivés par défaut ; timeframe source supérieur et seuil automatique optionnels
- **Plus hauts / plus bas MTF** — niveaux du jour, de la semaine et du mois précédents (tous désactivés par défaut)
- **Zones premium / équilibre / discount** — désactivées par défaut
- **Strong/Weak High/Low** — extrêmes swing suiveurs, libellés selon le biais swing courant

16 `alertcondition` sont exposées (BOS, CHoCH, cassures d'OB, EQH/EQL, FVG), pour les
variantes internes comme swing.

La terminologie correspond à celle de la skill `glossaire-smc` (BOS, CHoCH, OB, FVG, LQ).

## Le lire depuis Claude

L'indicateur dessine avec `line.new()`, `label.new()` et `box.new()` : sa sortie est
donc invisible pour `data_get_study_values`. Utilisez plutôt les outils de graphiques
Pine avec un filtre :

```
data_get_pine_lines   study_filter: "Smart Money"   → lignes BOS/CHoCH, niveaux MTF
data_get_pine_labels  study_filter: "Smart Money"   → BOS, CHoCH, EQH, EQL, Strong/Weak High/Low
data_get_pine_boxes   study_filter: "Smart Money"   → order blocks, FVG, zones premium/discount
```

L'indicateur doit être **visible** sur le graphique pour que ces outils renvoient
quelque chose.

## Envoyer un script vers TradingView

TradingView doit tourner avec le CDP sur le port 9222 (`scripts/launch_tv_debug_*`),
avec l'éditeur Pine ouvert sur le script à écraser.

```bash
node scripts/pine_push.js pine/smart-money-concepts.pine   # injecte + compile + rapporte les erreurs
node scripts/pine_pull.js pine/smart-money-concepts.pine   # relit l'éditeur dans le fichier
```

Sans argument, les deux scripts utilisent toujours `scripts/current.pine`, ce qui
correspond à la boucle de la skill `pine-develop`.

Attention : `pine_push.js` écrase ce qui est actuellement ouvert dans l'éditeur Pine —
ouvrez d'abord un script vierge si vous ne voulez pas perdre votre code en cours.

## Licence

Le dépôt est sous MIT (voir `../LICENSE`), mais `smart-money-concepts.pine` **ne l'est
pas**. Il est publié par LuxAlgo sous
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) : attribution
obligatoire, usage **non commercial uniquement**, et partage des dérivés dans les mêmes
conditions. L'en-tête de licence en haut du fichier fait partie de cette licence —
gardez-le intact, y compris sur toute copie modifiée.

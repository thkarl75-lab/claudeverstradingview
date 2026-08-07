# V3R_Zonage_C4A_Extractor

Extraction **exhaustive et automatisée** de toutes les propriétés de Trois-Rivières
situées dans une zone autorisant les usages de la famille **C-4 / C-4a**
(commerce d'hébergement touristique — location court terme).

L'outil ne fait **aucune** recherche adresse par adresse : il télécharge les couches
cartographiques officielles publiées par la Ville de Trois-Rivières sur
[Données Québec](https://www.donneesquebec.ca/recherche/dataset/zonage-v3r), exécute
une **intersection spatiale globale** (`gpd.sjoin`) entre la matrice foncière et les
polygones de zonage C-4a, puis produit la liste complète des propriétés conformes.

---

## Installation

```bash
cd v3r_zonage_c4a
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

> `geopandas` s'installe sans compilation via les roues `pyogrio` / `shapely`.
> En cas de souci sur Windows, `conda install -c conda-forge geopandas` reste
> la voie la plus simple.

## Utilisation

### 1. Mode batch (aucune intervention)

```bash
python main.py
```

Télécharge (ou réutilise le cache de `data/`), croise les couches et écrit :

```
exports/toutes_les_proprietes_c4a_trois_rivieres.xlsx
exports/toutes_les_proprietes_c4a_trois_rivieres.csv
exports/toutes_les_proprietes_c4a_trois_rivieres.geojson
```

Options utiles :

| Option | Effet |
|---|---|
| `--force-refresh` | Ignore le cache et retélécharge les couches |
| `--predicate {auto,within,intersects}` | Règle du `sjoin` (défaut : `auto`) |
| `--zonage FICHIER` / `--lots FICHIER` | Utilise vos propres fichiers au lieu du portail |
| `--no-adresses` | N'enrichit pas les lots avec la couche d'adresses civiques |
| `--exports-dir DOSSIER` | Change le dossier de sortie |
| `--demo` | Exécute le pipeline sur des données **fictives**, sans réseau |
| `--log-level DEBUG` | Journal détaillé |

Codes de sortie : `0` succès · `1` aucune propriété trouvée · `2` données sources indisponibles.

### 2. Dashboard interactif

```bash
streamlit run app.py
```

* Statistiques (nombre total de lots conformes, nombre de zones, répartition) ;
* table filtrable et recherchable (par zone, par texte libre) ;
* carte Folium : zones C-4a en **vert**, un marqueur par lot admissible
  (regroupés en clusters au-delà de 300 points) ;
* boutons de téléchargement Excel et CSV (liste complète ou sélection filtrée).

### 3. Vérifier l'installation

```bash
python tests/test_pipeline.py       # 10 tests, sans réseau
python main.py --demo               # pipeline complet sur données fictives
```

---

## Architecture

```
v3r_zonage_c4a/
├── data/                 # cache des couches téléchargées (+ data/manuel/ pour le mode hors ligne)
├── exports/              # sorties Excel / CSV / GeoJSON
├── src/
│   ├── config.py         # chemins, CRS, motifs C-4, noms de colonnes candidates
│   ├── fetcher.py        # API CKAN de Données Québec, téléchargement, cache
│   ├── spatial_engine.py # filtrage C-4a + sjoin global + table de résultats
│   ├── exporter.py       # Excel multi-feuilles, CSV, GeoJSON
│   └── demo_data.py      # couches synthétiques (tests et mode --demo)
├── app.py                # dashboard Streamlit
├── main.py               # CLI batch
└── tests/test_pipeline.py
```

### Le pipeline en quatre étapes

1. **`fetcher.py`** interroge l'API CKAN de l'organisation `ville-de-trois-rivieres`,
   classe les ressources par format (`geojson` > `shp` > `gpkg` > `zip`), télécharge en
   streaming avec quatre tentatives et backoff exponentiel, dézippe (en refusant les
   chemins d'archive sortant du dossier cible), puis met en cache dans `data/<couche>/`.
   Un manifeste `data/_cache_manifest.json` conserve l'URL source et la date.

2. **`spatial_engine.filter_c4_zones()`** isole les polygones de la famille C-4.
   Deux stratégies en cascade : d'abord les colonnes métier attendues
   (`zone`, `classe_usage`, `grille`, `affectation`…), puis, si rien ne sort, un
   balayage de **toutes** les colonnes textuelles. Une zone est retenue si elle
   correspond au motif `C-4 / C4 / C-4a / C-4.1` **ou** à un mot-clé d'hébergement
   touristique (`résidence de tourisme`, `gîte`, `établissement hôtelier`…).

3. **`spatial_engine.join_properties()`** exécute le `gpd.sjoin` global.
   En mode `auto`, l'affectation se fait par **point représentatif** du lot
   (`predicate="within"`) : chaque lot reçoit une zone et une seule, ce qui élimine
   les doublons des lots à cheval sur une limite de zone. Si ce mode ne ramène rien,
   repli automatique sur `intersects`.

4. **`build_result_table()`** extrait, pour chaque lot conforme : **matricule**,
   **numéro de lot**, **zone** (ex. `C-104`), **classe d'usage**, **adresse civique
   complète**, latitude/longitude (WGS84) et superficie en m².

### Gestion du CRS

C'est le point critique d'un `sjoin` : deux couches dans des projections différentes
produisent silencieusement zéro résultat. Le module applique donc systématiquement :

* **CRS de travail : `EPSG:32188`** (NAD83 / MTM zone 8), la projection métrique
  officielle du secteur de Trois-Rivières — toutes les superficies et distances y
  sont calculées ;
* reprojection forcée des deux couches vers ce CRS **avant** chaque jointure ;
* si un fichier ne déclare aucun CRS (`.prj` absent), l'emprise est inspectée :
  des coordonnées dans `[-180,180] × [-90,90]` sont traitées comme du `EPSG:4326`,
  sinon la projection municipale est supposée ;
* sortie en `EPSG:4326` pour la carte, le GeoJSON et les colonnes lat/lon.

Les géométries invalides sont réparées (`buffer(0)`) et les entités sans géométrie
écartées, avec un décompte dans le journal.

---

## Mode hors ligne

Si votre réseau bloque `donneesquebec.ca` (proxy d'entreprise, environnement isolé),
téléchargez les couches à la main et déposez-les ici :

```
data/manuel/zonage/plan_zonage.geojson      # ou .shp + .dbf + .shx + .prj
data/manuel/lots/matrice_graphique.shp
data/manuel/adresses/adresses.geojson       # optionnel
```

Les fichiers de `data/manuel/` sont **prioritaires** sur tout téléchargement.
Vous pouvez aussi pointer directement vos fichiers :

```bash
python main.py --zonage ~/Downloads/plan_zonage.geojson --lots ~/Downloads/lots.shp
```

Sources :
* Zonage — <https://www.donneesquebec.ca/recherche/dataset/zonage-v3r>
* Matrice graphique / rôle d'évaluation — portail Données Québec, organisation
  *Ville de Trois-Rivières*

## Robustesse aux changements de schéma

Les couches municipales changent de noms de colonnes d'un millésime à l'autre.
`config.py` centralise des **listes de noms candidats** (`MATRICULE_COLUMNS`,
`LOT_COLUMNS`, `ZONE_ID_COLUMNS`, `CIVIC_NUMBER_COLUMNS`…) ; la résolution se fait
par égalité stricte après normalisation (`No Civique (Réno)` → `no_civique_reno`),
puis par sous-chaîne. Si un schéma inattendu apparaît, ajoutez simplement le nom
de colonne à la liste correspondante — aucun autre code n'est à toucher.

La feuille **Métadonnées** du classeur Excel et l'encart « Traçabilité » du dashboard
indiquent quelles colonnes ont réellement déclenché la sélection et quelles valeurs
ont été retenues, pour qu'un résultat vide ou surprenant soit toujours explicable.

---

## Avertissement

Ce résultat reflète le **zonage cartographique** publié en données ouvertes. Il
identifie les zones où la grille des usages autorise la famille C-4 / C-4a, mais
**ne constitue pas une autorisation**. La conformité finale d'un projet
d'hébergement touristique doit être validée auprès :

* du **Service de l'aménagement et du développement du territoire** de la Ville de
  Trois-Rivières (règlement de zonage en vigueur, usages dérogatoires, conditions
  particulières) ;
* de la **CITQ** / du registre des établissements d'hébergement touristique du Québec
  pour l'attestation de classification.

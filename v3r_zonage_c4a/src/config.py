"""Configuration centrale du projet V3R_Zonage_C4A_Extractor.

Regroupe les chemins, les systemes de coordonnees et les regles metier
(motifs de classes d'usage, noms de colonnes candidates) utilises par les
modules `fetcher`, `spatial_engine` et `exporter`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------
# Arborescence
# --------------------------------------------------------------------------

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
EXPORTS_DIR: Final[Path] = PROJECT_ROOT / "exports"
CACHE_MANIFEST: Final[Path] = DATA_DIR / "_cache_manifest.json"

DEFAULT_EXCEL_NAME: Final[str] = "toutes_les_proprietes_c4a_trois_rivieres.xlsx"
DEFAULT_CSV_NAME: Final[str] = "toutes_les_proprietes_c4a_trois_rivieres.csv"
DEFAULT_GEOJSON_NAME: Final[str] = "toutes_les_proprietes_c4a_trois_rivieres.geojson"

# --------------------------------------------------------------------------
# Systemes de coordonnees
# --------------------------------------------------------------------------

# CRS de travail metrique : NAD83 / MTM zone 8, la projection officielle des
# donnees municipales de Trois-Rivieres (~72.5 deg O). Toute mesure de
# surface / distance est faite dans ce CRS.
WORKING_CRS: Final[str] = "EPSG:32188"

# CRS de sortie geographique (Folium, GeoJSON, exports web).
GEOGRAPHIC_CRS: Final[str] = "EPSG:4326"

# CRS suppose lorsqu'un fichier source n'en declare aucun (.prj manquant).
# Verifie a l'execution : si les coordonnees ressemblent a des degres,
# `spatial_engine` bascule automatiquement sur EPSG:4326.
ASSUMED_SOURCE_CRS: Final[str] = WORKING_CRS

# Centre de carte par defaut (hotel de ville de Trois-Rivieres), lat/lon.
CITY_CENTER: Final[tuple[float, float]] = (46.3432, -72.5477)

# --------------------------------------------------------------------------
# Source des donnees ouvertes
# --------------------------------------------------------------------------

CKAN_BASE_URL: Final[str] = "https://www.donneesquebec.ca/recherche/api/3/action"
CKAN_ORGANIZATION: Final[str] = "ville-de-trois-rivieres"

# Jeux de donnees officiels, epingles par leur slug CKAN.
#
# Le slug est la reference la plus stable : contrairement aux URL de
# ressources (qui portent des UUID regeneres a chaque remplacement de
# fichier), il ne change pas quand la Ville republie un millesime. Le
# fetcher interroge `package_show?id=<slug>` en PREMIER, avant toute
# recherche par mots-cles — c'est ce qui empeche de retomber sur un jeu
# de donnees sans rapport (ex: "avis-grands-travaux-v3r").
ZONAGE_DATASET_IDS: Final[tuple[str, ...]] = (
    "zonage-v3r",              # https://www.donneesquebec.ca/recherche/dataset/zonage-v3r
)
LOTS_DATASET_IDS: Final[tuple[str, ...]] = (
    "matrice-graphique-v3r",
    "role-evaluation-fonciere-v3r",
    "cadastre-v3r",
)
ADRESSES_DATASET_IDS: Final[tuple[str, ...]] = (
    "adresses-v3r",
    "points-adresses-v3r",
)

# URL directes, utilisees uniquement si l'API CKAN est injoignable.
# Elles contiennent des UUID de ressource : si la Ville republie la couche,
# ces liens peuvent mourir — d'ou la priorite donnee au slug ci-dessus.
ZONAGE_FALLBACK_URLS: Final[tuple[str, ...]] = (
    "https://www.donneesquebec.ca/recherche/dataset/81cfd131-73ec-43ad-9d6b-72f127c45f51"
    "/resource/cc9a0110-6ce5-4b00-ace9-603dda3c2acc/download/plan_zonage.geojson",
)

HTTP_TIMEOUT: Final[int] = 120
HTTP_RETRIES: Final[int] = 4
HTTP_BACKOFF_SECONDS: Final[float] = 2.0
USER_AGENT: Final[str] = "V3R-Zonage-C4A-Extractor/1.0 (open data client)"

# --------------------------------------------------------------------------
# Regles metier : classes d'usage visees
# --------------------------------------------------------------------------

# Motif principal : la famille commerciale C-4 (C-4, C4, C-4a, C4A, C-4.1...).
# Les gardes evitent les faux positifs du type "C-40" ou "AC-4".
C4_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Z0-9])C\s*[-_. ]?\s*4\s*(?:[.\-]?\s*[A-Z]\b|\b)",
    re.IGNORECASE,
)

# Mots-cles d'hebergement touristique rencontres dans les colonnes "usage"
# ou "description" des grilles de zonage municipales.
TOURISM_KEYWORDS: Final[tuple[str, ...]] = (
    "hebergement touristique",
    "hébergement touristique",
    "residence de tourisme",
    "résidence de tourisme",
    "location court terme",
    "location a court terme",
    "location à court terme",
    "meuble de tourisme",
    "meublé de tourisme",
    "etablissement hotelier",
    "établissement hôtelier",
    "hotellerie",
    "hôtellerie",
    "gite touristique",
    "gîte touristique",
    "auberge",
    "motel",
)

# --------------------------------------------------------------------------
# Colonnes candidates (les schemas municipaux varient d'un millesime a l'autre)
# --------------------------------------------------------------------------

# Colonnes pouvant porter l'identifiant de zone (ex: "C-104", "H-207").
ZONE_ID_COLUMNS: Final[tuple[str, ...]] = (
    "zone", "no_zone", "num_zone", "numero_zone", "nozone", "zonage",
    "id_zone", "code_zone", "zone_id", "designation", "no_zonage",
)

# Colonnes pouvant porter la classe d'usage (ex: "C-4a").
USAGE_COLUMNS: Final[tuple[str, ...]] = (
    "usage", "usages", "classe", "classe_usage", "classes_usages",
    "categorie", "catégorie", "affectation", "grille", "dominante",
    "usage_principal", "usage_autorise", "description", "libelle", "libellé",
    "type_usage", "note", "remarque",
)

# Colonnes pouvant porter le matricule foncier (18 chiffres au Quebec).
MATRICULE_COLUMNS: Final[tuple[str, ...]] = (
    "matricule", "no_matricule", "num_matricule", "matricule18",
    "id_provinc", "id_provincial", "matricule_18", "no_mat", "matr",
)

# Colonnes pouvant porter le numero de lot cadastral.
LOT_COLUMNS: Final[tuple[str, ...]] = (
    "no_lot", "numero_lot", "lot", "nolot", "lot_renove", "no_lot_renove",
    "cadastre", "id_lot", "lot_id", "designation_cadastrale",
)

# Colonnes composant l'adresse civique.
CIVIC_NUMBER_COLUMNS: Final[tuple[str, ...]] = (
    "no_civique", "num_civique", "numero_civique", "nocivique", "civique",
    "no_civ", "adresse_no", "numero", "no_imm",
)
STREET_COLUMNS: Final[tuple[str, ...]] = (
    "rue", "nom_rue", "nomrue", "odonyme", "voie", "nom_voie", "generique",
    "adresse_rue", "libelle_voie",
)
FULL_ADDRESS_COLUMNS: Final[tuple[str, ...]] = (
    "adresse", "adresse_complete", "adresse_civique", "adr", "adresse1",
    "nom_adresse", "adresse_com",
)
SUFFIX_COLUMNS: Final[tuple[str, ...]] = (
    "suite", "app", "appartement", "no_suite", "suffixe", "unite",
)

# Colonnes descriptives conservees si presentes (valeur ajoutee pour l'analyse).
EXTRA_COLUMNS: Final[tuple[str, ...]] = (
    "nb_logements", "nombre_logements", "nb_log", "annee_construction",
    "an_construction", "superficie", "superficie_terrain", "valeur_totale",
    "valeur_immeuble", "utilisation", "code_utilisation", "codeutilisation",
    "nb_etages", "nombre_etages", "proprietaire_type",
)

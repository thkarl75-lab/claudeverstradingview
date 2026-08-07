"""Moteur spatial : filtrage des zones C-4 / C-4a et intersection globale.

Le pipeline est volontairement tolerant aux variations de schema : les
couches municipales changent de noms de colonnes d'un millesime a l'autre.
Chaque etape journalise ce qu'elle a reellement trouve, de sorte qu'un
resultat vide soit explicable plutot que silencieux.

Etapes :
  1. `load_layer`        - lecture + normalisation des colonnes et du CRS ;
  2. `filter_c4_zones`   - isolation des polygones de la famille C-4 ;
  3. `join_properties`   - `gpd.sjoin()` global lots x zones C-4a ;
  4. `build_result_table`- extraction matricule / lot / zone / adresse.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

from .config import (
    ASSUMED_SOURCE_CRS,
    C4_PATTERN,
    CIVIC_NUMBER_COLUMNS,
    EXTRA_COLUMNS,
    FULL_ADDRESS_COLUMNS,
    GEOGRAPHIC_CRS,
    LOT_COLUMNS,
    MATRICULE_COLUMNS,
    STREET_COLUMNS,
    SUFFIX_COLUMNS,
    TOURISM_KEYWORDS,
    USAGE_COLUMNS,
    WORKING_CRS,
    ZONE_ID_COLUMNS,
)

LOGGER = logging.getLogger(__name__)

# Encodages rencontres dans les shapefiles municipaux quebecois.
ENCODINGS: tuple[str, ...] = ("utf-8", "latin-1", "cp1252")


class SpatialEngineError(RuntimeError):
    """Erreur bloquante du moteur spatial."""


# --------------------------------------------------------------------------
# Rapports
# --------------------------------------------------------------------------


@dataclass
class ZoneFilterReport:
    """Trace de ce qui a permis (ou non) d'identifier les zones C-4a."""

    total_zones: int = 0
    matched_zones: int = 0
    matched_columns: dict[str, int] = field(default_factory=dict)
    sample_values: list[str] = field(default_factory=list)
    strategy: str = "aucune"

    def summary(self) -> str:
        if not self.matched_zones:
            return f"Aucune zone C-4 detectee sur {self.total_zones} polygones de zonage."
        colonnes = ", ".join(f"{col} ({count})" for col, count in self.matched_columns.items())
        return (
            f"{self.matched_zones} polygone(s) C-4 retenu(s) sur {self.total_zones} "
            f"[strategie: {self.strategy}; colonnes: {colonnes}]"
        )


@dataclass
class ExtractionResult:
    """Sortie complete du pipeline spatial."""

    properties: gpd.GeoDataFrame          # lots conformes (CRS de travail)
    zones: gpd.GeoDataFrame               # polygones C-4a retenus
    table: pd.DataFrame                   # table plate prete a exporter
    zone_report: ZoneFilterReport
    join_predicate: str
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.table)

    def zone_breakdown(self) -> pd.DataFrame:
        """Repartition du nombre de proprietes par zone."""
        if self.table.empty or "Zone" not in self.table.columns:
            return pd.DataFrame(columns=["Zone", "Nombre de proprietes"])
        counts = (
            self.table["Zone"].fillna("(non identifiee)").value_counts().reset_index()
        )
        counts.columns = ["Zone", "Nombre de proprietes"]
        return counts.sort_values("Nombre de proprietes", ascending=False, ignore_index=True)


# --------------------------------------------------------------------------
# Chargement / normalisation
# --------------------------------------------------------------------------


def normalize_name(name: str) -> str:
    """`No Civique (Réno)` -> `no_civique_reno` (comparaison de colonnes)."""
    decomposed = unicodedata.normalize("NFKD", str(name).strip().lower())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", without_accents).strip("_")


def load_layer(path: str | Path, target_crs: str = WORKING_CRS) -> gpd.GeoDataFrame:
    """Charge un fichier vectoriel, normalise ses colonnes et son CRS.

    Args:
        path: chemin d'un .geojson, .shp, .gpkg...
        target_crs: CRS metrique de travail.

    Returns:
        GeoDataFrame aux colonnes normalisees (`snake_case` sans accents),
        geometries valides, reprojete dans `target_crs`.
    """
    path = Path(path)
    if not path.exists():
        raise SpatialEngineError(f"Fichier introuvable : {path}")

    gdf: gpd.GeoDataFrame | None = None
    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            gdf = gpd.read_file(path, encoding=encoding)
            break
        except Exception as exc:  # noqa: BLE001 - on essaie l'encodage suivant
            last_error = exc
    if gdf is None:
        raise SpatialEngineError(f"Lecture impossible de {path} : {last_error}")

    LOGGER.info("Couche %s : %d entites, %d colonnes", path.name, len(gdf), len(gdf.columns))

    gdf = gdf.rename(columns={col: normalize_name(col) for col in gdf.columns})
    if "geometry" not in gdf.columns and gdf.geometry.name != "geometry":
        gdf = gdf.rename_geometry("geometry")

    gdf = _clean_geometries(gdf)
    gdf = ensure_crs(gdf, target_crs)
    return gdf


def ensure_crs(gdf: gpd.GeoDataFrame, target_crs: str) -> gpd.GeoDataFrame:
    """Garantit un CRS connu puis reprojette vers `target_crs`.

    Si le fichier ne declare aucun CRS (.prj manquant), on devine :
    des coordonnees dans [-180, 180] x [-90, 90] indiquent des degres
    (EPSG:4326), sinon on suppose la projection municipale (MTM 8).
    """
    if gdf.empty:
        return gdf.set_crs(target_crs, allow_override=True) if gdf.crs is None else gdf.to_crs(target_crs)

    if gdf.crs is None:
        minx, miny, maxx, maxy = gdf.total_bounds
        looks_geographic = (
            -180.0 <= minx <= 180.0 and -180.0 <= maxx <= 180.0
            and -90.0 <= miny <= 90.0 and -90.0 <= maxy <= 90.0
        )
        assumed = GEOGRAPHIC_CRS if looks_geographic else ASSUMED_SOURCE_CRS
        LOGGER.warning("CRS absent : on suppose %s (emprise %s)", assumed, (minx, miny, maxx, maxy))
        gdf = gdf.set_crs(assumed, allow_override=True)

    if gdf.crs.to_string() != target_crs:
        gdf = gdf.to_crs(target_crs)
    return gdf


def _clean_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Supprime les geometries nulles et repare les polygones invalides."""
    before = len(gdf)
    gdf = gdf[~gdf.geometry.isna()].copy()
    if len(gdf) != before:
        LOGGER.warning("%d entite(s) sans geometrie ecartee(s)", before - len(gdf))

    invalid = ~gdf.geometry.is_valid
    if bool(invalid.any()):
        LOGGER.warning("%d geometrie(s) invalide(s) reparee(s)", int(invalid.sum()))
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)
        gdf = gdf[gdf.geometry.is_valid & ~gdf.geometry.is_empty].copy()
    return gdf


def find_column(gdf: pd.DataFrame, candidates: Sequence[str]) -> str | None:
    """Trouve la premiere colonne correspondant a un nom candidat.

    Compare d'abord en egalite stricte (apres normalisation) puis en
    sous-chaine, pour absorber les suffixes du type `no_lot_renove_2024`.
    """
    normalized = {normalize_name(col): col for col in gdf.columns}
    for candidate in candidates:
        key = normalize_name(candidate)
        if key in normalized:
            return normalized[key]
    for candidate in candidates:
        key = normalize_name(candidate)
        for norm_col, original in normalized.items():
            if key and key in norm_col:
                return original
    return None


# --------------------------------------------------------------------------
# Etape 1 : filtrage des zones C-4 / C-4a
# --------------------------------------------------------------------------


def matches_c4(value: Any) -> bool:
    """Vrai si la valeur designe la famille C-4 ou un usage d'hebergement."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value)
    if C4_PATTERN.search(text):
        return True
    lowered = normalize_name(text).replace("_", " ")
    return any(normalize_name(keyword).replace("_", " ") in lowered for keyword in TOURISM_KEYWORDS)


def filter_c4_zones(
    zoning: gpd.GeoDataFrame,
    extra_columns: Iterable[str] = (),
) -> tuple[gpd.GeoDataFrame, ZoneFilterReport]:
    """Isole les polygones de zonage autorisant la famille d'usages C-4.

    Cherche d'abord dans les colonnes metier attendues (identifiant de zone,
    classe d'usage, grille). Si rien ne sort, elargit a toutes les colonnes
    textuelles - certaines publications encodent la classe d'usage dans une
    colonne de description libre.
    """
    report = ZoneFilterReport(total_zones=len(zoning))
    if zoning.empty:
        return zoning.iloc[0:0].copy(), report

    preferred = _existing_columns(zoning, [*ZONE_ID_COLUMNS, *USAGE_COLUMNS, *extra_columns])
    text_columns = [
        col for col in zoning.columns
        if col != zoning.geometry.name and zoning[col].dtype == object
    ]

    for strategy, columns in (("colonnes metier", preferred), ("balayage integral", text_columns)):
        if not columns:
            continue
        mask = pd.Series(False, index=zoning.index)
        per_column: dict[str, int] = {}
        for column in columns:
            column_mask = zoning[column].map(matches_c4).fillna(False).astype(bool)
            hits = int(column_mask.sum())
            if hits:
                per_column[column] = hits
                mask |= column_mask
        if bool(mask.any()):
            report.strategy = strategy
            report.matched_columns = per_column
            report.matched_zones = int(mask.sum())
            matched = zoning.loc[mask].copy()
            report.sample_values = _sample_zone_values(matched, per_column)
            LOGGER.info(report.summary())
            return matched, report

    LOGGER.warning(report.summary())
    return zoning.iloc[0:0].copy(), report


def _existing_columns(gdf: pd.DataFrame, candidates: Iterable[str]) -> list[str]:
    """Resout une liste de noms candidats en colonnes reellement presentes."""
    found: list[str] = []
    for candidate in candidates:
        column = find_column(gdf, [candidate])
        if column and column not in found and column != getattr(gdf, "_geometry_column_name", "geometry"):
            found.append(column)
    return found


def _sample_zone_values(matched: gpd.GeoDataFrame, per_column: dict[str, int]) -> list[str]:
    """Quelques valeurs reellement retenues, pour audit humain."""
    samples: list[str] = []
    for column in per_column:
        values = matched[column].dropna().astype(str).unique()[:5]
        samples.extend(f"{column}={value}" for value in values)
    return samples[:15]


# --------------------------------------------------------------------------
# Etape 2 : intersection spatiale globale
# --------------------------------------------------------------------------


def join_properties(
    properties: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
    predicate: str = "auto",
) -> tuple[gpd.GeoDataFrame, str]:
    """Intersecte l'ensemble des lots avec les polygones C-4a.

    En mode `auto`, l'affectation se fait par point representatif du lot
    (`within`) : chaque lot recoit une zone et une seule, ce qui evite les
    doublons dus aux lots mitoyens d'une limite de zone. Si ce mode ne
    ramene rien (couches decalees, lots ponctuels hors polygones), on
    bascule sur un `intersects` classique.

    Returns:
        (lots conformes avec les attributs de zone, predicat effectivement utilise)
    """
    if properties.empty or zones.empty:
        return properties.iloc[0:0].copy(), predicate

    # Le sjoin exige des CRS strictement identiques.
    zones = ensure_crs(zones, WORKING_CRS)
    properties = ensure_crs(properties, WORKING_CRS)

    zones_for_join = _prefix_zone_columns(zones)

    if predicate in ("auto", "within"):
        joined = _join_on_representative_point(properties, zones_for_join)
        if not joined.empty or predicate == "within":
            return joined, "point representatif (within)"
        LOGGER.warning("Aucune correspondance par point representatif, repli sur 'intersects'")

    effective = "intersects" if predicate in ("auto", "within") else predicate
    joined = gpd.sjoin(properties, zones_for_join, how="inner", predicate=effective)
    joined = joined.drop(columns=[c for c in ("index_right", "index_left") if c in joined.columns])
    joined = joined[~joined.index.duplicated(keep="first")].copy()
    LOGGER.info("sjoin(%s) : %d lot(s) conforme(s)", effective, len(joined))
    return joined, effective


def _join_on_representative_point(
    properties: gpd.GeoDataFrame, zones: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """sjoin sur le point interieur de chaque lot, puis retour aux polygones."""
    points = properties.copy()
    # `representative_point` reste a l'interieur du polygone (contrairement au
    # centroide d'un polygone concave) ; sans effet sur des geometries ponctuelles.
    points["geometry"] = properties.geometry.representative_point()

    joined = gpd.sjoin(points, zones, how="inner", predicate="within")
    joined = joined.drop(columns=[c for c in ("index_right", "index_left") if c in joined.columns])
    joined = joined[~joined.index.duplicated(keep="first")].copy()
    # Restaure la geometrie d'origine (polygone du lot) pour la cartographie.
    joined["geometry"] = properties.geometry.loc[joined.index]
    result = gpd.GeoDataFrame(joined, geometry="geometry", crs=properties.crs)
    LOGGER.info("sjoin(point representatif) : %d lot(s) conforme(s)", len(result))
    return result


def _prefix_zone_columns(zones: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Prefixe les attributs de zone pour eviter les collisions au sjoin."""
    geometry_name = zones.geometry.name
    renamed = {
        col: f"zone__{col}" for col in zones.columns if col != geometry_name
    }
    return zones.rename(columns=renamed)


# --------------------------------------------------------------------------
# Etape 3 : construction de la table de resultats
# --------------------------------------------------------------------------


def build_result_table(joined: gpd.GeoDataFrame) -> pd.DataFrame:
    """Extrait matricule, lot, zone et adresse civique de chaque lot conforme."""
    if joined.empty:
        return pd.DataFrame(
            columns=[
                "Matricule", "Numero de lot", "Zone", "Classe d'usage",
                "Adresse", "Latitude", "Longitude", "Superficie (m2)",
            ]
        )

    zone_columns = [col for col in joined.columns if col.startswith("zone__")]
    zone_frame = joined[zone_columns].rename(columns={col: col[len("zone__"):] for col in zone_columns})

    table = pd.DataFrame(index=joined.index)
    table["Matricule"] = _first_series(joined, MATRICULE_COLUMNS)
    table["Numero de lot"] = _first_series(joined, LOT_COLUMNS)
    table["Zone"] = _first_series(zone_frame, ZONE_ID_COLUMNS)
    table["Classe d'usage"] = _usage_series(zone_frame)
    table["Adresse"] = _address_series(joined)

    centroids = joined.geometry.representative_point().to_crs(GEOGRAPHIC_CRS)
    table["Latitude"] = centroids.y.round(6)
    table["Longitude"] = centroids.x.round(6)
    table["Superficie (m2)"] = _area_series(joined)

    # Attributs supplementaires utiles s'ils existent dans la source.
    for candidate in EXTRA_COLUMNS:
        column = find_column(joined, [candidate])
        if column and column not in ("geometry",):
            label = candidate.replace("_", " ").capitalize()
            if label not in table.columns:
                table[label] = joined[column].to_numpy()

    table = table.reset_index(drop=True)
    # Une meme adresse peut apparaitre deux fois si la source contient des
    # doublons de matricule ; on ne garde qu'une ligne par propriete.
    subset = [c for c in ("Matricule", "Numero de lot", "Adresse") if c in table.columns]
    if subset:
        table = table.drop_duplicates(subset=subset, ignore_index=True)
    return _sort_table(table)


def _first_series(frame: pd.DataFrame, candidates: Sequence[str]) -> pd.Series:
    """Retourne la premiere colonne disponible, sinon une colonne vide."""
    column = find_column(frame, candidates)
    if column is None:
        return pd.Series([None] * len(frame), index=frame.index, dtype=object)
    return frame[column].astype(object)


def _usage_series(zone_frame: pd.DataFrame) -> pd.Series:
    """Recompose la classe d'usage : valeur explicite, sinon motif C-4 detecte."""
    column = find_column(zone_frame, USAGE_COLUMNS)
    if column is not None:
        return zone_frame[column].astype(object)

    def extract(row: pd.Series) -> str | None:
        for value in row:
            if value is None:
                continue
            match = C4_PATTERN.search(str(value))
            if match:
                return match.group(0).strip()
        return None

    if zone_frame.empty:
        return pd.Series([], dtype=object)
    return zone_frame.apply(extract, axis=1)


def _address_series(joined: pd.DataFrame) -> pd.Series:
    """Reconstitue l'adresse civique complete a partir du schema disponible."""
    full_column = find_column(joined, FULL_ADDRESS_COLUMNS)
    if full_column is not None:
        addresses = joined[full_column].astype(object)
        if addresses.notna().any():
            return addresses

    number_column = find_column(joined, CIVIC_NUMBER_COLUMNS)
    street_column = find_column(joined, STREET_COLUMNS)
    suffix_column = find_column(joined, SUFFIX_COLUMNS)
    if number_column is None and street_column is None:
        return pd.Series([None] * len(joined), index=joined.index, dtype=object)

    def compose(index: Any) -> str | None:
        parts: list[str] = []
        for column in (number_column, street_column):
            if column is None:
                continue
            value = joined.at[index, column]
            if value is not None and not pd.isna(value):
                text = str(value).strip()
                # Les numeros civiques lus depuis un shapefile sont souvent
                # des flottants ("1234.0") : on les remet en entier.
                if column == number_column and text.endswith(".0"):
                    text = text[:-2]
                if text:
                    parts.append(text)
        address = " ".join(parts).strip()
        if suffix_column is not None:
            suffix = joined.at[index, suffix_column]
            if suffix is not None and not pd.isna(suffix) and str(suffix).strip():
                address = f"{address}, app. {str(suffix).strip()}"
        return address or None

    return pd.Series([compose(index) for index in joined.index], index=joined.index, dtype=object)


def _area_series(joined: gpd.GeoDataFrame) -> pd.Series:
    """Superficie en m2, calculee dans le CRS metrique de travail."""
    metric = joined.to_crs(WORKING_CRS)
    areas = metric.geometry.area.round(1)
    # Une couche ponctuelle a une aire nulle : on n'affiche alors rien.
    return areas.where(areas > 0)


def _sort_table(table: pd.DataFrame) -> pd.DataFrame:
    """Tri lisible : par zone puis par adresse."""
    keys = [c for c in ("Zone", "Adresse", "Matricule") if c in table.columns]
    if not keys:
        return table
    return table.sort_values(by=keys, na_position="last", ignore_index=True)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run_pipeline(
    zoning_path: str | Path,
    properties_path: str | Path,
    predicate: str = "auto",
) -> ExtractionResult:
    """Execute le pipeline complet a partir de deux fichiers vectoriels."""
    zoning = load_layer(zoning_path)
    properties = load_layer(properties_path)
    return run_pipeline_from_layers(zoning, properties, predicate=predicate)


def run_pipeline_from_layers(
    zoning: gpd.GeoDataFrame,
    properties: gpd.GeoDataFrame,
    predicate: str = "auto",
) -> ExtractionResult:
    """Variante prenant des couches deja chargees (utilisee par les tests)."""
    warnings: list[str] = []

    zoning = ensure_crs(zoning, WORKING_CRS)
    properties = ensure_crs(properties, WORKING_CRS)

    zones, report = filter_c4_zones(zoning)
    if zones.empty:
        warnings.append(
            "Aucune zone C-4 / C-4a identifiee : verifiez que la couche de "
            "zonage contient bien une colonne de classe d'usage."
        )
        empty = properties.iloc[0:0].copy()
        return ExtractionResult(empty, zones, build_result_table(empty), report, predicate, warnings)

    joined, effective_predicate = join_properties(properties, zones, predicate=predicate)
    if joined.empty:
        warnings.append(
            "Les zones C-4a ont ete trouvees mais aucun lot ne les intersecte : "
            "verifiez la coherence geographique des deux couches."
        )

    table = build_result_table(joined)
    if not table.empty and table["Adresse"].isna().all():
        warnings.append(
            "Aucune adresse civique dans la couche de lots : joignez la couche "
            "'adresses' pour completer (voir README)."
        )

    return ExtractionResult(joined, zones, table, report, effective_predicate, warnings)


def attach_addresses(
    properties: gpd.GeoDataFrame,
    addresses: gpd.GeoDataFrame,
    max_distance: float = 25.0,
) -> gpd.GeoDataFrame:
    """Complete les lots avec la couche d'adresses civiques ponctuelles.

    Utilise une jointure spatiale par proximite (`sjoin_nearest`) limitee a
    `max_distance` metres, afin de ne pas rattacher une adresse a un lot
    voisin.
    """
    if properties.empty or addresses.empty:
        return properties

    addresses = ensure_crs(addresses, WORKING_CRS)
    properties = ensure_crs(properties, WORKING_CRS)

    keep = [
        col for col in addresses.columns
        if col != addresses.geometry.name
        and find_column(addresses[[col]], [*FULL_ADDRESS_COLUMNS, *CIVIC_NUMBER_COLUMNS, *STREET_COLUMNS])
    ]
    slim = addresses[[*keep, addresses.geometry.name]].rename(
        columns={col: f"adr_{col}" for col in keep}
    )

    joined = gpd.sjoin_nearest(
        properties, slim, how="left", max_distance=max_distance, distance_col="_distance_adresse"
    )
    joined = joined.drop(columns=[c for c in ("index_right", "index_left") if c in joined.columns])
    joined = joined[~joined.index.duplicated(keep="first")].copy()
    LOGGER.info("Adresses rattachees a %d lot(s)", int(joined["_distance_adresse"].notna().sum()))
    return joined


def zones_for_map(zones: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reprojette les zones en WGS84 pour l'affichage Folium."""
    return ensure_crs(zones, GEOGRAPHIC_CRS)


def geometry_is_polygonal(geometry: BaseGeometry | None) -> bool:
    """Vrai pour Polygon / MultiPolygon (utilitaire de diagnostic)."""
    return geometry is not None and geometry.geom_type in ("Polygon", "MultiPolygon")

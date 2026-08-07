"""Telechargement et mise en cache des couches SIG de la Ville de Trois-Rivieres.

Les jeux de donnees sont publies sur Donnees Quebec (portail CKAN). Plutot
que de coder en dur des URL qui changent a chaque millesime, ce module
interroge l'API CKAN de l'organisation `ville-de-trois-rivieres`, selectionne
la ressource la plus pertinente pour chaque couche voulue (zonage, lots /
matrice graphique, adresses) puis la telecharge dans `data/`.

Trois niveaux de resilience :
  1. resolution dynamique via l'API CKAN ;
  2. URL de repli codees en dur si l'API est injoignable ;
  3. fichiers deposes manuellement par l'utilisateur dans `data/manuel/`.

Le cache est valide par un manifeste JSON (`data/_cache_manifest.json`) qui
conserve l'URL source, la taille, l'ETag et la date de telechargement.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import requests

from .config import (
    ADRESSES_DATASET_IDS,
    CACHE_MANIFEST,
    CIVIC_NUMBER_COLUMNS,
    CKAN_BASE_URL,
    CKAN_ORGANIZATION,
    DATA_DIR,
    FULL_ADDRESS_COLUMNS,
    HTTP_BACKOFF_SECONDS,
    HTTP_RETRIES,
    HTTP_TIMEOUT,
    LOT_COLUMNS,
    LOTS_DATASET_IDS,
    MATRICULE_COLUMNS,
    STREET_COLUMNS,
    USAGE_COLUMNS,
    USER_AGENT,
    ZONAGE_DATASET_IDS,
    ZONAGE_FALLBACK_URLS,
    ZONE_ID_COLUMNS,
)

LOGGER = logging.getLogger(__name__)

# Extensions de fichiers vectoriels lisibles par geopandas / pyogrio.
VECTOR_EXTENSIONS: tuple[str, ...] = (".geojson", ".json", ".shp", ".gpkg", ".gml", ".kml")

# Ordre de preference des formats CKAN (le GeoJSON evite les soucis
# d'encodage et de fichiers .prj absents des shapefiles).
#
# `json` figure en DERNIER et non plus en deuxieme : sur Donnees Quebec,
# beaucoup de jeux non geospatiaux (avis, horaires, listes) sont publies en
# `json` brut. Les placer avant les formats geo faisait telecharger un
# fichier sans geometrie. La validation post-telechargement reste le vrai
# garde-fou, ce classement n'est qu'une optimisation.
FORMAT_PRIORITY: tuple[str, ...] = ("geojson", "shp", "gpkg", "zip", "json")


class FetchError(RuntimeError):
    """Erreur de telechargement ou de resolution d'une couche."""


# --------------------------------------------------------------------------
# Description des couches voulues
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerSpec:
    """Decrit une couche a recuperer sur le portail de donnees ouvertes.

    Attributes:
        key: identifiant interne (sert de nom de dossier dans `data/`).
        label: libelle lisible pour les journaux et l'interface.
        dataset_ids: slugs CKAN epingles, essayes AVANT toute recherche par
            mots-cles. C'est la voie fiable ; le reste n'est qu'un filet.
        include_all: groupes de mots-cles ; le titre du jeu de donnees doit
            contenir au moins un mot-cle de *chaque* groupe.
        exclude: mots-cles disqualifiants (ex: "glissement de terrain").
        fallback_urls: URL directes utilisees si l'API CKAN echoue.
        geometry_types: types de geometrie acceptes ; une couche qui n'en
            contient aucun est rejetee (ex: un JSON d'avis de travaux).
        required_any_columns: la couche doit exposer au moins une de ces
            colonnes, sinon elle ne correspond pas a ce qu'on cherche.
        required: si False, un echec n'interrompt pas le pipeline.
    """

    key: str
    label: str
    include_all: tuple[tuple[str, ...], ...]
    dataset_ids: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    fallback_urls: tuple[str, ...] = ()
    geometry_types: tuple[str, ...] = ()
    required_any_columns: tuple[str, ...] = ()
    required: bool = True


# Mots-cles disqualifiants communs : jeux de donnees municipaux qui parlent
# de "zone" ou de "lot" dans leur texte sans etre des couches de zonage ou
# de cadastre (c'est ce qui faisait retenir "avis-grands-travaux-v3r").
_COMMON_EXCLUDE: tuple[str, ...] = (
    "avis", "travaux", "entrave", "chantier", "fermeture", "deneigement",
    "collecte", "horaire", "evenement", "permis emis", "statistique",
)

ZONAGE_LAYER = LayerSpec(
    key="zonage",
    label="Zonage municipal",
    dataset_ids=ZONAGE_DATASET_IDS,
    # "zonage" seul : le mot "zone" est trop courant et matchait n'importe
    # quel jeu de donnees mentionnant une zone dans sa description.
    include_all=(("zonage", "plan de zonage", "grille des usages"),),
    exclude=_COMMON_EXCLUDE + (
        "glissement", "inondation", "erosion", "stationnement", "scolaire",
        "agricole permanente", "bruit", "vitesse", "intervention",
    ),
    fallback_urls=ZONAGE_FALLBACK_URLS,
    geometry_types=("Polygon", "MultiPolygon"),
    required_any_columns=ZONE_ID_COLUMNS + USAGE_COLUMNS,
)

LOTS_LAYER = LayerSpec(
    key="lots",
    label="Lots / matrice graphique",
    dataset_ids=LOTS_DATASET_IDS,
    include_all=(("matrice graphique", "cadastre", "lot", "unite d'evaluation",
                  "unites d'evaluation", "role d'evaluation", "fonciere",
                  "foncier", "propriete"),),
    exclude=_COMMON_EXCLUDE + ("zonage", "glissement", "inondation"),
    geometry_types=("Polygon", "MultiPolygon", "Point"),
    required_any_columns=MATRICULE_COLUMNS + LOT_COLUMNS,
)

ADRESSES_LAYER = LayerSpec(
    key="adresses",
    label="Adresses civiques",
    dataset_ids=ADRESSES_DATASET_IDS,
    include_all=(("adresse",),),
    exclude=_COMMON_EXCLUDE + ("zonage",),
    geometry_types=("Point", "MultiPoint"),
    required_any_columns=CIVIC_NUMBER_COLUMNS + STREET_COLUMNS + FULL_ADDRESS_COLUMNS,
    required=False,
)

DEFAULT_LAYERS: tuple[LayerSpec, ...] = (ZONAGE_LAYER, LOTS_LAYER, ADRESSES_LAYER)


@dataclass
class FetchResult:
    """Resultat de la recuperation d'une couche."""

    key: str
    label: str
    path: Path | None
    source_url: str | None
    origin: str  # "cache" | "telechargement" | "manuel" | "absent"
    dataset_title: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.path is not None


# --------------------------------------------------------------------------
# Client CKAN
# --------------------------------------------------------------------------


class CkanClient:
    """Client minimal pour l'API CKAN de Donnees Quebec."""

    def __init__(self, base_url: str = CKAN_BASE_URL, session: requests.Session | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or _build_session()

    def package_search(self, organization: str, rows: int = 500) -> list[dict[str, Any]]:
        """Retourne tous les jeux de donnees publies par une organisation."""
        url = f"{self.base_url}/package_search"
        params = {"fq": f"organization:{organization}", "rows": rows}
        payload = _request_json(self.session, url, params=params)
        result = payload.get("result", {})
        packages = result.get("results", [])
        LOGGER.info("CKAN: %d jeux de donnees trouves pour '%s'", len(packages), organization)
        return list(packages)

    def package_show(self, dataset_id: str) -> dict[str, Any]:
        """Retourne le detail d'un jeu de donnees (avec ses ressources)."""
        url = f"{self.base_url}/package_show"
        payload = _request_json(self.session, url, params={"id": dataset_id})
        return dict(payload.get("result", {}))


# --------------------------------------------------------------------------
# Fetcher
# --------------------------------------------------------------------------


class DataFetcher:
    """Recupere et met en cache les couches SIG necessaires au pipeline."""

    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        organization: str = CKAN_ORGANIZATION,
        force_refresh: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.manual_dir = self.data_dir / "manuel"
        self.organization = organization
        self.force_refresh = force_refresh
        self.session = session or _build_session()
        self.client = CkanClient(session=self.session)
        self._packages: list[dict[str, Any]] | None = None
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.manual_dir.mkdir(parents=True, exist_ok=True)

    # -- API publique ------------------------------------------------------

    def fetch_all(self, layers: Sequence[LayerSpec] = DEFAULT_LAYERS) -> dict[str, FetchResult]:
        """Recupere toutes les couches demandees, sans interrompre sur erreur."""
        results: dict[str, FetchResult] = {}
        for spec in layers:
            results[spec.key] = self.fetch(spec)
        return results

    def fetch(self, spec: LayerSpec) -> FetchResult:
        """Recupere une couche : fichier manuel > cache > telechargement."""
        # 1. Fichier depose manuellement par l'utilisateur (priorite absolue).
        manual = _find_vector_file(self.manual_dir / spec.key) or _find_named_vector(self.manual_dir, spec.key)
        if manual is not None:
            LOGGER.info("[%s] fichier manuel utilise : %s", spec.key, manual)
            # On signale une anomalie mais on n'ecarte pas le fichier :
            # l'utilisateur l'a depose deliberement, son schema peut etre
            # legitime et inconnu de nos listes de colonnes.
            try:
                validate_layer(manual, spec)
            except LayerValidationError as exc:
                LOGGER.warning("[%s] fichier manuel suspect : %s", spec.key, exc)
            return FetchResult(spec.key, spec.label, manual, None, "manuel")

        target_dir = self.data_dir / spec.key

        # 2. Cache local — valide seulement s'il contient la bonne couche.
        # Sans ce controle, un mauvais telechargement anterieur (ex: un JSON
        # d'avis de travaux enregistre comme "zonage") resterait servi
        # indefiniment depuis le cache.
        if not self.force_refresh:
            cached = _find_vector_file(target_dir)
            if cached is not None:
                try:
                    validate_layer(cached, spec)
                except LayerValidationError as exc:
                    LOGGER.warning(
                        "[%s] cache invalide, il sera retelecharge : %s", spec.key, exc
                    )
                    shutil.rmtree(target_dir, ignore_errors=True)
                else:
                    LOGGER.info("[%s] cache reutilise : %s", spec.key, cached)
                    meta = self._read_manifest().get(spec.key, {})
                    return FetchResult(
                        spec.key, spec.label, cached, meta.get("url"), "cache",
                        dataset_title=meta.get("dataset_title"),
                    )

        # 3. Telechargement.
        try:
            return self._download_layer(spec, target_dir)
        except Exception as exc:  # noqa: BLE001 - on veut un rapport, pas un crash
            LOGGER.warning("[%s] echec de recuperation : %s", spec.key, exc)
            # Dernier recours : un cache perime vaut mieux que rien.
            stale = _find_vector_file(target_dir)
            if stale is not None:
                LOGGER.warning("[%s] repli sur le cache existant", spec.key)
                return FetchResult(spec.key, spec.label, stale, None, "cache", error=str(exc))
            return FetchResult(spec.key, spec.label, None, None, "absent", error=str(exc))

    # -- Interne -----------------------------------------------------------

    def _download_layer(self, spec: LayerSpec, target_dir: Path) -> FetchResult:
        candidates = self._resolve_urls(spec)
        if not candidates:
            raise FetchError(
                f"Aucune ressource cartographique trouvee pour '{spec.label}'. "
                f"Deposez le fichier manuellement dans {self.manual_dir / spec.key}/"
            )

        last_error: Exception | None = None
        for url, dataset_title in candidates:
            try:
                path = self._download_and_extract(url, target_dir)
                # Garde-fou : un telechargement reussi ne prouve pas qu'on a
                # la bonne couche. On verifie le contenu avant d'accepter.
                validate_layer(path, spec)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("[%s] candidat rejete (%s) : %s", spec.key, url, exc)
                last_error = exc
                continue
            self._write_manifest_entry(spec.key, url, dataset_title, path)
            LOGGER.info("[%s] telecharge depuis %s -> %s", spec.key, url, path)
            return FetchResult(spec.key, spec.label, path, url, "telechargement", dataset_title)

        raise FetchError(f"Toutes les URL candidates ont echoue pour '{spec.label}' : {last_error}")

    def _resolve_urls(self, spec: LayerSpec) -> list[tuple[str, str | None]]:
        """Ordonne les URL candidates.

        Priorite : slugs CKAN epingles > recherche par mots-cles > URL de
        repli. Les slugs passent en premier parce qu'ils designent le jeu de
        donnees officiel sans ambiguite ; la recherche par mots-cles n'est
        qu'un filet pour le jour ou un slug change.
        """
        candidates: list[tuple[str, str | None]] = []

        # 1. Jeux de donnees epingles (package_show sur un slug connu).
        for dataset_id in spec.dataset_ids:
            try:
                dataset = self.client.package_show(dataset_id)
            except Exception as exc:  # noqa: BLE001 - slug retire ou API HS
                LOGGER.debug("[%s] slug '%s' indisponible : %s", spec.key, dataset_id, exc)
                continue
            title = dataset.get("title") or dataset.get("name")
            resources = _rank_resources(dataset.get("resources", []))
            LOGGER.info(
                "[%s] jeu epingle '%s' : %d ressource(s) geospatiale(s)",
                spec.key, dataset_id, len(resources),
            )
            candidates.extend(
                (str(res["url"]), title) for res in resources if res.get("url")
            )

        # 2. Recherche par mots-cles dans l'organisation.
        try:
            for dataset in self._match_datasets(spec):
                title = dataset.get("title") or dataset.get("name")
                for resource in _rank_resources(dataset.get("resources", [])):
                    url = resource.get("url")
                    if url:
                        candidates.append((str(url), title))
        except Exception as exc:  # noqa: BLE001 - API indisponible / hors ligne
            LOGGER.warning("[%s] API CKAN indisponible (%s), repli sur les URL connues", spec.key, exc)

        candidates.extend((url, None) for url in spec.fallback_urls)
        # Deduplique en conservant l'ordre de priorite.
        seen: set[str] = set()
        ordered: list[tuple[str, str | None]] = []
        for url, title in candidates:
            if url not in seen:
                seen.add(url)
                ordered.append((url, title))
        return ordered

    def _match_datasets(self, spec: LayerSpec) -> list[dict[str, Any]]:
        """Selectionne les jeux de donnees dont le titre colle a la couche."""
        if self._packages is None:
            self._packages = self.client.package_search(self.organization)

        scored: list[tuple[int, dict[str, Any]]] = []
        for package in self._packages:
            # L'inclusion ne regarde QUE le titre, le slug et les tags.
            # La description (`notes`) etait auparavant incluse : elle fait
            # matcher n'importe quel jeu de donnees mentionnant "zone" ou
            # "lot" en passant, ce qui faisait retenir "Avis de grands
            # travaux" comme couche de zonage.
            haystack = _normalize(
                " ".join(str(package.get(field_name, "")) for field_name in ("title", "name"))
                + " "
                + " ".join(_tag_names(package))
            )
            # L'exclusion, elle, balaie aussi la description : mieux vaut
            # ecarter un jeu douteux que l'accepter.
            excludable = haystack + " " + _normalize(str(package.get("notes", "")))
            if any(_normalize(bad) in excludable for bad in spec.exclude):
                continue
            if not all(
                any(_normalize(word) in haystack for word in group)
                for group in spec.include_all
            ):
                continue
            # Un jeu contenant une ressource geospatiale passe devant.
            score = sum(
                1 for res in package.get("resources", [])
                if str(res.get("format", "")).lower() in FORMAT_PRIORITY
            )
            scored.append((score, package))

        scored.sort(key=lambda item: item[0], reverse=True)
        matches = [package for _, package in scored]
        LOGGER.info("[%s] %d jeu(x) de donnees correspondant(s)", spec.key, len(matches))
        return matches

    def _download_and_extract(self, url: str, target_dir: Path) -> Path:
        """Telecharge une URL puis renvoie le chemin du fichier vectoriel."""
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = _filename_from_url(url)
        archive_path = target_dir / filename
        _download_stream(self.session, url, archive_path)

        if zipfile.is_zipfile(archive_path):
            extract_dir = target_dir / "extrait"
            extract_dir.mkdir(exist_ok=True)
            _safe_extract(archive_path, extract_dir)
            archive_path.unlink(missing_ok=True)

        vector = _find_vector_file(target_dir)
        if vector is None:
            raise FetchError(f"Aucun fichier vectoriel exploitable dans {url}")
        return vector

    # -- Manifeste de cache ------------------------------------------------

    def _read_manifest(self) -> dict[str, Any]:
        if not CACHE_MANIFEST.exists():
            return {}
        try:
            return json.loads(CACHE_MANIFEST.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_manifest_entry(
        self, key: str, url: str, dataset_title: str | None, path: Path
    ) -> None:
        manifest = self._read_manifest()
        manifest[key] = {
            "url": url,
            "dataset_title": dataset_title,
            "fichier": str(path.relative_to(self.data_dir)) if path.is_relative_to(self.data_dir) else str(path),
            "octets": path.stat().st_size if path.exists() else None,
            "telecharge_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        CACHE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        CACHE_MANIFEST.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# --------------------------------------------------------------------------
# Validation du contenu telecharge
# --------------------------------------------------------------------------


class LayerValidationError(FetchError):
    """La couche telechargee ne correspond pas a ce qui etait demande."""


def validate_layer(path: Path, spec: LayerSpec, sample_size: int = 200) -> None:
    """Verifie qu'un fichier telecharge est bien la couche attendue.

    Un telechargement HTTP 200 ne prouve rien : le portail peut servir un
    jeu de donnees sans rapport (un JSON d'avis de travaux, une page
    d'erreur HTML, un CSV sans geometrie). Cette fonction lit un echantillon
    du fichier et rejette tout ce qui ne ressemble pas a la couche voulue.

    Args:
        path: fichier vectoriel a controler.
        spec: couche attendue (types de geometrie, colonnes obligatoires).
        sample_size: nombre d'entites lues pour le controle.

    Raises:
        LayerValidationError: si le fichier ne correspond pas.
    """
    import geopandas as gpd  # import tardif : garde le fetcher leger

    try:
        sample = gpd.read_file(path, rows=sample_size)
    except Exception as exc:  # noqa: BLE001 - fichier illisible = invalide
        raise LayerValidationError(
            f"{path.name} n'est pas une couche vectorielle lisible ({exc})"
        ) from exc

    if sample.empty:
        raise LayerValidationError(f"{path.name} ne contient aucune entite")

    # 1. Geometrie presente et du bon type.
    if sample.geometry.isna().all():
        raise LayerValidationError(f"{path.name} n'a aucune geometrie exploitable")

    if spec.geometry_types:
        present = set(sample.geometry.geom_type.dropna().unique())
        if not present & set(spec.geometry_types):
            raise LayerValidationError(
                f"{path.name} contient {sorted(present)} au lieu de "
                f"{list(spec.geometry_types)} — ce n'est pas la couche '{spec.label}'"
            )

    # 2. Au moins une colonne metier attendue.
    if spec.required_any_columns:
        normalized = {_normalize_column(name) for name in sample.columns}
        wanted = {_normalize_column(name) for name in spec.required_any_columns}
        if not normalized & wanted:
            # Tolerance : une correspondance par sous-chaine suffit, les
            # schemas municipaux prefixent parfois leurs colonnes.
            if not any(w in col for col in normalized for w in wanted if len(w) > 3):
                raise LayerValidationError(
                    f"{path.name} n'expose aucune colonne attendue pour "
                    f"'{spec.label}' (colonnes vues : {sorted(sample.columns)[:12]})"
                )

    LOGGER.info(
        "[%s] validation OK : %d entite(s) echantillonnee(s), geometries %s",
        spec.key, len(sample), sorted(set(sample.geometry.geom_type.dropna().unique())),
    )


def _normalize_column(name: str) -> str:
    """Normalise un nom de colonne pour comparaison (accents, casse, separateurs)."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    return session


def _request_json(
    session: requests.Session, url: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """GET JSON avec reessais et backoff exponentiel."""
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES):
        try:
            response = session.get(url, params=params, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            return dict(response.json())
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < HTTP_RETRIES - 1:
                time.sleep(HTTP_BACKOFF_SECONDS * (2**attempt))
    raise FetchError(f"GET {url} a echoue apres {HTTP_RETRIES} tentatives : {last_error}")


def _download_stream(session: requests.Session, url: str, destination: Path) -> None:
    """Telecharge un fichier en streaming, avec reessais et ecriture atomique."""
    last_error: Exception | None = None
    for attempt in range(HTTP_RETRIES):
        temp_path = destination.with_suffix(destination.suffix + ".part")
        try:
            with session.get(url, stream=True, timeout=HTTP_TIMEOUT) as response:
                response.raise_for_status()
                with temp_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        if chunk:
                            handle.write(chunk)
            if temp_path.stat().st_size == 0:
                raise FetchError("fichier vide")
            temp_path.replace(destination)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            temp_path.unlink(missing_ok=True)
            if attempt < HTTP_RETRIES - 1:
                time.sleep(HTTP_BACKOFF_SECONDS * (2**attempt))
    raise FetchError(f"Telechargement de {url} impossible : {last_error}")


def _safe_extract(archive: Path, destination: Path) -> None:
    """Extrait un ZIP en refusant les chemins sortant du dossier cible."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            member_path = (destination / member.filename).resolve()
            if not member_path.is_relative_to(destination):
                raise FetchError(f"Entree d'archive suspecte : {member.filename}")
        zf.extractall(destination)


def _find_vector_file(root: Path) -> Path | None:
    """Retourne le fichier vectoriel le plus pertinent sous `root`."""
    if not root.exists():
        return None
    candidates: list[Path] = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.lower() in VECTOR_EXTENSIONS
    ]
    if not candidates:
        return None

    def priority(path: Path) -> tuple[int, int]:
        try:
            extension_rank = VECTOR_EXTENSIONS.index(path.suffix.lower())
        except ValueError:  # pragma: no cover - defensif
            extension_rank = len(VECTOR_EXTENSIONS)
        # A format egal, on garde le plus gros fichier (couche principale).
        return (extension_rank, -path.stat().st_size)

    candidates.sort(key=priority)
    return candidates[0]


def _find_named_vector(root: Path, key: str) -> Path | None:
    """Cherche `data/manuel/<key>.geojson` (ou .shp, .gpkg...)."""
    if not root.exists():
        return None
    for extension in VECTOR_EXTENSIONS:
        candidate = root / f"{key}{extension}"
        if candidate.exists():
            return candidate
    return None


def _rank_resources(resources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trie les ressources CKAN par format geospatial preferentiel."""
    usable = [
        resource
        for resource in resources
        if str(resource.get("format", "")).lower() in FORMAT_PRIORITY
        and resource.get("url")
    ]

    def rank(resource: dict[str, Any]) -> int:
        return FORMAT_PRIORITY.index(str(resource.get("format", "")).lower())

    return sorted(usable, key=rank)


def _tag_names(package: dict[str, Any]) -> list[str]:
    tags = package.get("tags", [])
    names: list[str] = []
    for tag in tags:
        if isinstance(tag, dict):
            names.append(str(tag.get("display_name") or tag.get("name") or ""))
        else:
            names.append(str(tag))
    return names


def _normalize(text: str) -> str:
    """Minuscule + suppression des accents, pour comparer des libelles FR."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _filename_from_url(url: str) -> str:
    from urllib.parse import unquote, urlparse

    name = Path(unquote(urlparse(url).path)).name or "download"
    # Force une extension exploitable pour la detection ZIP / vectoriel.
    if not Path(name).suffix:
        name += ".bin"
    return name

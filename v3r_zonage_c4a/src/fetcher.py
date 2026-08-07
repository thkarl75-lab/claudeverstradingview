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
    CACHE_MANIFEST,
    CKAN_BASE_URL,
    CKAN_ORGANIZATION,
    DATA_DIR,
    HTTP_BACKOFF_SECONDS,
    HTTP_RETRIES,
    HTTP_TIMEOUT,
    USER_AGENT,
)

LOGGER = logging.getLogger(__name__)

# Extensions de fichiers vectoriels lisibles par geopandas / pyogrio.
VECTOR_EXTENSIONS: tuple[str, ...] = (".geojson", ".json", ".shp", ".gpkg", ".gml", ".kml")

# Ordre de preference des formats CKAN (le GeoJSON evite les soucis
# d'encodage et de fichiers .prj absents des shapefiles).
FORMAT_PRIORITY: tuple[str, ...] = ("geojson", "json", "shp", "gpkg", "zip")


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
        include_all: groupes de mots-cles ; le titre du jeu de donnees doit
            contenir au moins un mot-cle de *chaque* groupe.
        exclude: mots-cles disqualifiants (ex: "glissement de terrain").
        fallback_urls: URL directes utilisees si l'API CKAN echoue.
        required: si False, un echec n'interrompt pas le pipeline.
    """

    key: str
    label: str
    include_all: tuple[tuple[str, ...], ...]
    exclude: tuple[str, ...] = ()
    fallback_urls: tuple[str, ...] = ()
    required: bool = True


ZONAGE_LAYER = LayerSpec(
    key="zonage",
    label="Zonage municipal",
    include_all=(("zonage", "zone",),),
    exclude=("glissement", "inondation", "erosion", "stationnement", "scolaire",
             "agricole permanente", "bruit", "vitesse"),
    fallback_urls=(
        # Ressource GeoJSON publiee par la Ville de Trois-Rivieres.
        "https://www.donneesquebec.ca/recherche/dataset/81cfd131-73ec-43ad-9d6b-72f127c45f51"
        "/resource/cc9a0110-6ce5-4b00-ace9-603dda3c2acc/download/plan_zonage.geojson",
    ),
)

LOTS_LAYER = LayerSpec(
    key="lots",
    label="Lots / matrice graphique",
    include_all=(("matrice", "cadastre", "lot", "unite d'evaluation",
                  "unites d'evaluation", "role d'evaluation", "fonciere",
                  "foncier", "propriete"),),
    exclude=("zonage", "glissement", "inondation"),
)

ADRESSES_LAYER = LayerSpec(
    key="adresses",
    label="Adresses civiques",
    include_all=(("adresse",),),
    exclude=("zonage", "collecte"),
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
            return FetchResult(spec.key, spec.label, manual, None, "manuel")

        target_dir = self.data_dir / spec.key

        # 2. Cache local valide.
        if not self.force_refresh:
            cached = _find_vector_file(target_dir)
            if cached is not None:
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
            except Exception as exc:  # noqa: BLE001
                LOGGER.debug("[%s] URL rejetee (%s) : %s", spec.key, url, exc)
                last_error = exc
                continue
            self._write_manifest_entry(spec.key, url, dataset_title, path)
            LOGGER.info("[%s] telecharge depuis %s -> %s", spec.key, url, path)
            return FetchResult(spec.key, spec.label, path, url, "telechargement", dataset_title)

        raise FetchError(f"Toutes les URL candidates ont echoue pour '{spec.label}' : {last_error}")

    def _resolve_urls(self, spec: LayerSpec) -> list[tuple[str, str | None]]:
        """Ordonne les URL candidates : API CKAN d'abord, replis ensuite."""
        candidates: list[tuple[str, str | None]] = []
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
            haystack = _normalize(
                " ".join(
                    str(package.get(field_name, ""))
                    for field_name in ("title", "name", "notes")
                )
                + " "
                + " ".join(_tag_names(package))
            )
            if any(_normalize(bad) in haystack for bad in spec.exclude):
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

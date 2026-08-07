#!/usr/bin/env python3
"""Pipeline batch : extraction de toutes les proprietes C-4 / C-4a de Trois-Rivieres.

Execution sans aucune intervention utilisateur :

    python main.py

Produit `exports/toutes_les_proprietes_c4a_trois_rivieres.xlsx` (+ CSV + GeoJSON).

Codes de sortie :
    0 - extraction reussie (au moins une propriete trouvee)
    1 - pipeline execute mais aucune propriete conforme
    2 - donnees sources indisponibles (reseau bloque, portail hors ligne...)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

import geopandas as gpd

from src.config import (
    DATA_DIR,
    DEFAULT_CSV_NAME,
    DEFAULT_EXCEL_NAME,
    DEFAULT_GEOJSON_NAME,
    EXPORTS_DIR,
)
from src.exporter import export_all
from src.fetcher import (
    ADRESSES_LAYER,
    LOTS_LAYER,
    ZONAGE_LAYER,
    DataFetcher,
    FetchResult,
)
from src.spatial_engine import (
    ExtractionResult,
    attach_addresses,
    load_layer,
    run_pipeline_from_layers,
)

LOGGER = logging.getLogger("v3r")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v3r-zonage-c4a",
        description="Extrait toutes les proprietes situees en zone C-4 / C-4a a Trois-Rivieres.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--zonage", type=Path, default=None,
        help="Fichier de zonage local (contourne le telechargement).",
    )
    parser.add_argument(
        "--lots", type=Path, default=None,
        help="Fichier de lots / matrice graphique local.",
    )
    parser.add_argument(
        "--adresses", type=Path, default=None,
        help="Couche d'adresses civiques locale (optionnelle).",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Ignore le cache de data/ et retelecharge les couches.",
    )
    parser.add_argument(
        "--no-adresses", action="store_true",
        help="N'essaie pas d'enrichir les lots avec la couche d'adresses.",
    )
    parser.add_argument(
        "--predicate", choices=("auto", "within", "intersects"), default="auto",
        help="Predicat du sjoin. 'auto' = point representatif puis repli intersects.",
    )
    parser.add_argument(
        "--exports-dir", type=Path, default=EXPORTS_DIR,
        help="Dossier de sortie des fichiers Excel/CSV.",
    )
    parser.add_argument(
        "--excel-name", default=DEFAULT_EXCEL_NAME, help="Nom du fichier Excel produit.",
    )
    parser.add_argument(
        "--no-geojson", action="store_true", help="N'ecrit pas le GeoJSON des lots conformes.",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Execute le pipeline sur des couches FICTIVES (aucun reseau requis), "
             "pour verifier l'installation et visualiser le format de sortie.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"), help="Verbosite du journal.",
    )
    return parser


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# --------------------------------------------------------------------------
# Acquisition des couches
# --------------------------------------------------------------------------


def resolve_layers(args: argparse.Namespace) -> tuple[dict[str, Path], dict[str, FetchResult]]:
    """Retourne les chemins des couches, en telechargeant ce qui manque."""
    paths: dict[str, Path] = {}
    results: dict[str, FetchResult] = {}

    overrides = {"zonage": args.zonage, "lots": args.lots, "adresses": args.adresses}
    wanted = [ZONAGE_LAYER, LOTS_LAYER] + ([] if args.no_adresses else [ADRESSES_LAYER])

    needs_download = [spec for spec in wanted if overrides.get(spec.key) is None]
    if needs_download:
        fetcher = DataFetcher(data_dir=DATA_DIR, force_refresh=args.force_refresh)
        results = fetcher.fetch_all(needs_download)

    for spec in wanted:
        override = overrides.get(spec.key)
        if override is not None:
            if not override.exists():
                raise SystemExit(f"Fichier introuvable : {override}")
            paths[spec.key] = override
            continue
        result = results.get(spec.key)
        if result and result.ok and result.path is not None:
            paths[spec.key] = result.path

    return paths, results


def load_optional(path: Path | None) -> gpd.GeoDataFrame | None:
    if path is None:
        return None
    try:
        return load_layer(path)
    except Exception as exc:  # noqa: BLE001 - couche facultative
        LOGGER.warning("Couche optionnelle ignoree (%s) : %s", path, exc)
        return None


# --------------------------------------------------------------------------
# Rapport console
# --------------------------------------------------------------------------


def print_report(result: ExtractionResult, written: dict[str, Path]) -> None:
    line = "=" * 72
    print(f"\n{line}")
    print("  V3R — PROPRIETES AUTORISEES EN ZONE C-4 / C-4a (hebergement touristique)")
    print(line)
    print(f"  Polygones de zonage analyses : {result.zone_report.total_zones}")
    print(f"  Zones C-4 / C-4a retenues    : {len(result.zones)}")
    print(f"  Predicat spatial             : {result.join_predicate}")
    print(f"  PROPRIETES CONFORMES         : {result.count}")

    breakdown = result.zone_breakdown()
    if not breakdown.empty:
        print(f"\n  Repartition par zone (top 15) :")
        for _, row in breakdown.head(15).iterrows():
            print(f"    {str(row['Zone']):<24} {row['Nombre de proprietes']:>6}")
        if len(breakdown) > 15:
            print(f"    ... et {len(breakdown) - 15} autre(s) zone(s)")

    if result.warnings:
        print("\n  Avertissements :")
        for warning in result.warnings:
            print(f"    ! {warning}")

    if written:
        print("\n  Fichiers produits :")
        for kind, path in written.items():
            print(f"    {kind:<8} {path}")
    print(f"{line}\n")


def print_fetch_failure(results: dict[str, FetchResult]) -> None:
    print("\nImpossible de recuperer les couches obligatoires :\n")
    for key, result in results.items():
        status = "OK" if result.ok else "ECHEC"
        print(f"  [{status:^5}] {result.label} ({key})")
        if result.error:
            print(f"           {result.error}")
    print(
        "\nSi votre reseau bloque donneesquebec.ca, telechargez les couches"
        "\nmanuellement puis relancez :"
        "\n  1. Zonage : https://www.donneesquebec.ca/recherche/dataset/zonage-v3r"
        "\n  2. Matrice graphique / lots : portail Donnees Quebec, organisation"
        "\n     'ville-de-trois-rivieres'"
        f"\n  3. Deposez les fichiers dans {DATA_DIR / 'manuel' / '<couche>'}/"
        "\n     (ex: data/manuel/zonage/plan_zonage.geojson, data/manuel/lots/lots.shp)"
        "\n  ou passez --zonage / --lots avec vos propres chemins.\n"
    )


# --------------------------------------------------------------------------
# Mode demonstration (hors ligne)
# --------------------------------------------------------------------------


def run_demo(args: argparse.Namespace) -> int:
    """Rejoue le pipeline sur des couches fictives, sans acces reseau."""
    from src.demo_data import make_demo_properties, make_demo_zoning

    print(
        "\n*** MODE DEMO — DONNEES FICTIVES ***\n"
        "Les lignes produites ne correspondent a AUCUNE propriete reelle.\n"
        "Ce mode sert uniquement a valider l'installation et le format de sortie.\n"
    )
    result = run_pipeline_from_layers(
        make_demo_zoning(), make_demo_properties(), predicate=args.predicate
    )
    written = export_all(
        result,
        exports_dir=args.exports_dir,
        excel_name="DEMO_donnees_fictives.xlsx",
        csv_name="DEMO_donnees_fictives.csv",
        geojson_name=None,
        metadata={"Mode": "DEMONSTRATION — donnees fictives, ne pas utiliser"},
    )
    print_report(result, written)
    return 0 if result.count else 1


# --------------------------------------------------------------------------
# Entree
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    if args.demo:
        return run_demo(args)

    LOGGER.info("Acquisition des couches SIG...")
    paths, fetch_results = resolve_layers(args)

    if "zonage" not in paths or "lots" not in paths:
        print_fetch_failure(fetch_results)
        return 2

    LOGGER.info("Chargement du zonage : %s", paths["zonage"])
    zoning = load_layer(paths["zonage"])
    LOGGER.info("Chargement des lots : %s", paths["lots"])
    properties = load_layer(paths["lots"])

    addresses = load_optional(paths.get("adresses"))
    if addresses is not None:
        LOGGER.info("Enrichissement des lots par la couche d'adresses (%d points)", len(addresses))
        properties = attach_addresses(properties, addresses)

    LOGGER.info("Intersection spatiale globale...")
    result = run_pipeline_from_layers(zoning, properties, predicate=args.predicate)

    metadata = {
        "Source zonage": str(paths["zonage"]),
        "Source lots": str(paths["lots"]),
        "Source adresses": str(paths.get("adresses", "-")),
    }
    geojson_name = None if args.no_geojson else DEFAULT_GEOJSON_NAME
    written = export_all(
        result,
        exports_dir=args.exports_dir,
        excel_name=args.excel_name,
        csv_name=DEFAULT_CSV_NAME,
        geojson_name=geojson_name,
        metadata=metadata,
    )

    print_report(result, written)
    return 0 if result.count else 1


if __name__ == "__main__":
    sys.exit(main())

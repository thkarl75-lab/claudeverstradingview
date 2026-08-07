#!/usr/bin/env python3
"""Tests du moteur spatial sur des couches synthetiques.

Ces tests ne touchent pas au reseau : ils construisent un zonage et une
matrice foncière fictifs, puis verifient que le filtrage C-4, le sjoin, la
gestion du CRS et les exports se comportent comme attendu.

    python tests/test_pipeline.py     # ou : pytest tests/
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import GEOGRAPHIC_CRS, WORKING_CRS  # noqa: E402
from src.demo_data import make_demo_properties, make_demo_zoning  # noqa: E402
from src.exporter import export_all  # noqa: E402
from src.spatial_engine import (  # noqa: E402
    build_result_table,
    ensure_crs,
    filter_c4_zones,
    join_properties,
    matches_c4,
    run_pipeline_from_layers,
)


# Les couches synthetiques sont partagees avec le mode `--demo` de main.py.
make_zoning = make_demo_zoning
make_properties = make_demo_properties


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_matches_c4_patterns() -> None:
    for positive in ("C-4", "C4", "C-4a", "c4A", "C-4.1", "Hébergement touristique",
                     "résidence de tourisme"):
        assert matches_c4(positive), f"aurait du matcher : {positive}"
    for negative in ("C-40", "C-104", "H-1", "P-2", "AC-4x", None, float("nan"), ""):
        assert not matches_c4(negative), f"n'aurait pas du matcher : {negative!r}"


def test_filter_c4_zones() -> None:
    zones, report = filter_c4_zones(make_zoning())
    assert len(zones) == 2, f"attendu 2 zones, obtenu {len(zones)}"
    assert report.total_zones == 3
    assert "classe_usage" in report.matched_columns
    # La zone residentielle ne doit pas passer.
    assert "H-330" not in set(zones["no_zone"])


def test_spatial_join_and_table() -> None:
    zones, _ = filter_c4_zones(make_zoning())
    joined, predicate = join_properties(make_properties(), zones)
    assert len(joined) == 3, f"attendu 3 lots conformes, obtenu {len(joined)}"
    assert "point representatif" in predicate

    table = build_result_table(joined)
    assert len(table) == 3
    assert set(table["Zone"]) == {"C-104", "C-210"}
    assert "100 rue Notre-Dame" in set(table["Adresse"])
    # Coordonnees reprojetees en WGS84, plausibles pour Trois-Rivieres.
    assert table["Latitude"].between(45.0, 47.5).all()
    assert table["Longitude"].between(-74.0, -71.0).all()
    assert (table["Superficie (m2)"] > 9000).all()  # carres de 100 m


def test_crs_mismatch_is_reconciled() -> None:
    """Les deux couches dans des CRS differents doivent quand meme se joindre."""
    zoning = make_zoning().to_crs(GEOGRAPHIC_CRS)
    properties = make_properties()  # reste en MTM 8
    result = run_pipeline_from_layers(zoning, properties)
    assert result.count == 3, f"attendu 3, obtenu {result.count}"


def test_missing_crs_is_assumed() -> None:
    """Un fichier sans .prj est rattache au CRS municipal, pas rejete."""
    zoning = make_zoning()
    zoning.crs = None
    result = run_pipeline_from_layers(zoning, make_properties())
    assert result.count == 3


def test_no_c4_zone_returns_empty_without_crashing() -> None:
    zoning = make_zoning()
    zoning["no_zone"] = ["H-1", "H-2", "H-3"]
    zoning["classe_usage"] = ["H-1", "H-2", "H-3"]
    result = run_pipeline_from_layers(zoning, make_properties())
    assert result.count == 0
    assert result.warnings, "un resultat vide doit etre explique"


def test_point_layer_is_supported() -> None:
    """Une matrice publiee en points (centroides) doit fonctionner aussi."""
    properties = make_properties()
    properties["geometry"] = properties.geometry.representative_point()
    result = run_pipeline_from_layers(make_zoning(), properties)
    assert result.count == 3
    assert result.table["Superficie (m2)"].isna().all()


def test_zone_breakdown() -> None:
    result = run_pipeline_from_layers(make_zoning(), make_properties())
    breakdown = result.zone_breakdown()
    assert list(breakdown.columns) == ["Zone", "Nombre de proprietes"]
    assert int(breakdown["Nombre de proprietes"].sum()) == result.count


def test_exports_are_written() -> None:
    result = run_pipeline_from_layers(make_zoning(), make_properties())
    with tempfile.TemporaryDirectory() as tmp:
        written = export_all(result, exports_dir=Path(tmp), metadata={"Test": "oui"})
        assert written["excel"].exists() and written["excel"].stat().st_size > 0
        assert written["csv"].exists()
        assert written["geojson"].exists()

        sheets = pd.read_excel(written["excel"], sheet_name=None)
        assert len(sheets["Proprietes C-4a"]) == 3
        assert "Repartition par zone" in sheets and "Metadonnees" in sheets

        reloaded = gpd.read_file(written["geojson"])
        assert len(reloaded) == 3
        assert reloaded.crs.to_epsg() == 4326


def test_ensure_crs_roundtrip() -> None:
    points = gpd.GeoDataFrame({"geometry": [Point(-72.5477, 46.3432)]}, crs=GEOGRAPHIC_CRS)
    projected = ensure_crs(points, WORKING_CRS)
    assert projected.crs.to_string() == WORKING_CRS
    back = ensure_crs(projected, GEOGRAPHIC_CRS)
    assert abs(back.geometry.iloc[0].x - (-72.5477)) < 1e-6


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - rapport de test
            failures += 1
            print(f"  ECHEC  {test.__name__}: {exc}")
        else:
            print(f"  OK     {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} test(s) reussi(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

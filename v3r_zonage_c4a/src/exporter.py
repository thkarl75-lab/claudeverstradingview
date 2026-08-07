"""Structuration et export des resultats (Excel, CSV, GeoJSON).

Le classeur Excel contient trois feuilles :
  * `Proprietes C-4a` - la liste exhaustive, filtrable ;
  * `Repartition par zone` - le decompte par zone ;
  * `Metadonnees` - la trace de l'extraction (sources, predicat, avertissements).
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import geopandas as gpd
import pandas as pd

from .config import (
    DEFAULT_CSV_NAME,
    DEFAULT_EXCEL_NAME,
    DEFAULT_GEOJSON_NAME,
    EXPORTS_DIR,
    GEOGRAPHIC_CRS,
)
from .spatial_engine import ExtractionResult

LOGGER = logging.getLogger(__name__)

SHEET_PROPERTIES = "Proprietes C-4a"
SHEET_BREAKDOWN = "Repartition par zone"
SHEET_METADATA = "Metadonnees"

MAX_COLUMN_WIDTH = 55


def export_all(
    result: ExtractionResult,
    exports_dir: Path = EXPORTS_DIR,
    excel_name: str = DEFAULT_EXCEL_NAME,
    csv_name: str = DEFAULT_CSV_NAME,
    geojson_name: str | None = DEFAULT_GEOJSON_NAME,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Ecrit tous les livrables et retourne les chemins produits."""
    exports_dir = Path(exports_dir)
    exports_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    excel_path = exports_dir / excel_name
    write_excel(result, excel_path, metadata=metadata)
    written["excel"] = excel_path

    csv_path = exports_dir / csv_name
    write_csv(result.table, csv_path)
    written["csv"] = csv_path

    if geojson_name:
        geojson_path = exports_dir / geojson_name
        if write_geojson(result.properties, geojson_path):
            written["geojson"] = geojson_path

    return written


# --------------------------------------------------------------------------
# Excel
# --------------------------------------------------------------------------


def write_excel(
    result: ExtractionResult,
    path: Path,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Ecrit le classeur Excel multi-feuilles."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        table = result.table if not result.table.empty else _empty_placeholder()
        table.to_excel(writer, sheet_name=SHEET_PROPERTIES, index=False)
        result.zone_breakdown().to_excel(writer, sheet_name=SHEET_BREAKDOWN, index=False)
        _metadata_frame(result, metadata).to_excel(writer, sheet_name=SHEET_METADATA, index=False)

        _style_sheet(writer.book[SHEET_PROPERTIES], freeze="A2", autofilter=True)
        _style_sheet(writer.book[SHEET_BREAKDOWN], freeze="A2", autofilter=True)
        _style_sheet(writer.book[SHEET_METADATA], freeze=None, autofilter=False)

    LOGGER.info("Excel ecrit : %s (%d lignes)", path, len(result.table))
    return path


def excel_bytes(result: ExtractionResult, metadata: Mapping[str, Any] | None = None) -> bytes:
    """Version en memoire, pour le bouton de telechargement Streamlit."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        table = result.table if not result.table.empty else _empty_placeholder()
        table.to_excel(writer, sheet_name=SHEET_PROPERTIES, index=False)
        result.zone_breakdown().to_excel(writer, sheet_name=SHEET_BREAKDOWN, index=False)
        _metadata_frame(result, metadata).to_excel(writer, sheet_name=SHEET_METADATA, index=False)
        _style_sheet(writer.book[SHEET_PROPERTIES], freeze="A2", autofilter=True)
        _style_sheet(writer.book[SHEET_BREAKDOWN], freeze="A2", autofilter=True)
        _style_sheet(writer.book[SHEET_METADATA], freeze=None, autofilter=False)
    return buffer.getvalue()


def _style_sheet(worksheet: Any, freeze: str | None, autofilter: bool) -> None:
    """En-tetes en gras, colonnes ajustees, filtre automatique."""
    from openpyxl.styles import Alignment, Font, PatternFill

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F6F43")

    for cell in worksheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    for column_cells in worksheet.columns:
        longest = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=0,
        )
        letter = column_cells[0].column_letter
        worksheet.column_dimensions[letter].width = min(max(longest + 2, 12), MAX_COLUMN_WIDTH)

    if freeze:
        worksheet.freeze_panes = freeze
    if autofilter and worksheet.max_row > 1:
        worksheet.auto_filter.ref = worksheet.dimensions


def _empty_placeholder() -> pd.DataFrame:
    """Feuille lisible lorsqu'aucune propriete n'a ete trouvee."""
    return pd.DataFrame(
        {"Resultat": ["Aucune propriete conforme trouvee - voir la feuille Metadonnees"]}
    )


def _metadata_frame(
    result: ExtractionResult, metadata: Mapping[str, Any] | None
) -> pd.DataFrame:
    """Assemble la feuille de tracabilite de l'extraction."""
    rows: list[tuple[str, Any]] = [
        ("Genere le", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Proprietes conformes", result.count),
        ("Polygones C-4a retenus", len(result.zones)),
        ("Zones de zonage analysees", result.zone_report.total_zones),
        ("Strategie de detection", result.zone_report.strategy),
        ("Colonnes declenchantes", ", ".join(result.zone_report.matched_columns) or "-"),
        ("Exemples de valeurs retenues", "; ".join(result.zone_report.sample_values) or "-"),
        ("Predicat spatial", result.join_predicate),
    ]
    for key, value in (metadata or {}).items():
        rows.append((str(key), value))
    for warning in result.warnings:
        rows.append(("Avertissement", warning))
    return pd.DataFrame(rows, columns=["Cle", "Valeur"])


# --------------------------------------------------------------------------
# CSV / GeoJSON
# --------------------------------------------------------------------------


def write_csv(table: pd.DataFrame, path: Path) -> Path:
    """CSV en UTF-8 avec BOM, pour qu'Excel affiche correctement les accents."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False, encoding="utf-8-sig")
    LOGGER.info("CSV ecrit : %s", path)
    return path


def csv_bytes(table: pd.DataFrame) -> bytes:
    """Version en memoire pour Streamlit."""
    return table.to_csv(index=False).encode("utf-8-sig")


def write_geojson(properties: gpd.GeoDataFrame, path: Path) -> bool:
    """Exporte les lots conformes en GeoJSON (WGS84). Retourne False si vide."""
    if properties is None or properties.empty:
        return False
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exportable = properties.to_crs(GEOGRAPHIC_CRS)
    # Les colonnes non serialisables (dates, objets) sont converties en texte.
    for column in exportable.columns:
        if column == exportable.geometry.name:
            continue
        if exportable[column].dtype == object:
            exportable[column] = exportable[column].astype(str)
    exportable.to_file(path, driver="GeoJSON")
    LOGGER.info("GeoJSON ecrit : %s", path)
    return True

"""V3R_Zonage_C4A_Extractor - extraction des proprietes C-4 / C-4a a Trois-Rivieres."""

from __future__ import annotations

__version__ = "1.0.0"

from .exporter import export_all, write_csv, write_excel
from .fetcher import DataFetcher, FetchResult, LayerSpec
from .spatial_engine import (
    ExtractionResult,
    ZoneFilterReport,
    build_result_table,
    filter_c4_zones,
    join_properties,
    load_layer,
    run_pipeline,
    run_pipeline_from_layers,
)

__all__ = [
    "__version__",
    "DataFetcher",
    "FetchResult",
    "LayerSpec",
    "ExtractionResult",
    "ZoneFilterReport",
    "build_result_table",
    "filter_c4_zones",
    "join_properties",
    "load_layer",
    "run_pipeline",
    "run_pipeline_from_layers",
    "export_all",
    "write_csv",
    "write_excel",
]

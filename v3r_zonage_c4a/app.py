#!/usr/bin/env python3
"""Dashboard Streamlit : proprietes autorisees en zone C-4 / C-4a a Trois-Rivieres.

Lancement :

    streamlit run app.py

Le pipeline complet (telechargement -> intersection spatiale -> table) est
mis en cache par Streamlit : il ne s'execute qu'une fois par session, sauf
demande explicite de rafraichissement.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import streamlit as st

from src.config import CITY_CENTER, DATA_DIR, DEFAULT_CSV_NAME, DEFAULT_EXCEL_NAME, GEOGRAPHIC_CRS
from src.exporter import csv_bytes, excel_bytes
from src.fetcher import ADRESSES_LAYER, LOTS_LAYER, ZONAGE_LAYER, DataFetcher
from src.spatial_engine import (
    ExtractionResult,
    attach_addresses,
    load_layer,
    run_pipeline_from_layers,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Au-dela de ce seuil, les marqueurs individuels rendent la carte inutilisable :
# on regroupe alors les points en clusters.
CLUSTER_THRESHOLD = 300
# Plafond de polygones de lots dessines (les zones restent toujours affichees).
MAX_MAPPED_LOTS = 2000

st.set_page_config(
    page_title="V3R — Zonage C-4a",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------
# Pipeline (mis en cache)
# --------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def run_extraction(force_refresh: bool, predicate: str, use_addresses: bool) -> ExtractionResult:
    """Execute le pipeline complet. Le cache evite de le rejouer a chaque clic."""
    layers = [ZONAGE_LAYER, LOTS_LAYER] + ([ADRESSES_LAYER] if use_addresses else [])
    fetcher = DataFetcher(data_dir=DATA_DIR, force_refresh=force_refresh)
    results = fetcher.fetch_all(layers)

    missing = [r.label for key, r in results.items() if not r.ok and key in ("zonage", "lots")]
    if missing:
        details = "\n".join(
            f"- **{r.label}** : {r.error}" for r in results.values() if not r.ok
        )
        raise RuntimeError(f"Couches obligatoires indisponibles : {', '.join(missing)}\n\n{details}")

    zoning = load_layer(results["zonage"].path)  # type: ignore[arg-type]
    properties = load_layer(results["lots"].path)  # type: ignore[arg-type]

    address_result = results.get("adresses")
    if use_addresses and address_result is not None and address_result.ok:
        try:
            properties = attach_addresses(properties, load_layer(address_result.path))  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - enrichissement facultatif
            logging.warning("Enrichissement adresses ignore : %s", exc)

    return run_pipeline_from_layers(zoning, properties, predicate=predicate)


# --------------------------------------------------------------------------
# Carte
# --------------------------------------------------------------------------


def build_map(result: ExtractionResult, table: pd.DataFrame) -> Any:
    """Carte Folium : zones C-4a en vert + un marqueur par lot admissible."""
    import folium
    from folium.plugins import MarkerCluster

    center = CITY_CENTER
    if not table.empty and table["Latitude"].notna().any():
        center = (float(table["Latitude"].mean()), float(table["Longitude"].mean()))

    fmap = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")

    # 1. Polygones des zones C-4a (vert).
    if not result.zones.empty:
        zones_wgs = result.zones.to_crs(GEOGRAPHIC_CRS)
        zone_label = _zone_label_column(zones_wgs)
        folium.GeoJson(
            zones_wgs.to_json(),
            name="Zones C-4 / C-4a",
            style_function=lambda _feature: {
                "fillColor": "#2E9E5B",
                "color": "#1F6F43",
                "weight": 1.5,
                "fillOpacity": 0.28,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[zone_label] if zone_label else [],
                aliases=["Zone :"] if zone_label else [],
            ),
        ).add_to(fmap)

    # 2. Marqueurs des lots admissibles.
    mapped = table.dropna(subset=["Latitude", "Longitude"]).head(MAX_MAPPED_LOTS)
    if not mapped.empty:
        layer: Any = folium.FeatureGroup(name="Lots admissibles")
        container: Any = MarkerCluster().add_to(layer) if len(mapped) > CLUSTER_THRESHOLD else layer
        for _, row in mapped.iterrows():
            folium.CircleMarker(
                location=(float(row["Latitude"]), float(row["Longitude"])),
                radius=4,
                color="#0B4F6C",
                fill=True,
                fill_color="#0B4F6C",
                fill_opacity=0.9,
                weight=1,
                popup=folium.Popup(_popup_html(row), max_width=320),
                tooltip=str(row.get("Adresse") or row.get("Matricule") or "Lot"),
            ).add_to(container)
        layer.add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap


def _zone_label_column(zones: gpd.GeoDataFrame) -> str | None:
    """Premiere colonne exploitable comme etiquette de zone dans l'infobulle."""
    for candidate in ("zone", "no_zone", "num_zone", "zonage", "code_zone", "designation"):
        if candidate in zones.columns:
            return candidate
    non_geometry = [c for c in zones.columns if c != zones.geometry.name]
    return non_geometry[0] if non_geometry else None


def _popup_html(row: pd.Series) -> str:
    """Fiche de la propriete affichee au clic sur un marqueur."""
    import html

    fields = [
        ("Adresse", row.get("Adresse")),
        ("Zone", row.get("Zone")),
        ("Classe d'usage", row.get("Classe d'usage")),
        ("Matricule", row.get("Matricule")),
        ("Numero de lot", row.get("Numero de lot")),
        ("Superficie (m2)", row.get("Superficie (m2)")),
    ]
    lines = "".join(
        f"<tr><td style='padding-right:8px;color:#555'>{html.escape(label)}</td>"
        f"<td><b>{html.escape(str(value))}</b></td></tr>"
        for label, value in fields
        if value is not None and not pd.isna(value)
    )
    return f"<table style='font-size:12px'>{lines}</table>"


# --------------------------------------------------------------------------
# Filtres
# --------------------------------------------------------------------------


def apply_filters(table: pd.DataFrame) -> pd.DataFrame:
    """Barre laterale : recherche plein texte + filtre par zone."""
    st.sidebar.header("Filtres")

    zones = sorted(table["Zone"].dropna().astype(str).unique()) if "Zone" in table else []
    selected = st.sidebar.multiselect("Zones", zones, default=[], help="Vide = toutes les zones")

    query = st.sidebar.text_input(
        "Recherche", "", placeholder="rue, matricule, numero de lot..."
    ).strip()

    filtered = table
    if selected:
        filtered = filtered[filtered["Zone"].astype(str).isin(selected)]
    if query:
        haystack = filtered.astype(str).apply(lambda col: col.str.lower())
        mask = haystack.apply(lambda col: col.str.contains(query.lower(), na=False, regex=False)).any(axis=1)
        filtered = filtered[mask]
    return filtered


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------


def main() -> None:
    st.title("🏠 Propriétés autorisées en zone C-4 / C-4a — Trois-Rivières")
    st.caption(
        "Intersection spatiale globale entre la matrice foncière et le zonage municipal "
        "(source : Données Québec, Ville de Trois-Rivières)."
    )

    st.sidebar.header("Extraction")
    predicate = st.sidebar.selectbox(
        "Prédicat spatial",
        ("auto", "within", "intersects"),
        help="auto : affectation par point représentatif, repli sur intersects.",
    )
    use_addresses = st.sidebar.checkbox(
        "Enrichir avec la couche d'adresses", value=True,
        help="Joint les adresses civiques aux lots par proximité (25 m).",
    )
    if st.sidebar.button("🔄 Retélécharger les données", use_container_width=True):
        st.cache_resource.clear()
        st.session_state["force_refresh"] = True

    force_refresh = st.session_state.pop("force_refresh", False)

    with st.spinner("Téléchargement des couches et intersection spatiale…"):
        try:
            result = run_extraction(force_refresh, predicate, use_addresses)
        except Exception as exc:  # noqa: BLE001 - message lisible plutot qu'une trace
            st.error("Le pipeline n'a pas pu s'exécuter.")
            st.markdown(str(exc))
            st.info(
                f"Vous pouvez déposer les fichiers manuellement dans "
                f"`{DATA_DIR / 'manuel' / '<couche>'}/` puis relancer "
                "(voir le README, section « Mode hors ligne »)."
            )
            st.stop()
            return

    table = result.table

    # --- Statistiques ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Propriétés conformes", f"{result.count:,}".replace(",", " "))
    col2.metric("Zones C-4 / C-4a", f"{len(result.zones):,}".replace(",", " "))
    col3.metric("Zones distinctes", table["Zone"].nunique() if "Zone" in table else 0)
    col4.metric("Prédicat", result.join_predicate.split(" ")[0])

    for warning in result.warnings:
        st.warning(warning)

    if table.empty:
        st.info("Aucune propriété conforme trouvée avec les paramètres actuels.")
        with st.expander("Diagnostic de détection des zones"):
            st.write(result.zone_report.summary())
            st.write(result.zone_report.sample_values)
        return

    filtered = apply_filters(table)

    tab_table, tab_map, tab_stats = st.tabs(
        ["📋 Propriétés", "🗺️ Carte interactive", "📊 Répartition"]
    )

    with tab_table:
        st.caption(f"{len(filtered)} propriété(s) affichée(s) sur {len(table)}.")
        st.dataframe(filtered, use_container_width=True, hide_index=True, height=560)

    with tab_map:
        try:
            from streamlit_folium import st_folium

            st_folium(build_map(result, filtered), use_container_width=True, height=620,
                      returned_objects=[])
        except ImportError:
            st.error("Installez `folium` et `streamlit-folium` : pip install -r requirements.txt")

    with tab_stats:
        breakdown = result.zone_breakdown()
        left, right = st.columns([1, 2])
        with left:
            st.dataframe(breakdown, use_container_width=True, hide_index=True, height=420)
        with right:
            st.bar_chart(breakdown.set_index("Zone").head(25), height=420)

    # --- Telechargements ---
    st.sidebar.header("Export")
    stamp = datetime.now().strftime("%Y%m%d")
    st.sidebar.download_button(
        "⬇️ Excel (.xlsx)",
        data=excel_bytes(result),
        file_name=DEFAULT_EXCEL_NAME,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.sidebar.download_button(
        "⬇️ CSV (sélection filtrée)",
        data=csv_bytes(filtered),
        file_name=f"proprietes_c4a_filtre_{stamp}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.sidebar.download_button(
        "⬇️ CSV (liste complète)",
        data=csv_bytes(table),
        file_name=DEFAULT_CSV_NAME,
        mime="text/csv",
        use_container_width=True,
    )

    with st.expander("ℹ️ Traçabilité de l'extraction"):
        st.write(result.zone_report.summary())
        if result.zone_report.sample_values:
            st.write("Valeurs ayant déclenché la sélection :", result.zone_report.sample_values)
        st.caption(
            "Vérification obligatoire : ce résultat reflète le zonage cartographique. "
            "La conformité finale d'un usage d'hébergement touristique doit être validée "
            "auprès du Service de l'aménagement de la Ville de Trois-Rivières et de la CITQ."
        )


if __name__ == "__main__":
    main()

"""Couches synthetiques pour la demonstration et les tests.

ATTENTION : ces donnees sont FICTIVES. Elles servent uniquement a valider le
pipeline (filtrage C-4, sjoin, exports) sans acces reseau, et a montrer le
format de sortie. Elles ne doivent jamais etre confondues avec les donnees
officielles de la Ville de Trois-Rivieres.
"""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Polygon

from .config import WORKING_CRS

# Origine des geometries : centre-ville de Trois-Rivieres projete en MTM 8,
# pour que les latitudes / longitudes produites restent plausibles.
ORIGIN_X: float = 378_100.0
ORIGIN_Y: float = 5_134_160.0


def square(x: float, y: float, size: float = 100.0) -> Polygon:
    """Carre de `size` metres, positionne relativement a l'origine V3R."""
    x, y = ORIGIN_X + x, ORIGIN_Y + y
    return Polygon([(x, y), (x + size, y), (x + size, y + size), (x, y + size)])


def make_demo_zoning() -> gpd.GeoDataFrame:
    """Zonage fictif : une zone C-4a, une zone d'hebergement, une residentielle."""
    return gpd.GeoDataFrame(
        {
            "no_zone": ["C-104", "C-210", "H-330"],
            "classe_usage": ["C-4a", "Hébergement touristique", "H-1"],
            "geometry": [square(0, 0, 400), square(500, 0, 400), square(1000, 0, 400)],
        },
        crs=WORKING_CRS,
    )


def make_demo_properties() -> gpd.GeoDataFrame:
    """Matrice fonciere fictive : 5 lots, dont 3 en zone C-4."""
    return gpd.GeoDataFrame(
        {
            "matricule": ["1234-56-7890", "1234-56-7891", "2234-56-7892",
                          "3234-56-7893", "4234-56-7894"],
            "no_lot": ["1 111 111", "1 111 112", "2 222 221", "3 333 331", "4 444 441"],
            "no_civique": [100, 102, 250, 400, 900],
            "nom_rue": ["rue Notre-Dame", "rue Notre-Dame", "rue des Ursulines",
                        "rue Laviolette", "boul. des Chenaux"],
            "geometry": [
                square(50, 50), square(200, 50),   # zone C-104
                square(550, 50),                    # zone C-210
                square(1050, 50),                   # zone H-330 (exclu)
                square(2000, 2000),                 # hors zonage (exclu)
            ],
        },
        crs=WORKING_CRS,
    )

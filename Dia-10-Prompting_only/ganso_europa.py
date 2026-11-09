"""Crea un GIF anual de observaciones europeas del ganso del Nilo en GBIF."""

from pathlib import Path
import time
from typing import Dict, Optional, Tuple

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
import pandas as pd
import requests


# Parámetros editables
MAX_PER_YEAR = 2000
YEAR_MIN = 1970
YEAR_MAX = 2025
OUTPUT_GIF = Path("ganso_nilo_europa.gif")
CACHE_DIR = Path("cache_gbif_ganso")

SPECIES_NAME = "Alopochen aegyptiaca"
GBIF_API = "https://api.gbif.org/v1"
GBIF_PAGE_SIZE = 300
GBIF_MAX_OFFSET = 100_000
REQUEST_PAUSE_SECONDS = 0.25
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

COUNT_CSV = CACHE_DIR / "conteos_por_ano.csv"
RECORD_COLUMNS = [
    "gbifID",
    "year",
    "decimalLatitude",
    "decimalLongitude",
]

# Extensión de Europa occidental y central en EPSG:3035.
MAP_X_LIMITS = (2_000_000, 5_800_000)
MAP_Y_LIMITS = (1_300_000, 5_500_000)

NATURAL_EARTH_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_cultural/"
    "ne_10m_admin_0_countries.zip"
)


def request_json(
    session: requests.Session,
    url: str,
    params: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Solicita JSON con reintentos limitados y pausas entre peticiones."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                url, params=params, timeout=REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Falló la petición a GBIF después de {MAX_RETRIES} intentos: "
                    f"{url}"
                ) from exc
            time.sleep(attempt)
            continue

        time.sleep(REQUEST_PAUSE_SECONDS)
        return payload

    raise RuntimeError("La petición a GBIF terminó sin una respuesta válida.")


def get_taxon_key(session: requests.Session) -> int:
    """Obtiene el identificador de especie usando species/match."""
    payload = request_json(
        session,
        f"{GBIF_API}/species/match",
        params={"name": SPECIES_NAME},
    )
    if (
        payload.get("rank") != "SPECIES"
        or payload.get("canonicalName") != SPECIES_NAME
        or not isinstance(payload.get("usageKey"), int)
    ):
        raise ValueError(
            "GBIF no devolvió una coincidencia inequívoca para "
            f"{SPECIES_NAME}: {payload}"
        )
    return payload["usageKey"]


def get_year_counts(
    session: requests.Session, taxon_key: int
) -> Tuple[Dict[int, int], int]:
    """Consulta y guarda la faceta de año antes de descargar ocurrencias."""
    payload = request_json(
        session,
        f"{GBIF_API}/occurrence/search",
        params={
            "taxonKey": taxon_key,
            "continent": "EUROPE",
            "hasCoordinate": "true",
            "hasGeospatialIssue": "false",
            "limit": 0,
            "facet": "year",
            "facetLimit": 100,
        },
    )

    facets = payload.get("facets")
    if not isinstance(facets, list):
        raise ValueError(f"Respuesta de facetas inesperada de GBIF: {payload}")
    year_facet = next(
        (facet for facet in facets if facet.get("field", "").upper() == "YEAR"),
        None,
    )
    if year_facet is None:
        raise ValueError("GBIF no devolvió la faceta YEAR solicitada.")

    counts: Dict[int, int] = {}
    rows = []
    for item in year_facet.get("counts", []):
        year_text = item.get("name")
        try:
            year = int(year_text)
            count = int(item["count"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"Valor de faceta YEAR inválido: {item}") from exc
        counts[year] = count
        rows.append({"year": year, "records": count})

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["year", "records"]).sort_values(
        "year"
    ).to_csv(COUNT_CSV, index=False)

    total = int(payload.get("count", 0))
    print(f"GBIF informa {total:,} ocurrencias para los filtros seleccionados.")
    print("Ocurrencias por año (faceta de GBIF):")
    for row in sorted(rows, key=lambda item: item["year"]):
        print(f"  {row['year']}: {row['records']:,}")
    print(f"Conteos guardados en: {COUNT_CSV}")
    return counts, total


def download_year(
    session: requests.Session, taxon_key: int, year: int
) -> pd.DataFrame:
    """Descarga hasta MAX_PER_YEAR registros de un año, paginando en GBIF."""
    cache_file = CACHE_DIR / f"ocurrencias_{year}_max{MAX_PER_YEAR}.csv"
    if cache_file.exists():
        print(f"  {year}: usando caché {cache_file.name}")
        return pd.read_csv(cache_file)

    records = []
    offset = 0
    while len(records) < MAX_PER_YEAR:
        if offset > GBIF_MAX_OFFSET:
            raise RuntimeError(
                f"Se alcanzó el offset máximo configurado de GBIF para {year}. "
                "Reduce MAX_PER_YEAR."
            )
        page_limit = min(GBIF_PAGE_SIZE, MAX_PER_YEAR - len(records))
        payload = request_json(
            session,
            f"{GBIF_API}/occurrence/search",
            params={
                "taxonKey": taxon_key,
                "continent": "EUROPE",
                "hasCoordinate": "true",
                "hasGeospatialIssue": "false",
                "year": year,
                "limit": page_limit,
                "offset": offset,
            },
        )
        page = payload.get("results")
        if not isinstance(page, list):
            raise ValueError(
                f"GBIF devolvió resultados inesperados para {year}: {payload}"
            )
        if not page:
            if payload.get("endOfRecords") is False:
                raise RuntimeError(
                    f"GBIF devolvió una página vacía no final para {year} "
                    f"(offset {offset})."
                )
            break

        records.extend(
            {
                column: record.get(column)
                for column in RECORD_COLUMNS
            }
            for record in page
        )
        offset += len(page)
        if payload.get("endOfRecords") is True:
            break

    frame = pd.DataFrame(records, columns=RECORD_COLUMNS)
    frame.to_csv(cache_file, index=False)
    print(f"  {year}: guardados {len(frame):,} registros en caché.")
    return frame


def load_occurrences(
    session: requests.Session,
    taxon_key: int,
    year_counts: Dict[int, int],
) -> pd.DataFrame:
    """Carga registros por año, aplica el tope y elimina coordenadas duplicadas."""
    frames = []
    for year in range(YEAR_MIN, YEAR_MAX + 1):
        if year_counts.get(year, 0) == 0:
            continue
        print(f"Descargando año {year} (máximo {MAX_PER_YEAR} registros)...")
        frames.append(download_year(session, taxon_key, year))

    if not frames:
        return pd.DataFrame(columns=["year", "x", "y"])

    occurrences = pd.concat(frames, ignore_index=True)
    occurrences["decimalLatitude"] = pd.to_numeric(
        occurrences["decimalLatitude"], errors="coerce"
    )
    occurrences["decimalLongitude"] = pd.to_numeric(
        occurrences["decimalLongitude"], errors="coerce"
    )
    occurrences = occurrences.dropna(
        subset=["decimalLatitude", "decimalLongitude"]
    )
    occurrences = occurrences[
        occurrences["decimalLatitude"].between(-90, 90)
        & occurrences["decimalLongitude"].between(-180, 180)
    ]
    occurrences = occurrences.drop_duplicates(
        subset=["year", "decimalLatitude", "decimalLongitude"]
    )

    points = gpd.GeoDataFrame(
        occurrences,
        geometry=gpd.points_from_xy(
            occurrences["decimalLongitude"], occurrences["decimalLatitude"]
        ),
        crs="EPSG:4326",
    ).to_crs("EPSG:3035")
    points["x"] = points.geometry.x
    points["y"] = points.geometry.y
    points = points[
        points["x"].between(*MAP_X_LIMITS)
        & points["y"].between(*MAP_Y_LIMITS)
    ]
    return pd.DataFrame(points[["year", "x", "y"]])


def load_countries() -> gpd.GeoDataFrame:
    """Carga países de GeoPandas o descarga el shapefile de Natural Earth."""
    datasets = getattr(gpd, "datasets", None)
    if datasets is not None:
        try:
            countries_path = datasets.get_path("naturalearth_lowres")
            return gpd.read_file(countries_path)
        except (AttributeError, ImportError, OSError, ValueError):
            pass

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = CACHE_DIR / "ne_10m_admin_0_countries.zip"
    if not archive_path.exists():
        response = requests.get(NATURAL_EARTH_URL, timeout=60)
        response.raise_for_status()
        archive_path.write_bytes(response.content)
    return gpd.read_file(f"zip://{archive_path.as_posix()}")


def create_animation(points: pd.DataFrame) -> None:
    """Dibuja un fotograma por año y guarda la animación como GIF."""
    countries = load_countries().to_crs("EPSG:3035")
    years = list(range(YEAR_MIN, YEAR_MAX + 1))

    fig, ax = plt.subplots(figsize=(8, 7), dpi=90)
    countries.plot(
        ax=ax,
        color="#f1eee7",
        edgecolor="#a7a49d",
        linewidth=0.45,
    )
    ax.set_xlim(*MAP_X_LIMITS)
    ax.set_ylim(*MAP_Y_LIMITS)
    ax.set_axis_off()
    ax.set_title(
        "Expansión del ganso del Nilo en Europa",
        fontsize=15,
        pad=14,
    )

    history = ax.scatter(
        [],
        [],
        s=9,
        color="#7296a5",
        alpha=0.28,
        linewidths=0,
    )
    current = ax.scatter(
        [],
        [],
        s=18,
        color="#d95f3d",
        alpha=0.85,
        linewidths=0,
    )
    year_label = ax.text(
        0.97,
        0.95,
        "",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=28,
        fontweight="bold",
        color="#24343b",
    )
    count_label = ax.text(
        0.03,
        0.04,
        "",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        color="#24343b",
        bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"},
    )
    fig.text(
        0.5,
        0.025,
        "Fuente: GBIF.org · Ocurrencias con coordenadas; "
        "muestra limitada por año",
        ha="center",
        fontsize=8,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))

    def update(year: int):
        previous = points[points["year"] < year]
        this_year = points[points["year"] == year]
        accumulated = points[points["year"] <= year]
        history.set_offsets(previous[["x", "y"]].to_numpy())
        current.set_offsets(this_year[["x", "y"]].to_numpy())
        year_label.set_text(str(year))
        count_label.set_text(
            f"Registros acumulados: {len(accumulated):,}"
        )
        return history, current, year_label, count_label

    animation = FuncAnimation(
        fig,
        update,
        frames=years,
        interval=500,
        repeat=False,
        blit=False,
    )
    OUTPUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    animation.save(OUTPUT_GIF, writer=PillowWriter(fps=2))
    plt.close(fig)
    print(f"GIF guardado en: {OUTPUT_GIF}")


def main() -> None:
    if not 1 <= MAX_PER_YEAR <= GBIF_MAX_OFFSET:
        raise ValueError(
            f"MAX_PER_YEAR debe estar entre 1 y {GBIF_MAX_OFFSET}."
        )
    if YEAR_MIN > YEAR_MAX:
        raise ValueError("YEAR_MIN no puede ser mayor que YEAR_MAX.")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        taxon_key = get_taxon_key(session)
        print(f"TaxonKey de {SPECIES_NAME}: {taxon_key}")
        year_counts, _ = get_year_counts(session, taxon_key)
        points = load_occurrences(session, taxon_key, year_counts)

    if points.empty:
        raise RuntimeError(
            "No quedaron registros con coordenadas dentro de la vista del mapa."
        )
    create_animation(points)


if __name__ == "__main__":
    main()
    

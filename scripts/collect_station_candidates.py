from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "station_collector.json"
DEFAULT_OUTPUT = ROOT / "data" / "collection" / "station_candidates.json"
DEFAULT_KML_OUTPUT = ROOT / "data" / "collection" / "station_search_area.kml"
MASTER_STATIONS = ROOT / "data" / "static" / "stations.geojson"


class CollectorError(RuntimeError):
    pass


class ListItemParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.buffer: list[str] = []
        self.items: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self.depth += 1
            if self.depth == 1:
                self.buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "li" or self.depth == 0:
            return
        if self.depth == 1:
            text = " ".join("".join(self.buffer).split())
            if text:
                self.items.append(text)
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.buffer.append(data)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request_text(url: str, *, user_agent: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise CollectorError(f"HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise CollectorError(f"network error: {exc.reason if isinstance(exc, URLError) else exc}") from exc


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None,
    user_agent: str,
    timeout: int,
    post: bool = False,
) -> Any:
    encoded = urlencode(params or {}).encode("utf-8")
    if post:
        request = Request(
            url,
            data=encoded,
            headers={
                "User-Agent": user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    else:
        separator = "&" if "?" in url else "?"
        request = Request(
            url + (separator + encoded.decode("utf-8") if encoded else ""),
            headers={"User-Agent": user_agent},
        )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise CollectorError(f"HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise CollectorError(f"network error: {exc.reason if isinstance(exc, URLError) else exc}") from exc
    except json.JSONDecodeError as exc:
        raise CollectorError("response was not valid JSON") from exc


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def in_bounds(lat: float, lon: float, bounds: dict[str, float]) -> bool:
    return bounds["south"] <= lat <= bounds["north"] and bounds["west"] <= lon <= bounds["east"]


def configured_bounds(config: dict[str, Any]) -> list[dict[str, float]]:
    bounds = config.get("search_bounds")
    if bounds:
        return bounds
    return [config["demo_bounds"]]


def in_configured_bounds(lat: float, lon: float, config: dict[str, Any]) -> bool:
    return any(in_bounds(lat, lon, bounds) for bounds in configured_bounds(config))


def haversine_m(first: dict[str, float], second: dict[str, float]) -> float:
    radius_m = 6_371_000
    lat1, lat2 = math.radians(first["lat"]), math.radians(second["lat"])
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second["lon"] - first["lon"])
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_m * math.asin(math.sqrt(value))


def goong_search_centers(config: dict[str, Any]) -> list[dict[str, Any]]:
    bounds_list = configured_bounds(config)
    spacing_km = float(config.get("goong_grid_spacing_km", 0))
    minimum_separation_m = spacing_km * 1_000 * 0.35
    centers: list[dict[str, Any]] = []

    def add_center(center: dict[str, Any]) -> None:
        point = {"lat": float(center["lat"]), "lon": float(center["lon"])}
        if not in_configured_bounds(point["lat"], point["lon"], config):
            return
        if minimum_separation_m and any(
            haversine_m(point, existing) < minimum_separation_m for existing in centers
        ):
            return
        centers.append({**center, **point})

    for center in config.get("search_centers", []):
        add_center(center)

    if spacing_km <= 0:
        return centers

    for bounds in bounds_list:
        latitude_km = max((bounds["north"] - bounds["south"]) * 111.32, 0)
        middle_latitude = (bounds["south"] + bounds["north"]) / 2
        longitude_km = max(
            (bounds["east"] - bounds["west"])
            * 111.32
            * math.cos(math.radians(middle_latitude)),
            0,
        )
        rows = max(1, math.ceil(latitude_km / spacing_km))
        columns = max(1, math.ceil(longitude_km / spacing_km))
        for row in range(rows):
            lat = bounds["south"] + (row + 0.5) * (
                bounds["north"] - bounds["south"]
            ) / rows
            for column in range(columns):
                lon = bounds["west"] + (column + 0.5) * (
                    bounds["east"] - bounds["west"]
                ) / columns
                add_center(
                    {
                        "name": f'{bounds.get("name", "bounds")}_{row + 1}_{column + 1}',
                        "lat": lat,
                        "lon": lon,
                    }
                )

    return centers


def make_candidate(
    *,
    provider: str,
    provider_id: str,
    name: str,
    address: str | None,
    lat: float | None,
    lon: float | None,
    operator: str | None,
    access: str = "unknown",
    source_url: str | None = None,
    source_attributes: dict[str, Any] | None = None,
    technical: dict[str, Any] | None = None,
    site_amenities: list[dict[str, Any]] | None = None,
    review_status: str = "pending",
    matched_station_id: str | None = None,
) -> dict[str, Any]:
    return {
        "candidate_id": None,
        "name": name,
        "address": address,
        "location": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
        "operator": operator,
        "access": access,
        "technical": technical or {"total_ports": None, "connectors": []},
        "site_amenities": site_amenities or [],
        "provider_refs": [
            {
                "provider": provider,
                "provider_id": str(provider_id),
                "source_url": source_url,
            }
        ],
        "source_attributes": {provider: source_attributes or {}},
        "review_status": review_status,
        "review_notes": [],
        "matched_station_id": matched_station_id,
    }


def existing_master_candidates() -> list[dict[str, Any]]:
    data = read_json(MASTER_STATIONS)
    candidates = []
    for feature in data.get("features", []):
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        amenity_status = (
            "unverified"
            if "amenities" in props.get("synthetic_fields", [])
            else "reviewed"
        )
        candidates.append(
            make_candidate(
                provider="existing_master",
                provider_id=props["station_id"],
                name=props["name"],
                address=props["address"],
                lat=lat,
                lon=lon,
                operator=props.get("operator"),
                access=props.get("access", "unknown"),
                source_url=None,
                source_attributes={"source_provider": props.get("source_provider")},
                technical={
                    "total_ports": props.get("total_ports"),
                    "connectors": props.get("connectors", []),
                },
                site_amenities=[
                    {
                        "code": code,
                        "is_available": True,
                        "status": amenity_status,
                        "evidence": "existing_master",
                    }
                    for code in props.get("amenities", [])
                ],
                review_status="verified",
                matched_station_id=props["station_id"],
            )
        )
    return candidates


def geocode_nominatim(query: str, config: dict[str, Any]) -> dict[str, Any] | None:
    results = request_json(
        config["nominatim_url"],
        params={"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1},
        user_agent=config["user_agent"],
        timeout=config["http_timeout_s"],
    )
    time.sleep(1)
    if not results:
        return None
    result = results[0]
    return {
        "lat": float(result["lat"]),
        "lon": float(result["lon"]),
        "display_name": result.get("display_name"),
        "osm_type": result.get("osm_type"),
        "osm_id": result.get("osm_id"),
    }


def parse_evone_items(html: str) -> list[dict[str, str]]:
    parser = ListItemParser()
    parser.feed(html)
    stations = []
    for item in parser.items:
        if not re.match(r"^EV\s*ONE\s*[–-]", item, flags=re.IGNORECASE):
            continue
        if not re.search(r"TP\.?\s*HCM|Hồ Chí Minh", item, flags=re.IGNORECASE):
            continue
        if ":" not in item:
            continue
        name, remainder = item.split(":", 1)
        details = ""
        detail_match = re.search(r"\(([^()]*(?:AC|DC|kW|KW|trụ)[^()]*)\)\s*$", remainder)
        if detail_match:
            details = detail_match.group(1).strip()
            remainder = remainder[: detail_match.start()]
        stations.append(
            {
                "name": " ".join(name.split()),
                "address": " ".join(remainder.split()).strip(" -"),
                "published_details": details,
            }
        )
    return stations


def collect_evone(config: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    html = request_text(
        config["evone_url"],
        user_agent=config["user_agent"],
        timeout=config["http_timeout_s"],
    )
    records = parse_evone_items(html)
    if not records:
        warnings.append("EV ONE page returned no parseable HCMC station list items")
    candidates = []
    for record in records:
        location = None
        for query in (
            f'{record["address"]}, Việt Nam',
            f'{record["name"]}, Hồ Chí Minh, Việt Nam',
        ):
            try:
                location = geocode_nominatim(query, config)
            except CollectorError as exc:
                warnings.append(f'OSM geocoding failed for {record["name"]}: {exc}')
                break
            if location:
                break
        if not location:
            warnings.append(f'No coordinates found for EV ONE candidate: {record["name"]}')
        elif not in_configured_bounds(location["lat"], location["lon"], config):
            continue
        provider_id = normalize_text(record["name"] + " " + record["address"])
        candidate = make_candidate(
            provider="evone",
            provider_id=provider_id,
            name=record["name"],
            address=record["address"],
            lat=location["lat"] if location else None,
            lon=location["lon"] if location else None,
            operator="EV ONE",
            source_url=config["evone_url"],
            source_attributes={"published_details": record["published_details"]},
        )
        if location:
            candidate["provider_refs"].append(
                {
                    "provider": "osm_nominatim",
                    "provider_id": f'{location["osm_type"]}/{location["osm_id"]}',
                    "source_url": config["nominatim_url"],
                }
            )
            candidate["source_attributes"]["osm_nominatim"] = {
                "display_name": location["display_name"]
            }
        candidates.append(candidate)
    return candidates


def osm_address(tags: dict[str, Any]) -> str | None:
    if tags.get("addr:full"):
        return tags["addr:full"]
    parts = [
        " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")])),
        tags.get("addr:suburb"),
        tags.get("addr:city"),
    ]
    address = ", ".join(part for part in parts if part)
    return address or None


def osm_access(value: str | None) -> str:
    if value in {"yes", "public", "permissive"}:
        return "public"
    if value in {"customers", "private"}:
        return value
    return "unknown"


def osm_site_amenities(tags: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []

    def add(code: str, key: str) -> None:
        claims.append(
            {
                "code": code,
                "is_available": True,
                "status": "provider_reported",
                "evidence": f"{key}={tags[key]}",
            }
        )

    if tags.get("toilets") in {"yes", "customers"}:
        add("restroom", "toilets")
    if tags.get("internet_access") in {"yes", "wlan", "wifi"}:
        add("wifi", "internet_access")
    if tags.get("parking") not in {None, "no"}:
        add("parking", "parking")
    if tags.get("shop") not in {None, "no"}:
        add("retail", "shop")
    if tags.get("food") == "yes":
        add("food", "food")
    vending = normalize_text(str(tags.get("vending", "")))
    if any(item in vending.split() for item in ("drinks", "coffee", "water", "milk")):
        add("beverage", "vending")
    if tags.get("rest_area") == "yes":
        add("rest_area", "rest_area")
    return claims


def request_overpass(query: str, config: dict[str, Any]) -> dict[str, Any]:
    urls = list(
        dict.fromkeys(
            [config["overpass_url"], *config.get("overpass_fallback_urls", [])]
        )
    )
    attempts = max(1, int(config.get("overpass_max_attempts", 1)))
    retry_base_s = max(0.0, float(config.get("overpass_retry_base_s", 1)))
    retry_max_s = max(retry_base_s, float(config.get("overpass_retry_max_s", 20)))
    overpass_timeout_s = int(config.get("overpass_timeout_s", 45))
    errors: list[str] = []

    for attempt in range(attempts):
        url = urls[attempt % len(urls)]
        try:
            return request_json(
                url,
                params={"data": query},
                user_agent=config["user_agent"],
                timeout=max(int(config["http_timeout_s"]), overpass_timeout_s + 5),
                post=True,
            )
        except CollectorError as exc:
            errors.append(f"{url}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(min(retry_base_s * (2**attempt), retry_max_s))

    raise CollectorError(
        f"failed after {attempts} attempts ({'; '.join(errors)})"
    )


def collect_osm(
    config: dict[str, Any], warnings: list[str] | None = None
) -> list[dict[str, Any]]:
    elements: dict[str, dict[str, Any]] = {}
    overpass_timeout_s = int(config.get("overpass_timeout_s", 45))
    successful_queries = 0
    for index, bounds in enumerate(configured_bounds(config)):
        label = bounds.get("name", str(index + 1))
        print(f"OSM search bounds {label}...", flush=True)
        bbox = f'{bounds["south"]},{bounds["west"]},{bounds["north"]},{bounds["east"]}'
        query = (
            f'[out:json][timeout:{overpass_timeout_s}];('
            f'nwr["amenity"="charging_station"]({bbox});'
            f'nwr["fuel:electricity"="yes"]({bbox});'
            ');out center tags;'
        )
        try:
            data = request_overpass(query, config)
        except CollectorError as exc:
            if warnings is not None:
                warnings.append(f"OSM search bounds {label} skipped: {exc}")
            print(f"OSM search bounds {label}: failed ({exc})", flush=True)
            continue
        successful_queries += 1
        print(
            f'OSM search bounds {label}: {len(data.get("elements", []))} elements',
            flush=True,
        )
        for element in data.get("elements", []):
            provider_id = f'{element.get("type")}/{element.get("id")}'
            elements[provider_id] = element
        if index + 1 < len(configured_bounds(config)):
            time.sleep(float(config.get("overpass_delay_s", 0)))

    if successful_queries == 0:
        raise CollectorError("all OSM search-bound queries failed")

    candidates = []
    for provider_id, element in elements.items():
        tags = element.get("tags", {})
        lat = element.get("lat", element.get("center", {}).get("lat"))
        lon = element.get("lon", element.get("center", {}).get("lon"))
        if lat is None or lon is None or not in_configured_bounds(float(lat), float(lon), config):
            continue
        name = tags.get("name") or tags.get("operator") or f"OSM charging station {provider_id}"
        capacity = tags.get("capacity")
        try:
            total_ports = int(capacity) if capacity is not None else None
        except (TypeError, ValueError):
            total_ports = None
        source_attributes = {
            key: value
            for key, value in tags.items()
            if key
            in {
                "access",
                "amenity",
                "brand",
                "capacity",
                "charging_station",
                "fuel:electricity",
                "motorcar",
                "motorcycle",
                "network",
                "opening_hours",
                "operator",
                "food",
                "internet_access",
                "parking",
                "rest_area",
                "shop",
                "toilets",
                "vending",
            }
            or key.startswith(("authentication:", "payment:", "socket:"))
        }
        candidates.append(
            make_candidate(
                provider="osm_overpass",
                provider_id=provider_id,
                name=name,
                address=osm_address(tags),
                lat=float(lat),
                lon=float(lon),
                operator=tags.get("operator") or tags.get("brand"),
                access=osm_access(tags.get("access")),
                source_url="https://www.openstreetmap.org/" + provider_id,
                source_attributes=source_attributes,
                technical={"total_ports": total_ports, "connectors": []},
                site_amenities=osm_site_amenities(tags),
            )
        )
    return candidates


def collect_goong(
    config: dict[str, Any], api_key: str, warnings: list[str] | None = None
) -> list[dict[str, Any]]:
    predictions: dict[str, dict[str, Any]] = {}
    for center in goong_search_centers(config):
        location = f'{center["lat"]},{center["lon"]}'
        for term in config["search_terms"]:
            try:
                data = request_json(
                    config["goong_autocomplete_url"],
                    params={"api_key": api_key, "input": term, "location": location},
                    user_agent=config["user_agent"],
                    timeout=config["http_timeout_s"],
                )
            except CollectorError as exc:
                if warnings is not None:
                    label = center.get("name", location)
                    warnings.append(f"Goong autocomplete {label!r}/{term!r} skipped: {exc}")
                continue
            for prediction in data.get("predictions", []):
                place_id = prediction.get("place_id")
                if place_id:
                    predictions.setdefault(place_id, prediction)

    candidates = []
    for place_id, prediction in predictions.items():
        try:
            data = request_json(
                config["goong_detail_url"],
                params={"api_key": api_key, "place_id": place_id},
                user_agent=config["user_agent"],
                timeout=config["http_timeout_s"],
            )
        except CollectorError as exc:
            if warnings is not None:
                warnings.append(f"Goong place detail {place_id!r} skipped: {exc}")
            continue
        result = data.get("result", data)
        location = result.get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lon = location.get("lng", location.get("lon"))
        if lat is None or lon is None or not in_configured_bounds(float(lat), float(lon), config):
            continue
        name = result.get("name") or prediction.get("structured_formatting", {}).get("main_text")
        name = name or prediction.get("description") or f"Goong place {place_id}"
        candidates.append(
            make_candidate(
                provider="goong_places",
                provider_id=place_id,
                name=name,
                address=result.get("formatted_address") or prediction.get("description"),
                lat=float(lat),
                lon=float(lon),
                operator=None,
                source_url=config["goong_detail_url"],
                source_attributes={"description": prediction.get("description")},
            )
        )
    return candidates


def source_keys(candidate: dict[str, Any]) -> set[str]:
    return {
        f'{ref["provider"]}:{ref["provider_id"]}'
        for ref in candidate.get("provider_refs", [])
        if ref.get("provider") and ref.get("provider_id")
    }


def is_duplicate(first: dict[str, Any], second: dict[str, Any], distance_m: float) -> bool:
    if source_keys(first) & source_keys(second):
        return True
    first_name = normalize_text(first.get("name"))
    second_name = normalize_text(second.get("name"))
    first_location, second_location = first.get("location"), second.get("location")
    if not first_location or not second_location:
        return bool(first_name and first_name == second_name)
    distance = haversine_m(first_location, second_location)
    similarity = SequenceMatcher(None, first_name, second_name).ratio()
    return distance <= 25 or (distance <= distance_m and similarity >= 0.55)


def merge_into(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    if not target.get("address") and incoming.get("address"):
        target["address"] = incoming["address"]
    if not target.get("location") and incoming.get("location"):
        target["location"] = incoming["location"]
    if not target.get("operator") and incoming.get("operator"):
        target["operator"] = incoming["operator"]
    if target.get("access") == "unknown" and incoming.get("access") != "unknown":
        target["access"] = incoming["access"]
    if target["technical"].get("total_ports") is None:
        target["technical"]["total_ports"] = incoming["technical"].get("total_ports")
    if not target["technical"].get("connectors") and incoming["technical"].get("connectors"):
        target["technical"]["connectors"] = incoming["technical"]["connectors"]
    known_amenities = {
        (claim.get("code"), claim.get("evidence"))
        for claim in target.get("site_amenities", [])
    }
    for claim in incoming.get("site_amenities", []):
        key = (claim.get("code"), claim.get("evidence"))
        if key not in known_amenities:
            target.setdefault("site_amenities", []).append(claim)
            known_amenities.add(key)
    known_refs = source_keys(target)
    for ref in incoming.get("provider_refs", []):
        key = f'{ref["provider"]}:{ref["provider_id"]}'
        if key not in known_refs:
            target["provider_refs"].append(ref)
            known_refs.add(key)
    target["source_attributes"].update(incoming.get("source_attributes", {}))


def deduplicate(candidates: list[dict[str, Any]], distance_m: float) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for candidate in candidates:
        duplicate = next(
            (existing for existing in merged if is_duplicate(existing, candidate, distance_m)),
            None,
        )
        if duplicate:
            merge_into(duplicate, candidate)
        else:
            merged.append(candidate)
    for candidate in merged:
        if candidate.get("matched_station_id"):
            seed = "station:" + candidate["matched_station_id"]
        else:
            seed = sorted(source_keys(candidate))[0]
        candidate["candidate_id"] = "CAND_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()
    return merged


def preserve_reviews(candidates: list[dict[str, Any]], output_path: Path) -> None:
    if not output_path.exists():
        return
    try:
        previous = read_json(output_path).get("candidates", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return
    by_id = {item.get("candidate_id"): item for item in previous}
    by_source: dict[str, dict[str, Any]] = {}
    for item in previous:
        for key in source_keys(item):
            by_source[key] = item
    for candidate in candidates:
        prior = by_id.get(candidate["candidate_id"])
        if not prior:
            prior = next((by_source[key] for key in source_keys(candidate) if key in by_source), None)
        if not prior:
            continue
        if candidate["review_status"] != "verified":
            candidate["review_status"] = prior.get("review_status", "pending")
        candidate["review_notes"] = prior.get("review_notes", [])
        candidate["matched_station_id"] = (
            candidate.get("matched_station_id") or prior.get("matched_station_id")
        )


def write_search_area_kml(
    output_path: Path,
    bounds_list: list[dict[str, float]],
    candidates: list[dict[str, Any]],
) -> None:
    search_areas = []
    for index, bounds in enumerate(bounds_list, start=1):
        polygon = " ".join(
            [
                f'{bounds["west"]},{bounds["south"]},0',
                f'{bounds["east"]},{bounds["south"]},0',
                f'{bounds["east"]},{bounds["north"]},0',
                f'{bounds["west"]},{bounds["north"]},0',
                f'{bounds["west"]},{bounds["south"]},0',
            ]
        )
        search_areas.extend(
            [
                "    <Placemark>",
                f"      <name>Collector search bounds {index}</name>",
                "      <styleUrl>#search-area</styleUrl>",
                "      <Polygon><outerBoundaryIs><LinearRing>",
                f"        <coordinates>{polygon}</coordinates>",
                "      </LinearRing></outerBoundaryIs></Polygon>",
                "    </Placemark>",
            ]
        )
    placemarks = []
    for candidate in candidates:
        location = candidate.get("location")
        if not location:
            continue
        description = escape(
            f'Access: {candidate.get("access", "unknown")} | '
            f'Review: {candidate.get("review_status", "pending")} | '
            f'Address: {candidate.get("address") or "unknown"}'
        )
        placemarks.append(
            "\n".join(
                [
                    "    <Placemark>",
                    f"      <name>{escape(candidate['name'])}</name>",
                    f"      <description>{description}</description>",
                    "      <styleUrl>#station</styleUrl>",
                    "      <Point>",
                    f'        <coordinates>{location["lon"]},{location["lat"]},0</coordinates>',
                    "      </Point>",
                    "    </Placemark>",
                ]
            )
        )
    content = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<kml xmlns="http://www.opengis.net/kml/2.2">',
            "  <Document>",
            "    <name>Smart EV Journey station search area</name>",
            '    <Style id="search-area">',
            "      <LineStyle><color>ff0078ff</color><width>3</width></LineStyle>",
            "      <PolyStyle><color>330078ff</color></PolyStyle>",
            "    </Style>",
            '    <Style id="station">',
            "      <IconStyle><color>ff00a545</color><scale>1.1</scale></IconStyle>",
            "    </Style>",
            *search_areas,
            *placemarks,
            "  </Document>",
            "</kml>",
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect EV charging station candidates")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--kml-output", type=Path, default=DEFAULT_KML_OUTPUT)
    parser.add_argument("--providers", help="Comma-separated remote providers: evone,osm,goong")
    parser.add_argument("--bounds-names", help="Comma-separated search-bound names to run")
    parser.add_argument("--overpass-url", help="Override the configured Overpass endpoint")
    parser.add_argument("--offline", action="store_true", help="Use only existing stations.geojson")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = read_json(args.config)
    if args.overpass_url:
        config["overpass_url"] = args.overpass_url
    if args.bounds_names:
        requested_bounds = {
            item.strip() for item in args.bounds_names.split(",") if item.strip()
        }
        selected_bounds = [
            bounds
            for bounds in configured_bounds(config)
            if bounds.get("name") in requested_bounds
        ]
        selected_names = {bounds.get("name") for bounds in selected_bounds}
        missing_bounds = sorted(requested_bounds - selected_names)
        if missing_bounds:
            raise SystemExit(f"Unknown search bounds: {', '.join(missing_bounds)}")
        config["search_bounds"] = selected_bounds
    load_dotenv(ROOT / ".env")
    requested = (
        [item.strip() for item in args.providers.split(",") if item.strip()]
        if args.providers
        else config["providers"]
    )
    unknown = sorted(set(requested) - {"evone", "osm", "goong"})
    if unknown:
        raise SystemExit(f"Unknown providers: {', '.join(unknown)}")

    warnings: list[str] = []
    providers_run = ["existing_master"]
    candidates = existing_master_candidates()
    if not args.offline:
        collectors = {
            "evone": lambda: collect_evone(config, warnings),
            "osm": lambda: collect_osm(config, warnings),
        }
        for provider in ("evone", "osm"):
            if provider not in requested:
                continue
            try:
                candidates.extend(collectors[provider]())
                providers_run.append(provider)
            except CollectorError as exc:
                warnings.append(f"{provider} skipped: {exc}")
        if "goong" in requested:
            api_key = os.getenv("GOONG_API_KEY", "").strip()
            if not api_key:
                warnings.append("goong skipped: GOONG_API_KEY is not configured")
            else:
                try:
                    candidates.extend(collect_goong(config, api_key, warnings))
                    providers_run.append("goong")
                except CollectorError as exc:
                    warnings.append(f"goong skipped: {exc}")

    candidates = deduplicate(candidates, float(config["dedup_distance_m"]))
    preserve_reviews(candidates, args.output)
    candidates.sort(key=lambda item: (item["review_status"] != "verified", item["name"]))
    bounds_list = configured_bounds(config)
    output = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": config.get("scope"),
        "search_bounds": bounds_list,
        "coverage_claim": config.get("coverage_claim", "none"),
        "providers_requested": [] if args.offline else requested,
        "providers_run": providers_run,
        "warnings": warnings,
        "candidates": candidates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_search_area_kml(args.kml_output, bounds_list, candidates)
    print(f"Station candidates: {len(candidates)}")
    print(f"Providers run: {', '.join(providers_run)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Output: {args.output.resolve()}")
    print(f"KML: {args.kml_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

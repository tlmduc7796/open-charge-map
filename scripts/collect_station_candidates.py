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
        elif not in_bounds(location["lat"], location["lon"], config["demo_bounds"]):
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


def collect_osm(config: dict[str, Any]) -> list[dict[str, Any]]:
    bounds = config["demo_bounds"]
    bbox = f'{bounds["south"]},{bounds["west"]},{bounds["north"]},{bounds["east"]}'
    query = (
        '[out:json][timeout:45];('
        f'nwr["amenity"="charging_station"]({bbox});'
        f'nwr["fuel:electricity"="yes"]({bbox});'
        ');out center tags;'
    )
    data = request_json(
        config["overpass_url"],
        params={"data": query},
        user_agent=config["user_agent"],
        timeout=config["http_timeout_s"],
        post=True,
    )
    candidates = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        lat = element.get("lat", element.get("center", {}).get("lat"))
        lon = element.get("lon", element.get("center", {}).get("lon"))
        if lat is None or lon is None or not in_bounds(float(lat), float(lon), bounds):
            continue
        provider_id = f'{element.get("type")}/{element.get("id")}'
        name = tags.get("name") or tags.get("operator") or f"OSM charging station {provider_id}"
        capacity = tags.get("capacity")
        try:
            total_ports = int(capacity) if capacity is not None else None
        except (TypeError, ValueError):
            total_ports = None
        source_attributes = {
            key: value
            for key, value in tags.items()
            if key in {"access", "brand", "capacity", "network", "opening_hours", "operator"}
            or key.startswith("socket:")
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
            )
        )
    return candidates


def collect_goong(config: dict[str, Any], api_key: str) -> list[dict[str, Any]]:
    predictions: dict[str, dict[str, Any]] = {}
    for center in config["search_centers"]:
        location = f'{center["lat"]},{center["lon"]}'
        for term in config["search_terms"]:
            data = request_json(
                config["goong_autocomplete_url"],
                params={"api_key": api_key, "input": term, "location": location},
                user_agent=config["user_agent"],
                timeout=config["http_timeout_s"],
            )
            for prediction in data.get("predictions", []):
                place_id = prediction.get("place_id")
                if place_id:
                    predictions.setdefault(place_id, prediction)

    candidates = []
    max_details = int(config.get("goong_max_details", 30))
    for place_id, prediction in list(predictions.items())[:max_details]:
        data = request_json(
            config["goong_detail_url"],
            params={"api_key": api_key, "place_id": place_id},
            user_agent=config["user_agent"],
            timeout=config["http_timeout_s"],
        )
        result = data.get("result", data)
        location = result.get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lon = location.get("lng", location.get("lon"))
        if lat is None or lon is None or not in_bounds(float(lat), float(lon), config["demo_bounds"]):
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
    bounds: dict[str, float],
    candidates: list[dict[str, Any]],
) -> None:
    polygon = " ".join(
        [
            f'{bounds["west"]},{bounds["south"]},0',
            f'{bounds["east"]},{bounds["south"]},0',
            f'{bounds["east"]},{bounds["north"]},0',
            f'{bounds["west"]},{bounds["north"]},0',
            f'{bounds["west"]},{bounds["south"]},0',
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
            "    <Placemark>",
            "      <name>Collector search bounds</name>",
            "      <styleUrl>#search-area</styleUrl>",
            "      <Polygon><outerBoundaryIs><LinearRing>",
            f"        <coordinates>{polygon}</coordinates>",
            "      </LinearRing></outerBoundaryIs></Polygon>",
            "    </Placemark>",
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
    parser.add_argument("--offline", action="store_true", help="Use only existing stations.geojson")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = read_json(args.config)
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
            "osm": lambda: collect_osm(config),
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
                    candidates.extend(collect_goong(config, api_key))
                    providers_run.append("goong")
                except CollectorError as exc:
                    warnings.append(f"goong skipped: {exc}")

    candidates = deduplicate(candidates, float(config["dedup_distance_m"]))
    preserve_reviews(candidates, args.output)
    candidates.sort(key=lambda item: (item["review_status"] != "verified", item["name"]))
    output = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "demo_bounds": config["demo_bounds"],
        "providers_requested": [] if args.offline else requested,
        "providers_run": providers_run,
        "warnings": warnings,
        "candidates": candidates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_search_area_kml(args.kml_output, config["demo_bounds"], candidates)
    print(f"Station candidates: {len(candidates)}")
    print(f"Providers run: {', '.join(providers_run)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Output: {args.output.resolve()}")
    print(f"KML: {args.kml_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

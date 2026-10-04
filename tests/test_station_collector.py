import json
import unittest
from pathlib import Path
from unittest import mock

from scripts.collect_station_candidates import (
    CollectorError,
    collect_goong,
    deduplicate,
    goong_search_centers,
    make_candidate,
    osm_site_amenities,
    parse_evone_items,
    preserve_reviews,
    request_overpass,
)


class StationCollectorTests(unittest.TestCase):
    def test_osm_site_amenities_only_use_tags_on_the_station(self):
        claims = osm_site_amenities(
            {
                "toilets": "yes",
                "internet_access": "wlan",
                "parking": "surface",
                "shop": "convenience",
            }
        )

        self.assertEqual(
            {claim["code"] for claim in claims},
            {"restroom", "wifi", "parking", "retail"},
        )
        self.assertTrue(all(claim["status"] == "provider_reported" for claim in claims))
        self.assertEqual(osm_site_amenities({"vending": "parking_tickets"}), [])

    def test_hcm_config_uses_only_pre_2025_city_search_areas(self):
        config_path = (
            Path(__file__).resolve().parents[1]
            / "data_platform"
            / "config"
            / "hcm_station_collector.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(config["scope"]["boundary_version"], "pre-2025")
        self.assertEqual(
            {bounds["name"] for bounds in config["search_bounds"]},
            {"HCMC_SW", "HCMC_SE", "HCMC_NW", "HCMC_NE"},
        )
        excluded_names = {
            "Thủ Dầu Một",
            "Dĩ An",
            "Thuận An",
            "Bến Cát",
            "Tân Uyên",
            "Vũng Tàu",
            "Bà Rịa",
            "Phú Mỹ",
            "Hồ Tràm - Xuyên Mộc",
            "Côn Đảo",
        }
        self.assertTrue(
            excluded_names.isdisjoint(center.get("name") for center in config["search_centers"])
        )

    def test_goong_grid_covers_bounds_with_multiple_centers(self):
        config = {
            "demo_bounds": {
                "south": 10.0,
                "west": 106.0,
                "north": 10.1,
                "east": 106.1,
            },
            "search_centers": [],
            "goong_grid_spacing_km": 5,
        }

        centers = goong_search_centers(config)

        self.assertEqual(len(centers), 9)
        self.assertTrue(all(10.0 <= row["lat"] <= 10.1 for row in centers))
        self.assertTrue(all(106.0 <= row["lon"] <= 106.1 for row in centers))

    @mock.patch("scripts.collect_station_candidates.request_json")
    def test_goong_collects_all_unique_predictions_without_global_cap(self, request_json):
        predictions = [
            {"place_id": f"place-{index}", "description": f"Station {index}"}
            for index in range(3)
        ]

        def response(url, **kwargs):
            if url == "autocomplete":
                return {"predictions": predictions}
            place_id = kwargs["params"]["place_id"]
            index = int(place_id.rsplit("-", 1)[1])
            return {
                "result": {
                    "name": f"Station {index}",
                    "formatted_address": "TP.HCM",
                    "geometry": {
                        "location": {"lat": 10.75 + index * 0.001, "lng": 106.70}
                    },
                }
            }

        request_json.side_effect = response
        config = {
            "demo_bounds": {
                "south": 10.7,
                "west": 106.6,
                "north": 10.9,
                "east": 106.8,
            },
            "search_centers": [{"lat": 10.75, "lon": 106.70}],
            "search_terms": ["trạm sạc xe điện"],
            "goong_autocomplete_url": "autocomplete",
            "goong_detail_url": "detail",
            "http_timeout_s": 1,
            "user_agent": "test",
            "goong_max_details": 1,
        }

        candidates = collect_goong(config, "api-key")

        self.assertEqual(len(candidates), 3)

    @mock.patch("scripts.collect_station_candidates.time.sleep")
    @mock.patch("scripts.collect_station_candidates.request_json")
    def test_overpass_retries_with_fallback_endpoint(self, request_json, sleep):
        request_json.side_effect = [CollectorError("busy"), {"elements": []}]
        config = {
            "overpass_url": "primary",
            "overpass_fallback_urls": ["fallback"],
            "overpass_max_attempts": 3,
            "overpass_retry_base_s": 1,
            "overpass_retry_max_s": 5,
            "overpass_timeout_s": 1,
            "http_timeout_s": 1,
            "user_agent": "test",
        }

        result = request_overpass("query", config)

        self.assertEqual(result, {"elements": []})
        self.assertEqual(request_json.call_args_list[0].args[0], "primary")
        self.assertEqual(request_json.call_args_list[1].args[0], "fallback")
        sleep.assert_called_once_with(1)

    def test_parse_evone_hcm_list_item(self):
        html = """
        <ul>
          <li>EV ONE – Audi Hồ Chí Minh: 6B Tôn Đức Thắng, TP.HCM (DC 180KW &amp; 2 trụ AC 11KW)</li>
          <li>EV ONE – Hà Nội: 1 Example, Hà Nội (AC 11KW)</li>
        </ul>
        """

        records = parse_evone_items(html)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "EV ONE – Audi Hồ Chí Minh")
        self.assertEqual(records[0]["address"], "6B Tôn Đức Thắng, TP.HCM")
        self.assertEqual(records[0]["published_details"], "DC 180KW & 2 trụ AC 11KW")

    def test_deduplicate_merges_sources_into_verified_master(self):
        master = make_candidate(
            provider="existing_master",
            provider_id="ST001",
            name="EV ONE – Audi Hồ Chí Minh",
            address="6B Tôn Đức Thắng",
            lat=10.7850,
            lon=106.7035,
            operator="EV ONE",
            access="private",
            review_status="verified",
            matched_station_id="ST001",
        )
        remote = make_candidate(
            provider="evone",
            provider_id="ev-one-audi-hcm",
            name="EV ONE Audi Ho Chi Minh",
            address="6B Tôn Đức Thắng, TP.HCM",
            lat=10.78501,
            lon=106.70351,
            operator="EV ONE",
        )

        result = deduplicate([master, remote], 80)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["review_status"], "verified")
        self.assertEqual(len(result[0]["provider_refs"]), 2)

    def test_deduplicate_keeps_same_name_at_different_locations(self):
        first = make_candidate(
            provider="goong_places",
            provider_id="vinfast-q1",
            name="Trạm sạc VinFast",
            address="Quận 1, Hồ Chí Minh",
            lat=10.775,
            lon=106.700,
            operator=None,
        )
        second = make_candidate(
            provider="goong_places",
            provider_id="vinfast-q7",
            name="Trạm sạc VinFast",
            address="Quận 7, Hồ Chí Minh",
            lat=10.735,
            lon=106.705,
            operator=None,
        )

        result = deduplicate([first, second], 80)

        self.assertEqual(len(result), 2)

    def test_preserve_manual_review(self):
        candidate = make_candidate(
            provider="osm_overpass",
            provider_id="node/1",
            name="Candidate",
            address=None,
            lat=10.77,
            lon=106.70,
            operator=None,
        )
        candidate = deduplicate([candidate], 80)[0]
        previous = {
            "candidates": [
                {
                    **candidate,
                    "review_status": "rejected",
                    "review_notes": ["Not an EV charging station"],
                }
            ]
        }
        output = Path(__file__).with_name(".tmp_station_candidates.json")
        try:
            output.write_text(json.dumps(previous), encoding="utf-8")
            preserve_reviews([candidate], output)
        finally:
            output.unlink(missing_ok=True)

        self.assertEqual(candidate["review_status"], "rejected")
        self.assertEqual(candidate["review_notes"], ["Not an EV charging station"])


if __name__ == "__main__":
    unittest.main()

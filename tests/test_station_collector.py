import json
import unittest
from pathlib import Path

from scripts.collect_station_candidates import (
    deduplicate,
    make_candidate,
    parse_evone_items,
    preserve_reviews,
)


class StationCollectorTests(unittest.TestCase):
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

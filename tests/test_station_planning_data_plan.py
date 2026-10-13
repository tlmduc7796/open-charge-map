import unittest

from data_platform.station_planning.data_plan import coerce_csv_row, quantile


class DataPlanViewTests(unittest.TestCase):
    def test_no_completed_sessions_has_unknown_wait(self):
        self.assertIsNone(quantile([], 0.5))
        self.assertIsNone(quantile([], 0.9))

    def test_true_zero_wait_is_preserved(self):
        self.assertEqual(quantile([0, 0], 0.9), 0)

    def test_wait_quantile_interpolation(self):
        self.assertEqual(quantile([0, 30, 60], 0.5), 30)
        self.assertEqual(quantile([0, 30, 60], 0.9), 54)

    def test_blank_nullable_number_is_not_zero(self):
        definition = {"properties": {"value": {"type": ["number", "null"]}}}
        self.assertIsNone(coerce_csv_row({"value": ""}, definition)["value"])
        self.assertEqual(coerce_csv_row({"value": "0"}, definition)["value"], 0)

    def test_structured_poi_mix_is_json(self):
        definition = {"properties": {"poi_mix": {"type": "object"}}}
        self.assertEqual(
            coerce_csv_row({"poi_mix": '{"retail": 1.0}'}, definition)["poi_mix"], {"retail": 1.0}
        )

    def test_invalid_boolean_is_not_silently_false(self):
        definition = {"properties": {"is_synthetic": {"type": "boolean"}}}
        with self.assertRaises(ValueError):
            coerce_csv_row({"is_synthetic": "unknown"}, definition)


if __name__ == "__main__":
    unittest.main()

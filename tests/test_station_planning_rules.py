import copy
import unittest

from data_platform.station_planning.rules import (
    access_metrics,
    candidate_constraints,
    eligibility_from_constraints,
)


class AccessRuleTests(unittest.TestCase):
    def setUp(self):
        self.access = {
            "speed_kmh_by_profile": {"fast": 25, "normal": 20, "slow": 12},
            "circuity_factor": 1.3,
            "fixed_access_minutes": 2,
            "target_access_minutes": 15,
        }

    def test_zero_distance_still_has_access_overhead(self):
        self.assertEqual(access_metrics(0, self.access, "normal"), (0, 2, True))

    def test_threshold_is_inclusive_and_next_distance_fails(self):
        # 20 km/h for 13 minutes = 4,333.333 m proxy / 1.3 = 3,333.333 m geodesic.
        threshold = (15 - 2) * 20 * 1000 / 60 / 1.3
        self.assertTrue(access_metrics(threshold, self.access, "normal")[2])
        self.assertFalse(access_metrics(threshold + 0.001, self.access, "normal")[2])

    def test_slower_profile_is_never_faster(self):
        fast = access_metrics(4000, self.access, "fast")[1]
        normal = access_metrics(4000, self.access, "normal")[1]
        slow = access_metrics(4000, self.access, "slow")[1]
        self.assertLess(fast, normal)
        self.assertLess(normal, slow)

    def test_invalid_parameters_fail(self):
        for field, bad in (
            ("circuity_factor", 0.5),
            ("fixed_access_minutes", -1),
            ("target_access_minutes", 0),
        ):
            value = copy.deepcopy(self.access)
            value[field] = bad
            with self.assertRaises(ValueError):
                access_metrics(1000, value, "normal")
        with self.assertRaises(ValueError):
            access_metrics(float("nan"), self.access, "normal")
        value = copy.deepcopy(self.access)
        value["speed_kmh_by_profile"]["normal"] = 0
        with self.assertRaises(ValueError):
            access_metrics(1000, value, "normal")


class ConstraintRuleTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "candidates": {"minimum_existing_distance_m": 150},
            "constraints": {
                "package_id": "test",
                "portfolio_budget_vnd": 1000,
                "charger_option": {"charger_type": "DC", "port_count": 4, "power_kw_per_port": 80},
            },
        }
        self.candidate = {
            "candidate_id": "c1",
            "nearest_fixture_site_distance_m": 150,
            "access_feasible": None,
            "grid_capacity_kw": None,
            "permit_status": "unknown",
        }

    def evaluate(self, **overrides):
        args = {"valid_geometry": True, "inside_pilot": True, "nominal_capex": 1000}
        args.update(overrides)
        return candidate_constraints(self.candidate, self.cfg, **args)

    def test_missing_physical_evidence_keeps_conditional(self):
        rows = self.evaluate()
        self.assertEqual(sum(r["status"] == "unknown" for r in rows), 5)
        self.assertEqual(eligibility_from_constraints(rows), "conditional")

    def test_values_without_source_evidence_do_not_confirm_feasibility(self):
        self.candidate.update(
            access_feasible=False, grid_capacity_kw=0, permit_status="confirmed_rejected"
        )
        self.assertEqual(eligibility_from_constraints(self.evaluate()), "conditional")

    def test_confirmed_grid_failure_excludes(self):
        self.candidate["grid_capacity_kw"] = 100
        self.candidate["feasibility_evidence"] = {
            "grid_capacity_kw": {
                "source_ref": "test-utility-study",
                "value_status": "provided",
                "source_type": "observed",
            }
        }
        self.assertEqual(eligibility_from_constraints(self.evaluate()), "excluded")

    def test_outside_pilot_or_excess_budget_fails(self):
        self.assertEqual(
            eligibility_from_constraints(self.evaluate(inside_pilot=False)), "excluded"
        )
        self.assertEqual(
            eligibility_from_constraints(self.evaluate(nominal_capex=1001)), "excluded"
        )
        self.assertEqual(
            eligibility_from_constraints(self.evaluate(nominal_capex=1000)), "conditional"
        )

    def test_boolean_port_count_is_invalid(self):
        self.cfg["constraints"]["charger_option"]["port_count"] = True
        self.assertEqual(eligibility_from_constraints(self.evaluate()), "excluded")


if __name__ == "__main__":
    unittest.main()

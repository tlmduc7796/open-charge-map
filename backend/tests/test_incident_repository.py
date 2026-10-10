from backend.app.incident_repository import DatabaseIncidentRepository


class _Result:
    def mappings(self):
        return self

    def all(self):
        return [
            {"station_id": "ST_SAFE", "incident_type": "safety_concern"},
            {"station_id": "ST_ACCESS", "incident_type": "access_problem"},
        ]


class _Connection:
    def __init__(self):
        self.statement = None
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, parameters):
        self.statement = statement
        self.parameters = parameters
        return _Result()


class _Engine:
    def __init__(self):
        self.connection = _Connection()

    def connect(self):
        return self.connection


def test_active_ranking_impacts_are_batched_and_filter_to_triaged_safety_access():
    engine = _Engine()
    repository = DatabaseIncidentRepository(engine)

    impacts = repository.active_ranking_impacts(("ST_SAFE", "ST_ACCESS", "ST_SAFE"))

    assert impacts == (
        {"station_id": "ST_SAFE", "incident_type": "safety_concern"},
        {"station_id": "ST_ACCESS", "incident_type": "access_problem"},
    )
    assert engine.connection.parameters == {"station_ids": ("ST_ACCESS", "ST_SAFE")}
    sql = str(engine.connection.statement)
    assert "si.status='triaged'" in sql
    assert "safety_concern" in sql
    assert "access_problem" in sql


def test_active_ranking_impacts_skips_database_for_empty_candidate_set():
    repository = DatabaseIncidentRepository(None)

    assert repository.active_ranking_impacts(()) == ()

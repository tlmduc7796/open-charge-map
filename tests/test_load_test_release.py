from __future__ import annotations

import json

import pytest

from scripts.load_test_release import fetch_json, percentile


@pytest.mark.parametrize(
    ("values", "fraction", "expected"),
    [([], 0.95, 0), ([10], 0.50, 10), ([3, 1, 2, 4], 0.50, 2), ([3, 1, 2, 4], 0.95, 4)],
)
def test_percentile_uses_nearest_rank(
    values: list[float], fraction: float, expected: float
) -> None:
    assert percentile(values, fraction) == expected


def test_fetch_json_builds_authenticated_journey_post(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"journey_id":"test"}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("scripts.load_test_release.urlopen", fake_urlopen)
    status, payload, _ = fetch_json(
        "https://staging.test/api/journey/recommend",
        5,
        method="POST",
        payload={"vehicle_id": "EV_TEST"},
        headers={
            "Authorization": "Bearer secret-token",
            "Idempotency-Key": "release-load-0123456789abcdef",
        },
    )

    request = captured["request"]
    assert status == 200
    assert payload == {"journey_id": "test"}
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"vehicle_id": "EV_TEST"}
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert request.get_header("Idempotency-key") == "release-load-0123456789abcdef"
    assert request.get_header("Content-type") == "application/json"
    assert captured["timeout"] == 5


def test_journey_probe_requires_explicit_write_confirmation(
    monkeypatch, tmp_path
) -> None:
    from scripts import load_test_release

    request_file = tmp_path / "journey.json"
    request_file.write_text(
        '{"vehicle_id":"EV_TEST","initial_soc":0.5,"origin":{},"destination":{}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "load_test_release.py",
            "--requests",
            "1",
            "--concurrency",
            "1",
            "--max-p95-ms",
            "100",
            "--max-error-rate",
            "0.1",
            "--confirm-staging",
            "--journey-request-file",
            str(request_file),
        ],
    )

    with pytest.raises(SystemExit):
        load_test_release.main()


def test_journey_probe_rejects_remote_http_without_sending_token(
    monkeypatch, tmp_path, capsys
) -> None:
    from scripts import load_test_release

    request_file = tmp_path / "journey.json"
    request_file.write_text(
        '{"vehicle_id":"EV_TEST","initial_soc":0.5,"origin":{},"destination":{}}',
        encoding="utf-8",
    )
    secret = "short-lived-secret-token"
    monkeypatch.setenv("SMART_EV_STAGING_BEARER_TOKEN", secret)
    monkeypatch.setattr(
        "sys.argv",
        [
            "load_test_release.py",
            "--api-url",
            "http://staging.example.net/api",
            "--requests",
            "1",
            "--concurrency",
            "1",
            "--max-p95-ms",
            "100",
            "--max-error-rate",
            "0.1",
            "--confirm-staging",
            "--journey-request-file",
            str(request_file),
            "--confirm-journey-writes",
        ],
    )
    monkeypatch.setattr(
        "scripts.load_test_release.urlopen",
        lambda *_args, **_kwargs: pytest.fail("request must not be sent over HTTP"),
    )

    with pytest.raises(SystemExit):
        load_test_release.main()

    captured = capsys.readouterr()
    assert "HTTPS" in captured.err
    assert secret not in captured.out + captured.err

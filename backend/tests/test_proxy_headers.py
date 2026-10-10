import asyncio

from uvicorn.config import Config
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


def _resolve_client(peer_ip: str) -> tuple[str, str]:
    observed: list[tuple[str, str]] = []

    async def app(scope, _receive, _send):
        observed.append((scope["client"][0], scope["scheme"]))

    middleware = ProxyHeadersMiddleware(app, trusted_hosts="172.31.250.2")
    scope = {
        "type": "http",
        "client": (peer_ip, 45000),
        "scheme": "http",
        "headers": [
            (b"x-forwarded-for", b"198.51.100.24"),
            (b"x-forwarded-proto", b"https"),
        ],
    }
    asyncio.run(middleware(scope, lambda: None, lambda _message: None))
    return observed[0]


def test_proxy_headers_are_applied_only_from_the_compose_web_proxy_ip() -> None:
    assert _resolve_client("172.31.250.2") == ("198.51.100.24", "https")
    assert _resolve_client("172.31.250.9") == ("172.31.250.9", "http")


def test_uvicorn_loads_the_compose_forwarded_allow_ips_environment(monkeypatch) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.31.250.2")

    config = Config("backend.app.main:app", proxy_headers=True)

    assert config.forwarded_allow_ips == "172.31.250.2"

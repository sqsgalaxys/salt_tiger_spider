import httpx
import pytest

from salttiger_library.client import RobotsDeniedError, SiteClient


def test_redirect_target_gets_its_own_robots_check():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == "https://a.example/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if str(request.url) == "https://a.example/start":
            return httpx.Response(302, headers={"Location": "https://b.example/secret"})
        if str(request.url) == "https://b.example/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /secret\n")
        raise AssertionError(f"unexpected request: {request.url}")

    client = SiteClient(user_agent="test", delay_seconds=0)
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    try:
        with pytest.raises(RobotsDeniedError):
            client.get_text("https://a.example/start")
    finally:
        client.close()

    assert "https://b.example/secret" not in requested


def test_missing_robots_file_allows_access():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="ok")

    client = SiteClient(user_agent="test", delay_seconds=0)
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    try:
        assert client.get_text("https://example.test/page") == "ok"
    finally:
        client.close()

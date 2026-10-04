from __future__ import annotations

import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx


class RobotsDeniedError(RuntimeError):
    pass


class SiteClient:
    def __init__(
        self,
        *,
        user_agent: str,
        delay_seconds: float = 3.0,
        timeout_seconds: float = 30.0,
        allow_disallowed: bool = False,
    ):
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.allow_disallowed = allow_disallowed
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_request_at = 0.0

    def __enter__(self) -> "SiteClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        remaining = self.delay_seconds - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def _request(self, url: str, *, follow_redirects: bool = False) -> httpx.Response:
        self._throttle()
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.get(url, follow_redirects=follow_redirects)
                self._last_request_at = time.monotonic()
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                if response.is_redirect:
                    return response
                response.raise_for_status()
                return response
            except httpx.HTTPError as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError) and 400 <= error.response.status_code < 500:
                    raise
                if attempt < 2:
                    time.sleep(2**attempt)
        raise RuntimeError(f"request failed after retries: {url}") from last_error

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        site = f"{parsed.scheme}://{parsed.netloc}"
        robots = self._robots.get(site)
        if robots is None:
            robots_url = urljoin(site, "/robots.txt")
            robots = urllib.robotparser.RobotFileParser()
            robots.set_url(robots_url)
            try:
                response = self._request(robots_url, follow_redirects=True)
            except httpx.HTTPStatusError as error:
                if 400 <= error.response.status_code < 500:
                    robots.parse([])
                else:
                    raise
            else:
                robots.parse(response.text.splitlines())
            self._robots[site] = robots
        return robots.can_fetch(self.user_agent, url)

    def _get_following_redirects(self, url: str) -> httpx.Response:
        current = url
        for _ in range(6):
            if not self.allow_disallowed and not self._allowed(current):
                raise RobotsDeniedError(
                    f"robots.txt disallows automated access to {current}; "
                    "use an offline HTML export or explicitly pass --allow-disallowed"
                )
            response = self._request(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RuntimeError(f"redirect without Location header: {current}")
                current = urljoin(current, location)
                continue
            return response
        raise RuntimeError(f"too many redirects: {url}")

    def get_text(self, url: str) -> str:
        return self._get_following_redirects(url).text

    def download(self, url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        last_error: Exception | None = None
        try:
            for attempt in range(3):
                current = url
                try:
                    for _ in range(6):
                        if not self.allow_disallowed and not self._allowed(current):
                            raise RobotsDeniedError(f"robots.txt disallows automated access to {current}")
                        self._throttle()
                        with self._client.stream("GET", current) as response:
                            self._last_request_at = time.monotonic()
                            if response.is_redirect:
                                location = response.headers.get("location")
                                if not location:
                                    raise RuntimeError(f"redirect without Location header: {current}")
                                current = urljoin(current, location)
                                continue
                            response.raise_for_status()
                            with partial.open("wb") as handle:
                                for chunk in response.iter_bytes():
                                    handle.write(chunk)
                            partial.replace(destination)
                            return destination
                    raise RuntimeError(f"too many redirects: {url}")
                except RobotsDeniedError:
                    raise
                except (httpx.HTTPError, OSError, RuntimeError) as error:
                    last_error = error
                    partial.unlink(missing_ok=True)
                    if attempt < 2:
                        time.sleep(2**attempt)
            raise RuntimeError(f"download failed after retries: {url}") from last_error
        finally:
            partial.unlink(missing_ok=True)

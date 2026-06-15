from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, urlencode

import requests
from requests.exceptions import RequestException, Timeout

LIVE_TYPE = "live"
VOD_TYPE = "vod"
SERIES_TYPE = "series"

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 60
RETRIES = 3
RETRY_SLEEP = 2

BackupMatchMode = Literal["mirror", "name", "merge"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/44.0.2403.89 Safari/537.36"
    )
}


def normalize_stream_match_mode(value: str) -> BackupMatchMode:
    """Validate and normalize a backup stream-match mode for type checkers."""
    clean_value = value.strip().lower()

    if clean_value == "mirror":
        return "mirror"

    if clean_value == "name":
        return "name"

    if clean_value == "merge":
        return "merge"

    raise ValueError(
        f"stream_match must be 'mirror', 'name', or 'merge', got {value!r}"
    )


def normalize_server(server: str) -> str:
    """Return a clean Xtream server URL with no trailing slash."""
    clean_server = server.strip().rstrip("/")

    if not clean_server:
        raise ValueError("Provider server cannot be empty")

    if not clean_server.startswith(("http://", "https://")):
        clean_server = f"http://{clean_server}"

    return clean_server


@dataclass(frozen=True)
class Provider:
    """Xtream provider connection details.

    stream_match controls how this provider is used as a backup:
      - mirror: reuse primary stream IDs on this server/domain.
      - name: fetch this provider's own categories/streams and match by channel name.
      - merge: fetch this provider with the same filters and append its channels.

    The primary provider can leave stream_match as mirror; it only matters for backups.
    """

    server: str
    username: str
    password: str
    name: str = "Primary"
    stream_match: BackupMatchMode = "mirror"

    def __post_init__(self) -> None:
        object.__setattr__(self, "server", normalize_server(self.server))
        object.__setattr__(self, "username", self.username.strip())
        object.__setattr__(self, "password", self.password.strip())
        object.__setattr__(self, "name", self.name.strip() or "Provider")
        object.__setattr__(
            self, "stream_match", normalize_stream_match_mode(str(self.stream_match))
        )

        if not self.username:
            raise ValueError(f"{self.name}: username cannot be empty")

        if not self.password:
            raise ValueError(f"{self.name}: password cannot be empty")


class XtreamClient:
    def __init__(self, provider: Provider):
        self.provider = provider
        self.session = requests.Session()
        self._categories_cache: dict[str, list[dict[str, Any]]] = {}

    def api_get(
        self,
        action: str,
        extra_params: dict[str, str] | None = None,
        default: Any = None,
        label: str | None = None,
    ) -> Any:
        if default is None:
            default = []

        url = f"{self.provider.server}/player_api.php"
        params: dict[str, str] = {
            "username": self.provider.username,
            "password": self.provider.password,
            "action": action,
        }

        if extra_params:
            params.update(extra_params)

        name = label or action

        for attempt in range(1, RETRIES + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=HEADERS,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
                response.raise_for_status()
                return response.json()

            except Timeout:
                print(
                    f"[TIMEOUT] {self.provider.name}: {name} attempt {attempt}/{RETRIES}"
                )

            except ValueError as exc:
                print(f"[JSON ERROR] {self.provider.name}: {name}: {exc}")
                return default

            except RequestException as exc:
                print(
                    f"[REQUEST ERROR] {self.provider.name}: "
                    f"{name} attempt {attempt}/{RETRIES}: {exc}"
                )

            if attempt < RETRIES:
                time.sleep(RETRY_SLEEP)

        print(f"[SKIPPED] {self.provider.name}: {name} failed after {RETRIES} attempts")
        return default

    def categories(self, stream_type: str) -> list[dict[str, Any]]:
        if stream_type in self._categories_cache:
            return self._categories_cache[stream_type]

        action_map = {
            LIVE_TYPE: "get_live_categories",
            VOD_TYPE: "get_vod_categories",
            SERIES_TYPE: "get_series_categories",
        }

        action = action_map.get(stream_type)
        if not action:
            return []

        data = self.api_get(action, default=[], label=f"{stream_type} categories")
        categories = data if isinstance(data, list) else []
        self._categories_cache[stream_type] = categories
        return categories

    def streams_by_category(
        self, stream_type: str, category_id: str
    ) -> list[dict[str, Any]]:
        action_map = {
            LIVE_TYPE: "get_live_streams",
            VOD_TYPE: "get_vod_streams",
            SERIES_TYPE: "get_series",
        }

        action = action_map.get(stream_type)
        if not action:
            return []

        data = self.api_get(
            action,
            extra_params={"category_id": str(category_id)},
            default=[],
            label=f"{stream_type} category {category_id}",
        )
        return data if isinstance(data, list) else []

    def series_info_by_id(self, series_id: str) -> dict[str, Any] | None:
        data = self.api_get(
            "get_series_info",
            extra_params={"series_id": str(series_id)},
            default=None,
            label=f"series info {series_id}",
        )
        return data if isinstance(data, dict) else None

    def build_stream_url(
        self,
        stream_id: str,
        stream_type: str,
        container_extension: str = "ts",
    ) -> str | None:
        path_map = {
            LIVE_TYPE: "live",
            VOD_TYPE: "movie",
            SERIES_TYPE: "series",
        }

        path = path_map.get(stream_type)
        if not path:
            return None

        # Encode path parts so special characters in credentials do not break URLs.
        username = quote(self.provider.username, safe="")
        password = quote(self.provider.password, safe="")
        stream_id = quote(str(stream_id), safe="")
        container_extension = container_extension.lstrip(".")

        return (
            f"{self.provider.server}/{path}/"
            f"{username}/{password}/"
            f"{stream_id}.{container_extension}"
        )

    def build_epg_url(self) -> str:
        """Return this provider's XMLTV/EPG URL."""
        params = urlencode(
            {
                "username": self.provider.username,
                "password": self.provider.password,
            }
        )
        return f"{self.provider.server}/xmltv.php?{params}"

from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

from urls import (
    LIVE_TYPE,
    SERIES_TYPE,
    VOD_TYPE,
    BackupMatchMode,
    Provider,
    XtreamClient,
)

SEPARATOR = ";\n"
DEFAULT_OUTPUT = "output"
BackupMatchArg = Literal["auto", "mirror", "name", "merge"]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupSpec:
    client: XtreamClient
    explicit_credentials: bool


@dataclass
class BackupCandidate:
    stream: dict[str, Any]
    category_name: str
    key: str
    tokens: frozenset[str]
    numbers: frozenset[str]


@dataclass
class BackupIndex:
    client: XtreamClient
    streams_by_key: dict[str, list[BackupCandidate]]
    candidates: list[BackupCandidate]
    matched: int = 0
    fuzzy_matched: int = 0
    missed: int = 0


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "_", name or "Unknown")
    return name.strip() or "Unknown"


def is_valid_channel(name: str) -> bool:
    if not name:
        return False

    name = name.strip()

    if name.count("#") > 3:
        return False

    if len(name) < 3:
        return False

    return True


def prepare_output_dir(path: Path, keep_prev: bool) -> None:
    if keep_prev:
        path.mkdir(parents=True, exist_ok=True)
        return

    previous = path.with_name(f"prev_{path.name}")

    if previous.exists():
        shutil.rmtree(previous)

    if path.exists():
        path.rename(previous)

    path.mkdir(parents=True, exist_ok=True)


def write_txt(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write(SEPARATOR.join(lines))
        file.write(SEPARATOR)


def m3u_escape(value: str | None) -> str:
    return (value or "").replace('"', "'").strip()


def write_m3u(
    path: Path,
    entries: list[dict[str, Any]],
    epg_urls: list[str] | None = None,
    epg_header_mode: Literal["single", "compat"] = "compat",
) -> None:
    """Write an M3U playlist.

    The M3U header points IPTV players to XMLTV/EPG when epg_urls is provided.
    The playlist still keeps the actual guide separate, which is how most IPTV
    apps expect M3U + XMLTV to work.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    epg_urls = [url.strip() for url in (epg_urls or []) if url and url.strip()]
    epg_value = m3u_escape(",".join(epg_urls))

    with path.open("w", encoding="utf-8") as file:
        if epg_value:
            if epg_header_mode == "single":
                file.write(f'#EXTM3U x-tvg-url="{epg_value}"\n')
            else:
                # x-tvg-url is the most common attribute. url-tvg/tvg-url are also
                # included for compatibility with players that prefer those names.
                file.write(
                    f'#EXTM3U x-tvg-url="{epg_value}" '
                    f'url-tvg="{epg_value}" '
                    f'tvg-url="{epg_value}"\n'
                )
        else:
            file.write("#EXTM3U\n")

        for entry in entries:
            attrs = []

            if entry.get("tvg_id"):
                attrs.append(f'tvg-id="{m3u_escape(str(entry["tvg_id"]))}"')

            if entry.get("name"):
                attrs.append(f'tvg-name="{m3u_escape(str(entry["name"]))}"')

            if entry.get("logo"):
                attrs.append(f'tvg-logo="{m3u_escape(str(entry["logo"]))}"')

            if entry.get("group"):
                attrs.append(f'group-title="{m3u_escape(str(entry["group"]))}"')

            attrs_text = " " + " ".join(attrs) if attrs else ""
            display_name = m3u_escape(str(entry["display_name"]))

            file.write(f"#EXTINF:-1{attrs_text},{display_name}\n")
            file.write(f"{entry['url']}\n")


def parse_csv_env(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def prompt_backup_servers() -> list[str]:
    print("\nEnter backup server URLs. Press Enter with no value when finished.")
    print("Examples:")
    print("  http://backup-server:8080")
    print("  http://backup-server:8080|username|password|Backup Name")
    print("  http://backup-server:8080|username|password|Backup Name|merge")

    servers = []
    index = 1

    while True:
        value = input(f"Backup server {index}: ").strip()
        if not value:
            break
        servers.append(value)
        index += 1

    return servers


def require_text(value: str | None, name: str) -> str:
    """Validate env/CLI values and return a real str, not str | None."""
    if value is None or not value.strip():
        raise ConfigError(
            f"Missing {name}. Add it to .env or pass --{name.lower()} on the command line."
        )
    return value.strip()


def load_credentials(args: argparse.Namespace) -> tuple[str, str, str]:
    server = require_text(args.server or os.getenv("SERVER"), "SERVER")
    username = require_text(args.username or os.getenv("USERNAME"), "USERNAME")
    password = require_text(args.password or os.getenv("PASSWORD"), "PASSWORD")
    return server, username, password


def provider_from_string(
    raw: str,
    fallback_user: str,
    fallback_pass: str,
    index: int,
    backup_match: BackupMatchArg = "auto",
) -> BackupSpec:
    """
    Supported formats:
      http://server:port
      http://server:port|username|password
      http://server:port|username|password|Display Name
      http://server:port|username|password|Display Name|mirror
      http://server:port|username|password|Display Name|name
      http://server:port|username|password|Display Name|merge

    Important behavior:
      - server only = mirror backup by default, reuse primary stream IDs
      - server|username|password = separate provider by default, match by name
      - the optional 5th field overrides --backup-match for this one provider
      - merge mode fetches backup provider channels using the same filters and appends them
    """
    parts = [part.strip() for part in raw.split("|")]

    if len(parts) not in {1, 3, 4, 5}:
        raise ConfigError(
            "Invalid --backup-server format. Use one of:\n"
            "  http://server:port\n"
            "  http://server:port|username|password\n"
            "  http://server:port|username|password|Display Name\n"
            "  http://server:port|username|password|Display Name|mirror|name|merge"
        )

    server = require_text(parts[0] if parts else None, f"BACKUP_SERVER_{index}")
    explicit_credentials = len(parts) >= 3

    if explicit_credentials:
        username = require_text(parts[1], f"BACKUP_USERNAME_{index}")
        password = require_text(parts[2], f"BACKUP_PASSWORD_{index}")
    else:
        username = fallback_user
        password = fallback_pass

    name = parts[3] if len(parts) >= 4 and parts[3] else f"Backup {index}"
    provider_override = parts[4].casefold() if len(parts) == 5 and parts[4] else ""

    mode_source: BackupMatchArg
    if provider_override:
        mode_source = normalize_backup_match_arg(provider_override)
        if mode_source == "auto":
            raise ConfigError(
                "Per-backup mode cannot be auto. Use mirror, name, or merge as the 5th field."
            )
    else:
        mode_source = backup_match

    stream_match: BackupMatchMode
    if mode_source == "auto":
        stream_match = "name" if explicit_credentials else "mirror"
    elif mode_source == "mirror":
        stream_match = "mirror"
    elif mode_source == "name":
        stream_match = "name"
    elif mode_source == "merge":
        stream_match = "merge"
    else:
        raise ConfigError("--backup-match must be auto, mirror, name, or merge")

    return BackupSpec(
        client=XtreamClient(
            Provider(
                server=server,
                username=username,
                password=password,
                name=name,
                stream_match=stream_match,
            )
        ),
        explicit_credentials=explicit_credentials,
    )


def normalize_backup_match_arg(value: str) -> BackupMatchArg:
    """Validate argparse's string value and return a literal-friendly mode."""
    if value == "auto":
        return "auto"

    if value == "mirror":
        return "mirror"

    if value == "name":
        return "name"

    if value == "merge":
        return "merge"

    raise ConfigError("--backup-match must be auto, mirror, name, or merge")


REGEX_META_CHARS = set(r".\^$*+?{}[]|()")


def looks_like_regex(pattern: str) -> bool:
    return any(char in REGEX_META_CHARS for char in pattern)


def token_pattern(pattern: str) -> str:
    """
    Convert a friendly plain-text filter into a safer regex.

    Example:
      sd  ->  (?<![A-Za-z0-9])sd(?![A-Za-z0-9])

    This lets users type --exclude-channel sd without accidentally matching
    letters inside a bigger word.
    """
    escaped = re.escape(pattern.strip())
    return rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"


def compile_patterns(
    patterns: Iterable[str] | None,
    *,
    smart_plain_words: bool = False,
) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []

    for raw_pattern in patterns or []:
        pattern = raw_pattern.strip()
        if not pattern:
            continue

        if smart_plain_words and not looks_like_regex(pattern):
            pattern = token_pattern(pattern)

        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            compiled.append(re.compile(re.escape(pattern), re.IGNORECASE))

    return compiled


def matches_any(value: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(value or "") for pattern in patterns)


def filter_categories(
    categories: list[dict[str, Any]],
    include: list[str] | None,
    exclude: list[str] | None,
) -> list[dict[str, Any]]:
    include_patterns = compile_patterns(include)
    exclude_patterns = compile_patterns(exclude, smart_plain_words=True)

    filtered = []

    for category in categories:
        name = str(category.get("category_name", ""))

        if include_patterns and not matches_any(name, include_patterns):
            continue

        if exclude_patterns and matches_any(name, exclude_patterns):
            continue

        filtered.append(category)

    return filtered


def channel_is_allowed(
    channel_name: str,
    include_patterns: list[re.Pattern[str]],
    exclude_patterns: list[re.Pattern[str]],
) -> bool:
    if include_patterns and not matches_any(channel_name, include_patterns):
        return False

    if exclude_patterns and matches_any(channel_name, exclude_patterns):
        return False

    return True


QUALITY_TOKENS = {
    "sd",
    "hd",
    "fhd",
    "uhd",
    "4k",
    "8k",
    "raw",
    "hevc",
    "h265",
    "h264",
    "vip",
    "dolby",
    "audio",
    "50fps",
    "60fps",
    "720p",
    "1080p",
    "2160p",
    "3840p",
}

CHANNEL_PREFIX_TOKENS = {
    "uk",
    "gb",
    "us",
    "usa",
    "ie",
    "irl",
    "ireland",
    "united",
    "kingdom",
}

CHANNEL_NOISE_TOKENS = {
    "channel",
    "channels",
    "backup",
    "source",
}

CHANNEL_TOKEN_ALIASES = {
    "sports": "sport",
    "sporting": "sport",
    "futbol": "football",
    "fútbol": "football",
    "soccer": "football",
    "plus": "plus",
    "+": "plus",
}


def normalize_channel_token(token: str) -> str:
    token = CHANNEL_TOKEN_ALIASES.get(token, token)

    # Keep channel numbers intact, but collapse simple plural words. This helps
    # names like "Sky Sports Main Event" match "SKY SPORT MAIN EVENT FHD".
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        token = token[:-1]

    return CHANNEL_TOKEN_ALIASES.get(token, token)


def normalize_channel_key(name: str) -> str:
    """Return a stable key for matching the same channel across providers.

    The key intentionally removes provider/country/quality noise such as UK,
    FHD, 4K, RAW, HEVC, VIP, and punctuation, while keeping channel numbers.
    It is a little forgiving because different providers name the same channel
    differently.
    """
    text = unicodedata.normalize("NFKD", name or "")
    text = text.casefold()
    text = text.replace("&", " and ").replace("+", " plus ")
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)

    tokens: list[str] = []
    for raw_token in text.split():
        token = normalize_channel_token(raw_token)
        if token in QUALITY_TOKENS:
            continue
        if token in CHANNEL_PREFIX_TOKENS:
            continue
        if token in CHANNEL_NOISE_TOKENS:
            continue
        tokens.append(token)

    return " ".join(tokens)


def channel_key_tokens(key: str) -> frozenset[str]:
    return frozenset(token for token in key.split() if token)


def channel_key_numbers(key: str) -> frozenset[str]:
    return frozenset(re.findall(r"\d+", key))


def channel_name_match_score(primary_key: str, candidate: BackupCandidate) -> float:
    """Score how likely a backup candidate is the same channel.

    Exact normalized matches still win, but this also catches common provider
    naming differences. Number mismatches are blocked so "TNT Sport 1" does not
    match "TNT Sport 2".
    """
    if not primary_key or not candidate.key:
        return 0.0

    if primary_key == candidate.key:
        return 1.0

    primary_numbers = channel_key_numbers(primary_key)
    if primary_numbers and candidate.numbers and primary_numbers != candidate.numbers:
        return 0.0

    primary_tokens = channel_key_tokens(primary_key)
    if not primary_tokens or not candidate.tokens:
        return 0.0

    shared = primary_tokens & candidate.tokens
    if not shared:
        return 0.0

    token_ratio = (2 * len(shared)) / (len(primary_tokens) + len(candidate.tokens))
    containment = len(shared) / min(len(primary_tokens), len(candidate.tokens))
    sequence_ratio = difflib.SequenceMatcher(None, primary_key, candidate.key).ratio()

    # If the shorter name is fully contained in the longer one and it has enough
    # useful words, treat it as a strong match. Example: "espn plus" vs
    # "usa espn plus event 1" after normalization.
    contained_score = 0.0
    if containment == 1.0 and min(len(primary_tokens), len(candidate.tokens)) >= 2:
        contained_score = 0.92

    return max(sequence_ratio, token_ratio, containment * 0.90, contained_score)


def find_best_backup_match(
    primary_key: str,
    backup_index: BackupIndex,
    threshold: float,
) -> tuple[BackupCandidate | None, bool]:
    exact_matches = backup_index.streams_by_key.get(primary_key)
    if exact_matches:
        return exact_matches[0], False

    best_candidate: BackupCandidate | None = None
    best_score = 0.0

    for candidate in backup_index.candidates:
        score = channel_name_match_score(primary_key, candidate)
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate and best_score >= threshold:
        return best_candidate, True

    return None, False


def category_with_provider_suffix(category_name: str, provider_name: str) -> str:
    return f"{category_name} | {provider_name}"


def get_stream_id(stream: dict[str, Any], stream_type: str) -> str | None:
    """Return the best stream ID field for the Xtream item."""
    if stream_type == SERIES_TYPE:
        value = stream.get("series_id") or stream.get("id") or stream.get("stream_id")
    else:
        value = stream.get("stream_id") or stream.get("id") or stream.get("series_id")

    return str(value) if value is not None else None


def print_categories(
    client: XtreamClient,
    stream_types: list[str],
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> None:
    for stream_type in stream_types:
        print(f"\n{stream_type.upper()} categories")
        print("-" * 60)

        categories = filter_categories(client.categories(stream_type), include, exclude)

        if not categories:
            print("No matching categories found")
            continue

        for category in categories:
            category_id = category.get("category_id", "?")
            category_name = category.get("category_name", "Unknown")
            print(f"{str(category_id):>6}  {category_name}")


def stream_entry(
    client: XtreamClient,
    stream: dict[str, Any],
    category_name: str,
    stream_type: str,
    container: str,
    provider_label: str | None = None,
    suffix_backup_name: bool = True,
) -> dict[str, Any] | None:
    stream_id = get_stream_id(stream, stream_type)
    name = str(stream.get("name") or "").strip()

    if not stream_id or not is_valid_channel(name):
        return None

    url = client.build_stream_url(str(stream_id), stream_type, container)
    if not url:
        return None

    display_name = name
    if provider_label and suffix_backup_name:
        display_name = f"{name} [{provider_label}]"

    return {
        "name": name,
        "display_name": display_name,
        "url": url,
        "group": category_name,
        "logo": stream.get("stream_icon") or stream.get("cover") or "",
        "tvg_id": stream.get("epg_channel_id") or stream.get("tvg_id") or "",
    }


def dedupe_entries(entries: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "none":
        return entries

    seen = set()
    result = []

    for entry in entries:
        if mode == "name":
            key = str(entry["name"]).casefold()
        elif mode == "url":
            key = str(entry["url"])
        else:
            key = (str(entry["name"]).casefold(), str(entry["url"]))

        if key in seen:
            continue

        seen.add(key)
        result.append(entry)

    return result


def mask_sensitive_url(url: str) -> str:
    """Mask username/password query params when printing URLs to the terminal."""
    parts = urlsplit(url)
    query_pairs = []

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in {"username", "password"} and value:
            query_pairs.append((key, value[:2] + "***"))
        else:
            query_pairs.append((key, value))

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query_pairs), parts.fragment)
    )


def build_epg_urls(
    args: argparse.Namespace,
    primary_client: XtreamClient,
    backup_clients: list[XtreamClient],
) -> list[str]:
    """Build XMLTV URLs that will be written into the M3U header."""
    if args.no_epg:
        return []

    epg_urls: list[str] = []

    if args.auto_epg:
        epg_urls.append(primary_client.build_epg_url())

        if args.backup_epg:
            epg_urls.extend(client.build_epg_url() for client in backup_clients)

    epg_urls.extend(args.epg_url or [])

    deduped: list[str] = []
    seen: set[str] = set()

    for url in epg_urls:
        clean_url = str(url).strip()
        if not clean_url or clean_url in seen:
            continue

        seen.add(clean_url)
        deduped.append(clean_url)

    return deduped


def print_epg_urls(epg_urls: list[str]) -> None:
    if not epg_urls:
        print("EPG: disabled / no XMLTV URL added")
        return

    print("EPG XMLTV URL added to M3U:")
    for url in epg_urls:
        print(f"  {mask_sensitive_url(url)}")


def validate_backup_clients(backup_specs: list[BackupSpec]) -> None:
    """Lightly validate backups that have their own username/password.

    Mirror backups that reuse the primary credentials are not validated here because
    they may be simple alternate domains for the same provider. Backups with
    explicit credentials are likely separate providers, so we fetch live categories
    once to confirm the account is reachable before export. XtreamClient caches
    categories, so this does not add another request later.
    """
    explicit_specs = [spec for spec in backup_specs if spec.explicit_credentials]
    if not explicit_specs:
        return

    print("Validating explicit-credential backup providers:")
    for spec in explicit_specs:
        provider = spec.client.provider
        categories = spec.client.categories(LIVE_TYPE)
        if categories:
            print(f"  {provider.name}: OK ({len(categories)} live categories)")
        else:
            print(
                f"  {provider.name}: warning - no live categories returned. "
                "Check credentials/server if this backup adds nothing."
            )


def build_backup_indexes(
    args: argparse.Namespace,
    backup_clients: list[XtreamClient],
    include_channel_patterns: list[re.Pattern[str]],
    exclude_channel_patterns: list[re.Pattern[str]],
) -> dict[str, BackupIndex]:
    """Build channel-name indexes for non-mirror backup providers.

    For backups with their own username/password, the stream IDs are usually
    different from the primary provider. This index lets us use the backup's
    real stream_id by matching channel names.
    """
    indexes: dict[str, BackupIndex] = {}

    for backup_client in backup_clients:
        if backup_client.provider.stream_match != "name":
            continue

        print(
            f"Building backup name index: {backup_client.provider.name} "
            f"({backup_client.provider.server})"
        )

        all_categories = backup_client.categories(LIVE_TYPE)

        if args.backup_search_all:
            categories = all_categories
            if not include_channel_patterns:
                print(
                    f"  Warning: --backup-search-all is active for {backup_client.provider.name} "
                    "without --channel. Category filters are bypassed for this backup."
                )
        else:
            categories = filter_categories(
                all_categories, args.category, args.exclude_category
            )

            if not categories:
                print(
                    f"  No matching backup categories found for {backup_client.provider.name}. "
                    "Use --backup-search-all if this provider uses different category names."
                )

        streams_by_key: dict[str, list[BackupCandidate]] = {}
        candidates: list[BackupCandidate] = []

        for category in categories:
            category_id_raw = category.get("category_id")
            if category_id_raw is None:
                continue

            category_id = str(category_id_raw)
            category_name = str(category.get("category_name", "Unknown"))
            streams = backup_client.streams_by_category(LIVE_TYPE, category_id)

            for stream in streams:
                stream_name = str(stream.get("name") or "").strip()

                if not channel_is_allowed(
                    stream_name, include_channel_patterns, exclude_channel_patterns
                ):
                    continue

                key = normalize_channel_key(stream_name)
                if not key:
                    continue

                candidate = BackupCandidate(
                    stream=stream,
                    category_name=category_name,
                    key=key,
                    tokens=channel_key_tokens(key),
                    numbers=channel_key_numbers(key),
                )
                streams_by_key.setdefault(key, []).append(candidate)
                candidates.append(candidate)

        indexes[backup_client.provider.name] = BackupIndex(
            client=backup_client,
            streams_by_key=streams_by_key,
            candidates=candidates,
        )

        print(
            f"  Indexed {sum(len(v) for v in streams_by_key.values())} streams "
            f"under {len(streams_by_key)} unique names"
        )

    return indexes


def collect_merge_backup_entries(
    args: argparse.Namespace,
    backup_clients: list[XtreamClient],
    include_channel_patterns: list[re.Pattern[str]],
    exclude_channel_patterns: list[re.Pattern[str]],
) -> list[dict[str, Any]]:
    """Fetch backup providers as extra providers and append their own channels.

    This is different from mirror mode and name-match mode:
      - mirror: reuse the primary provider stream IDs on another domain
      - name: add backup alternatives only when the backup has the same channel name
      - merge: fetch the backup provider with the same filters and add all matches

    Merge mode is useful when a backup is really another subscription/provider and
    you want its channels added to the playlist instead of mapped one-to-one.
    """
    merged_entries: list[dict[str, Any]] = []

    for backup_client in backup_clients:
        if backup_client.provider.stream_match != "merge":
            continue

        print(
            f"Merging backup provider channels: {backup_client.provider.name} "
            f"({backup_client.provider.server})"
        )

        all_categories = backup_client.categories(LIVE_TYPE)

        if args.backup_search_all:
            categories = all_categories
            if not include_channel_patterns:
                print(
                    f"  Warning: --backup-search-all is active for {backup_client.provider.name} "
                    "without --channel. Category filters are bypassed for this backup."
                )
        else:
            categories = filter_categories(
                all_categories, args.category, args.exclude_category
            )

        if not categories:
            print(
                f"  No matching merge categories found for {backup_client.provider.name}. "
                "Use --backup-search-all to include all backup categories."
            )
            continue

        provider_count = 0

        for category in categories:
            category_id_raw = category.get("category_id")
            if category_id_raw is None:
                continue

            category_id = str(category_id_raw)
            category_name = str(category.get("category_name", "Unknown"))
            group_name = category_with_provider_suffix(
                category_name, backup_client.provider.name
            )

            streams = backup_client.streams_by_category(LIVE_TYPE, category_id)

            for stream in streams:
                stream_name = str(stream.get("name") or "").strip()
                if not channel_is_allowed(
                    stream_name, include_channel_patterns, exclude_channel_patterns
                ):
                    continue

                entry = stream_entry(
                    backup_client,
                    stream,
                    group_name,
                    LIVE_TYPE,
                    args.container,
                    provider_label=backup_client.provider.name,
                    suffix_backup_name=args.backup_mode == "suffix",
                )

                if entry:
                    merged_entries.append(entry)
                    provider_count += 1

        print(
            f"  Added {provider_count} merged channels from "
            f"{backup_client.provider.name}"
        )

    return merged_entries


def export_live(
    args: argparse.Namespace,
    primary_client: XtreamClient,
    backup_clients: list[XtreamClient],
) -> None:
    output_dir = Path(args.output)

    if args.txt:
        prepare_output_dir(output_dir / "txt", args.keep_prev)
    if args.m3u:
        prepare_output_dir(output_dir / "m3u", args.keep_prev)

    categories = primary_client.categories(LIVE_TYPE)
    categories = filter_categories(categories, args.category, args.exclude_category)

    if not categories:
        print("No matching live categories found")
        return

    include_channel_patterns = compile_patterns(args.channel)
    exclude_channel_patterns = compile_patterns(
        args.exclude_channel, smart_plain_words=True
    )
    backup_indexes: dict[str, BackupIndex] = {}
    if args.include_backups:
        backup_indexes = build_backup_indexes(
            args, backup_clients, include_channel_patterns, exclude_channel_patterns
        )

    epg_urls = build_epg_urls(args, primary_client, backup_clients)

    full_entries = []
    total = 0

    for category in categories:
        category_id_raw = category.get("category_id")
        if category_id_raw is None:
            continue

        category_id = str(category_id_raw)
        category_name = str(category.get("category_name", "Unknown"))
        safe_category = safe_filename(category_name)

        print(f"Fetching live category: {category_name}")
        streams = primary_client.streams_by_category(LIVE_TYPE, category_id)

        if not streams:
            continue

        category_entries = []

        for stream in streams:
            stream_name = str(stream.get("name") or "").strip()
            if not channel_is_allowed(
                stream_name, include_channel_patterns, exclude_channel_patterns
            ):
                continue

            primary_entry = stream_entry(
                primary_client,
                stream,
                category_name,
                LIVE_TYPE,
                args.container,
            )

            if primary_entry:
                category_entries.append(primary_entry)

            if args.include_backups:
                primary_key = normalize_channel_key(stream_name)

                for backup_client in backup_clients:
                    if backup_client.provider.stream_match == "mirror":
                        backup_entry = stream_entry(
                            backup_client,
                            stream,
                            category_name,
                            LIVE_TYPE,
                            args.container,
                            provider_label=backup_client.provider.name,
                            suffix_backup_name=args.backup_mode == "suffix",
                        )
                        if backup_entry:
                            category_entries.append(backup_entry)
                        continue

                    backup_index = backup_indexes.get(backup_client.provider.name)
                    if not backup_index:
                        continue

                    match, fuzzy = find_best_backup_match(
                        primary_key,
                        backup_index,
                        args.backup_name_threshold,
                    )
                    if not match:
                        backup_index.missed += 1
                        continue

                    backup_entry = stream_entry(
                        backup_client,
                        match.stream,
                        category_name or match.category_name,
                        LIVE_TYPE,
                        args.container,
                        provider_label=backup_client.provider.name,
                        suffix_backup_name=args.backup_mode == "suffix",
                    )
                    if backup_entry:
                        category_entries.append(backup_entry)
                        backup_index.matched += 1
                        if fuzzy:
                            backup_index.fuzzy_matched += 1

        category_entries = dedupe_entries(category_entries, args.dedupe)
        full_entries.extend(category_entries)

        if not args.full and category_entries:
            if args.txt:
                txt_lines = [
                    f"{entry['display_name']}, {entry['url']}"
                    for entry in category_entries
                ]
                write_txt(output_dir / "txt" / f"{safe_category}.txt", txt_lines)

            if args.m3u:
                write_m3u(
                    output_dir / "m3u" / f"{safe_category}.m3u",
                    category_entries,
                    epg_urls,
                    args.epg_header_mode,
                )

            print(f"Wrote {len(category_entries):5d} → {category_name}")
            total += len(category_entries)

    if args.include_backups:
        merge_entries = collect_merge_backup_entries(
            args, backup_clients, include_channel_patterns, exclude_channel_patterns
        )
        merge_entries = dedupe_entries(merge_entries, args.dedupe)

        if merge_entries:
            full_entries.extend(merge_entries)

            if not args.full:
                if args.txt:
                    txt_lines = [
                        f"{entry['display_name']}, {entry['url']}"
                        for entry in merge_entries
                    ]
                    write_txt(output_dir / "txt" / "backup_merged.txt", txt_lines)

                if args.m3u:
                    write_m3u(
                        output_dir / "m3u" / "backup_merged.m3u",
                        merge_entries,
                        epg_urls,
                        args.epg_header_mode,
                    )

    full_entries = dedupe_entries(full_entries, args.dedupe)

    if args.full and full_entries:
        if args.txt:
            txt_lines = [
                f"{entry['display_name']}, {entry['url']}" for entry in full_entries
            ]
            write_txt(output_dir / "all_live.txt", txt_lines)

        if args.m3u:
            m3u_path = output_dir / "all_live.m3u"
            write_m3u(m3u_path, full_entries, epg_urls, args.epg_header_mode)
            print(f"Wrote M3U file: {m3u_path}")
            print_epg_urls(epg_urls)

        total = len(full_entries)
        print(f"Wrote full live playlist → {total} channels")

    for index in backup_indexes.values():
        print(
            f"Backup name-match summary for {index.client.provider.name}: "
            f"matched={index.matched}, fuzzy={index.fuzzy_matched}, missed={index.missed}"
        )

    print(f"\nTotal exported live channels: {total}")


def export_vod_or_series(
    args: argparse.Namespace, primary_client: XtreamClient, stream_type: str
) -> None:
    output_dir = Path(args.output)
    media_dir = output_dir / stream_type
    prepare_output_dir(media_dir, args.keep_prev)

    categories = primary_client.categories(stream_type)
    categories = filter_categories(categories, args.category, args.exclude_category)

    if not categories:
        print(f"No matching {stream_type} categories found")
        return

    container = "mkv"
    include_channel_patterns = compile_patterns(args.channel)
    exclude_channel_patterns = compile_patterns(
        args.exclude_channel, smart_plain_words=True
    )

    for category in categories:
        category_id_raw = category.get("category_id")
        if category_id_raw is None:
            continue

        category_id = str(category_id_raw)
        category_name = str(category.get("category_name", "Unknown"))
        safe_category = safe_filename(category_name)

        print(f"Fetching {stream_type} category: {category_name}")
        streams = primary_client.streams_by_category(stream_type, category_id)

        if not streams:
            continue

        entries = []
        for stream in streams:
            stream_name = str(stream.get("name") or "").strip()
            if not channel_is_allowed(
                stream_name, include_channel_patterns, exclude_channel_patterns
            ):
                continue

            entry = stream_entry(
                primary_client,
                stream,
                category_name,
                stream_type,
                container,
            )
            if entry:
                entries.append(entry)

        entries = dedupe_entries(entries, args.dedupe)

        if not entries:
            continue

        if args.txt:
            txt_lines = [
                f"{entry['display_name']}, {entry['url']}" for entry in entries
            ]
            write_txt(media_dir / safe_category / f"{safe_category}.txt", txt_lines)

        if args.m3u:
            write_m3u(media_dir / safe_category / f"{safe_category}.m3u", entries)

        print(f"Wrote {len(entries):5d} → {category_name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Advanced Xtream Codes playlist exporter for TXT and M3U output.",
        epilog="""
Examples:
  python main.py --help
  python main.py --list-categories --live
  python main.py --m3u --full --category sport
  python main.py --m3u --full --category "sport|football|f1|boxing"
  python main.py --m3u --full --category sport --exclude-category sd --exclude-channel sd
  python main.py --m3u --full --category sport --channel "sky sports|tnt|dazn"
  python main.py --m3u --full --category sport --epg-url "https://example.com/epg.xml"
  python main.py --m3u --full --category sport --backup-server http://backup:8080 --include-backups
  python main.py --m3u --full --category sport --backup-server "http://other:80|user|pass|Other Provider" --include-backups
  python main.py --m3u --full --category sport --backup-match merge --backup-server "http://other:80|user|pass|Other Provider" --include-backups
  python main.py --m3u --full --category sport --backup-server "http://other:80|user|pass|Other Provider|merge" --backup-server http://mirror-domain.com --include-backups
  python main.py --m3u --full --category sport --ask-backups --include-backups
  python main.py --m3u --full --live --vod --output playlists

Backup behavior:
  server only:
    treated as a mirror by default; primary stream IDs are reused.

  server|username|password:
    treated as a separate provider by default; backup streams are fetched and
    matched by normalized channel name so the backup provider's own stream IDs
    are used.

  Override globally with:
    --backup-match auto     default behavior
    --backup-match mirror   force mirror mode for all backups
    --backup-match name     force name-match mode for all backups
    --backup-match merge    fetch backup providers with the same filters and append their channels
    --backup-name-threshold 0.82  loosen/tighten name matching for separate providers

  Override one provider with a 5th field:
    http://server:port|username|password|Provider Name|mirror
    http://server:port|username|password|Provider Name|name
    http://server:port|username|password|Provider Name|merge

  If a separate backup provider uses very different category names, add:
    --backup-search-all

Category and channel filters are case-insensitive. Regex is supported, but plain exclude words like sd are handled safely as whole tokens.
        """,
    )

    auth = parser.add_argument_group("authentication")
    auth.add_argument(
        "--server", help="Xtream server URL. Defaults to SERVER from .env"
    )
    auth.add_argument(
        "--username", help="Xtream username. Defaults to USERNAME from .env"
    )
    auth.add_argument(
        "--password", help="Xtream password. Defaults to PASSWORD from .env"
    )

    export = parser.add_argument_group("export type")
    export.add_argument("--live", action="store_true", help="Export live TV")
    export.add_argument("--vod", action="store_true", help="Export movies/VOD")
    export.add_argument("--series", action="store_true", help="Export series list")
    export.add_argument("--txt", action="store_true", help="Export TXT playlist")
    export.add_argument("--m3u", action="store_true", help="Export M3U playlist")
    export.add_argument(
        "--full",
        action="store_true",
        help="Generate one full playlist instead of category files",
    )
    export.add_argument(
        "--output", default=DEFAULT_OUTPUT, help="Output directory. Default: output"
    )
    export.add_argument(
        "--keep-prev", action="store_true", help="Do not rotate previous output folder"
    )
    export.add_argument(
        "--container",
        default="ts",
        choices=["ts", "m3u8"],
        help="Live stream container. Default: ts",
    )

    filters = parser.add_argument_group("filters")
    filters.add_argument(
        "--category",
        action="append",
        help="Only include categories matching this regex/keyword. Can be used multiple times",
    )
    filters.add_argument(
        "--exclude-category",
        action="append",
        help="Exclude categories matching this regex/keyword. Plain words like 'sd' match as a separate word/token",
    )
    filters.add_argument(
        "--channel",
        action="append",
        help="Only include channels/streams matching this regex/keyword. Can be used multiple times",
    )
    filters.add_argument(
        "--exclude-channel",
        action="append",
        help="Exclude channels/streams matching this regex/keyword. Plain words like 'sd' match as a separate word/token",
    )
    filters.add_argument(
        "--list-categories",
        action="store_true",
        help="Print matching categories and exit",
    )

    epg = parser.add_argument_group("epg")
    epg.add_argument(
        "--no-epg", action="store_true", help="Do not add x-tvg-url to M3U output"
    )
    epg.add_argument(
        "--auto-epg",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add provider xmltv.php EPG URL to M3U output. Enabled by default",
    )
    epg.add_argument(
        "--epg-url", action="append", help="Custom EPG URL. Can be used multiple times"
    )
    epg.add_argument(
        "--backup-epg", action="store_true", help="Also add backup provider EPG URLs"
    )
    epg.add_argument(
        "--epg-header-mode",
        choices=["single", "compat"],
        default="compat",
        help="M3U EPG header style. single writes only x-tvg-url; compat also writes url-tvg and tvg-url. Default: compat",
    )

    backups = parser.add_argument_group("backup providers")
    backups.add_argument(
        "--backup-server",
        action="append",
        help="Backup server/provider. Can be used multiple times",
    )
    backups.add_argument(
        "--ask-backups", action="store_true", help="Prompt for backup server URLs"
    )
    backups.add_argument(
        "--include-backups",
        action="store_true",
        help="Duplicate live entries using backup providers",
    )
    backups.add_argument(
        "--backup-mode",
        choices=["suffix", "duplicate"],
        default="suffix",
        help="suffix adds [Backup Name] to backup channel names. duplicate keeps the same name",
    )
    backups.add_argument(
        "--backup-match",
        choices=["auto", "mirror", "name", "merge"],
        default="auto",
        help=(
            "How to use backup providers. auto: server-only backups are mirrors; "
            "backups with explicit username/password are matched by channel name. "
            "merge: fetch backup providers with the same filters and append channels."
        ),
    )
    backups.add_argument(
        "--backup-search-all",
        action="store_true",
        help="For name/merge backups, use all backup categories instead of only categories matching --category",
    )
    backups.add_argument(
        "--backup-name-threshold",
        type=float,
        default=0.82,
        help="Loose name-match threshold for backup-match name. Lower finds more matches but risks wrong matches. Default: 0.82",
    )
    backups.add_argument(
        "--validate-backups",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Validate backups with explicit username/password before exporting. Enabled by default",
    )
    backups.add_argument(
        "--dedupe",
        choices=["none", "name", "url", "name-url"],
        default="name-url",
        help="Remove duplicates. Use 'none' if you intentionally want duplicates",
    )

    args = parser.parse_args()

    if not 0.0 <= args.backup_name_threshold <= 1.0:
        parser.error("--backup-name-threshold must be between 0.0 and 1.0")

    if not (args.live or args.vod or args.series):
        args.live = True

    if not (args.txt or args.m3u):
        args.txt = True

    return args


def main() -> None:
    load_dotenv()
    args = parse_args()

    try:
        server, username, password = load_credentials(args)

        primary_provider = Provider(
            server=server,
            username=username,
            password=password,
            name="Primary",
        )
        primary_client = XtreamClient(primary_provider)

        backup_values = []
        backup_values.extend(parse_csv_env(os.getenv("BACKUP_SERVERS")))
        backup_values.extend(args.backup_server or [])

        if args.ask_backups:
            backup_values.extend(prompt_backup_servers())

        backup_match = normalize_backup_match_arg(str(args.backup_match))
        backup_specs = [
            provider_from_string(value, username, password, index, backup_match)
            for index, value in enumerate(backup_values, start=1)
        ]
        backup_clients = [spec.client for spec in backup_specs]

        if backup_clients:
            print("Backup providers:")
            for spec in backup_specs:
                provider = spec.client.provider
                reason = (
                    "explicit credentials"
                    if spec.explicit_credentials
                    else "same credentials"
                )
                print(
                    f"  {provider.name}: {provider.server} "
                    f"mode={provider.stream_match} ({reason})"
                )

            if args.validate_backups:
                validate_backup_clients(backup_specs)

        stream_types = []
        if args.live:
            stream_types.append(LIVE_TYPE)
        if args.vod:
            stream_types.append(VOD_TYPE)
        if args.series:
            stream_types.append(SERIES_TYPE)

        if args.list_categories:
            print_categories(
                primary_client, stream_types, args.category, args.exclude_category
            )
            return

        if args.live:
            export_live(args, primary_client, backup_clients)

        if args.vod:
            export_vod_or_series(args, primary_client, VOD_TYPE)

        if args.series:
            export_vod_or_series(args, primary_client, SERIES_TYPE)

    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(2)

    except ValueError as exc:
        print(f"Invalid provider config: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

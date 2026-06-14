from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from urls import LIVE_TYPE, SERIES_TYPE, VOD_TYPE, Provider, XtreamClient

SEPARATOR = ";\n"
DEFAULT_OUTPUT = "output"


class ConfigError(RuntimeError):
    pass


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
    path: Path, entries: list[dict[str, Any]], epg_urls: list[str] | None = None
) -> None:
    """Write an M3U playlist.

    If epg_urls is provided, the playlist header points IPTV players to XMLTV.
    Several attribute names are written for better player compatibility:
      - x-tvg-url
      - url-tvg
      - tvg-url
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    epg_urls = [url.strip() for url in (epg_urls or []) if url and url.strip()]
    epg_value = m3u_escape(",".join(epg_urls))

    with path.open("w", encoding="utf-8") as file:
        if epg_value:
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
    raw: str, fallback_user: str, fallback_pass: str, index: int
) -> Provider:
    """
    Supported formats:
      http://server:port
      http://server:port|username|password
      http://server:port|username|password|Display Name
    """
    parts = [part.strip() for part in raw.split("|")]

    server = require_text(parts[0] if parts else None, f"BACKUP_SERVER_{index}")
    username = parts[1] if len(parts) > 1 and parts[1] else fallback_user
    password = parts[2] if len(parts) > 2 and parts[2] else fallback_pass
    name = parts[3] if len(parts) > 3 and parts[3] else f"Backup {index}"

    return Provider(server=server, username=username, password=password, name=name)


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
    stream_id = stream.get("stream_id") or stream.get("id")
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


def build_epg_urls(
    args: argparse.Namespace,
    primary_client: XtreamClient,
    backup_clients: list[XtreamClient],
) -> list[str]:
    """Build XMLTV URLs that will be written into the M3U header.

    Default behavior:
      - add the primary provider XMLTV URL automatically
      - add custom --epg-url values if provided
      - add backup provider XMLTV URLs only when --backup-epg is used
    """
    if args.no_epg:
        return []

    epg_urls: list[str] = []

    if args.auto_epg:
        epg_urls.append(primary_client.build_epg_url())

        if args.backup_epg:
            epg_urls.extend(client.build_epg_url() for client in backup_clients)

    epg_urls.extend(args.epg_url or [])

    # Keep order but remove duplicates and empty values.
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
        print(f"  {url}")


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

    epg_urls = build_epg_urls(args, primary_client, backup_clients)
    include_channel_patterns = compile_patterns(args.channel)
    exclude_channel_patterns = compile_patterns(
        args.exclude_channel, smart_plain_words=True
    )

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
                for backup_client in backup_clients:
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
                )

            print(f"Wrote {len(category_entries):5d} → {category_name}")
            total += len(category_entries)

    full_entries = dedupe_entries(full_entries, args.dedupe)

    if args.full and full_entries:
        if args.txt:
            txt_lines = [
                f"{entry['display_name']}, {entry['url']}" for entry in full_entries
            ]
            write_txt(output_dir / "all_live.txt", txt_lines)

        if args.m3u:
            m3u_path = output_dir / "all_live.m3u"
            write_m3u(m3u_path, full_entries, epg_urls)
            print(f"Wrote M3U file: {m3u_path}")
            print_epg_urls(epg_urls)

        total = len(full_entries)
        print(f"Wrote full live playlist → {total} channels")

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
  python main.py --m3u --full --category sport --exclude-category "adult|xxx"
  python main.py --m3u --full --category sport --exclude-category sd --exclude-channel sd
  python main.py --m3u --full --category sport --channel "sky sports|tnt|dazn"
  python main.py --m3u --full --category sport
  python main.py --m3u --full --category sport --epg-url "https://example.com/epg.xml"
  python main.py --m3u --full --category sport --backup-server http://backup:8080 --include-backups
  python main.py --m3u --full --category sport --ask-backups --include-backups
  python main.py --m3u --full --live --vod --output playlists

Category and channel filters are case-insensitive. Regex is supported, but plain exclude words like sd are handled safely as whole tokens.
Backup servers are assumed to be mirrors using the same stream IDs unless you provide full credentials.
Backup format:
  --backup-server "http://server:port"
  --backup-server "http://server:port|username|password"
  --backup-server "http://server:port|username|password|Provider Name"
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
        "--dedupe",
        choices=["none", "name", "url", "name-url"],
        default="name-url",
        help="Remove duplicates. Use 'none' if you intentionally want duplicates",
    )

    args = parser.parse_args()

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

        backup_clients = [
            XtreamClient(provider_from_string(value, username, password, index))
            for index, value in enumerate(backup_values, start=1)
        ]

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

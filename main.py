import os
import argparse
import sys
import re
import shutil

from dotenv import load_dotenv

import urls
from urls import categories, streams_by_category, build_stream_url

"""
====================================================
DEPENDENCIES & INSTALLATION GUIDE
====================================================

This project requires the following Python packages:

- requests        → HTTP calls to Xtream Codes API
- python-dotenv   → Load SERVER / USERNAME / PASSWORD from .env

----------------------------------------------------
IMPORTANT (macOS / Homebrew users)
----------------------------------------------------

If you installed Python via Homebrew, pip is RESTRICTED
by PEP 668 and WILL NOT allow system-wide installs.

DO NOT use:
    pip install requests
    pip install python-dotenv
outside a virtual environment.

----------------------------------------------------
RECOMMENDED SETUP (Virtual Environment)
----------------------------------------------------

1) Navigate to the project directory:

    cd m3uDownloader

2) Create a virtual environment:

    python3 -m venv .venv

3) Activate the virtual environment:

    source .venv/bin/activate

   You should now see (.venv) in your terminal prompt.

4) Install required packages INSIDE the venv:

    pip install requests python-dotenv

5) (Optional) Save dependencies:

    pip freeze > requirements.txt

----------------------------------------------------
RUNNING THE SCRIPT
----------------------------------------------------

Every time you open a new terminal, you MUST activate
the virtual environment first:

    source .venv/bin/activate
    python main.py

----------------------------------------------------
ENVIRONMENT VARIABLES (.env)
----------------------------------------------------

Create a file named .env in the project root:

    SERVER=http://your-server:port
    USERNAME=your_username
    PASSWORD=your_password

DO NOT commit .env to Git.
Add this to .gitignore:

    .env

----------------------------------------------------
TROUBLESHOOTING
----------------------------------------------------

If you see:
    ModuleNotFoundError: No module named 'requests'

It means:
    - The virtual environment is not activated
    - OR packages were installed outside the venv

Fix:
    source .venv/bin/activate
    pip install requests python-dotenv

====================================================
"""


def ensure_venv():
    """
    Warn if the script is not running inside a virtual environment.
    This prevents 'ModuleNotFoundError' issues on macOS/Homebrew.
    """
    if sys.prefix == sys.base_prefix:
        print(
            "\n[WARNING] Virtual environment not detected.\n"
            "It is strongly recommended to run this script inside a venv:\n\n"
            "  python3 -m venv .venv\n"
            "  source .venv/bin/activate\n"
            "  pip install -r requirements.txt\n"
        )


load_dotenv()

urls.SERVER = os.getenv("SERVER")
urls.USERNAME = os.getenv("USERNAME")
urls.PASSWORD = os.getenv("PASSWORD")

if not all([urls.SERVER, urls.USERNAME, urls.PASSWORD]):
    raise RuntimeError("Missing SERVER / USERNAME / PASSWORD in .env")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Xtream Codes IPTV exporter (TXT / M3U)"
    )

    parser.add_argument(
        "--container",
        default="ts",
        choices=["ts", "m3u8"],
        help="Stream container type (default: ts)",
    )

    parser.add_argument("--txt", action="store_true", help="Export TXT playlists")

    parser.add_argument("--m3u", action="store_true", help="Export M3U playlists")

    parser.add_argument(
        "--full",
        action="store_true",
        help="Generate single full playlist instead of category split",
    )

    parser.add_argument(
        "--output", default="output", help="Base output directory (default: output)"
    )

    parser.add_argument("--live", action="store_true", help="Export live TV")
    parser.add_argument("--vod", action="store_true", help="Export movies")
    parser.add_argument("--series", action="store_true", help="Export series")
    parser.add_argument(
        "--keep-prev",
        action="store_true",
        help="Keep previous output instead of replacing it"
    )

    return parser.parse_args()


args = parse_args()

if not (args.live or args.vod or args.series):
    args.live = True

KEEP_PREV = args.keep_prev
LIVE_CONTAINER = args.container
VOD_CONTAINER = "mkv"
SERIES_CONTAINER = "mkv"
EXPORT_TXT = args.txt or not args.m3u  # default TXT if nothing specified
EXPORT_M3U = args.m3u
SPLIT_BY_CATEGORY = not args.full

BASE_OUTPUT_DIR = args.output
TXT_DIR = os.path.join(BASE_OUTPUT_DIR, "txt")
M3U_DIR = os.path.join(BASE_OUTPUT_DIR, "m3u")

SEPARATOR = ";\n"
LIVE_TYPE = "live"
VOD_TYPE = "vod"
SERIES_TYPE = "series"

VOD_DIR = os.path.join(BASE_OUTPUT_DIR, "vod")
SERIES_DIR = os.path.join(BASE_OUTPUT_DIR, "series")


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()

def prepare_sub_output(base_dir: str, sub_dir: str, keep_prev: bool):
    """
    Prepares output/<sub_dir> directory.

    - If keep_prev is False:
        output/<sub_dir>     -> prev_<sub_dir>
        prev_<sub_dir> is deleted if it already exists
    - If keep_prev is True:
        output/<sub_dir> is reused
    """
    target = os.path.join(base_dir, sub_dir)
    prev = os.path.join(base_dir, f"prev_{sub_dir}")

    if keep_prev:
        os.makedirs(target, exist_ok=True)
        return

    if os.path.exists(prev):
        shutil.rmtree(prev)

    if os.path.exists(target):
        os.rename(target, prev)

    os.makedirs(target, exist_ok=True)

def is_valid_channel(name: str) -> bool:
    if not name:
        return False

    name = name.strip()

    # Header / separator channels
    if name.count("#") > 3:
        return False

    if len(name) < 3:
        return False

    return True


def write_txt(path: str, lines: list[str]):
    with open(path, "w", encoding="utf-8") as f:
        f.write(SEPARATOR.join(lines))
        f.write(SEPARATOR)


def write_m3u(path: str, lines: list[str]):
    with open(path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for line in lines:
            name, url = line.split(",", 1)
            f.write(f"#EXTINF:-1,{name.strip()}\n")
            f.write(f"{url.strip()}\n")


def export_live_streams():
    if args.txt:
        prepare_sub_output(BASE_OUTPUT_DIR, "txt", KEEP_PREV)
    if args.m3u:
        prepare_sub_output(BASE_OUTPUT_DIR, "m3u", KEEP_PREV)


    categories_data = categories(LIVE_TYPE)
    if not categories_data:
        print("No live categories found")
        return

    full_playlist = []
    total = 0

    for cat in categories_data:
        category_id = cat.get("category_id")
        category_name = safe_filename(cat.get("category_name", "Unknown"))

        streams = streams_by_category(LIVE_TYPE, category_id)
        if not streams:
            continue

        category_lines = []

        for stream in streams:
            stream_id = stream.get("stream_id")
            name = stream.get("name", "")

            if not stream_id:
                continue

            if not is_valid_channel(name):
                continue

            url = build_stream_url(stream_id, LIVE_TYPE, LIVE_CONTAINER)
            entry = f"{name.strip()}, {url}"

            category_lines.append(entry)
            full_playlist.append(entry)

        if SPLIT_BY_CATEGORY and category_lines:
            if EXPORT_TXT:
                txt_path = os.path.join(TXT_DIR, f"{category_name}.txt")
                write_txt(txt_path, category_lines)

            if EXPORT_M3U:
                m3u_path = os.path.join(M3U_DIR, f"{category_name}.m3u")
                write_m3u(m3u_path, category_lines)

            print(f"Wrote {len(category_lines):5d} → {category_name}")
            total += len(category_lines)

    if not SPLIT_BY_CATEGORY and full_playlist:
        if EXPORT_TXT:
            write_txt(os.path.join(BASE_OUTPUT_DIR, "all.txt"), full_playlist)

        if EXPORT_M3U:
            write_m3u(os.path.join(BASE_OUTPUT_DIR, "all.m3u"), full_playlist)

        total = len(full_playlist)
        print(f"Wrote full playlist → {total} channels")

    print(f"\nTotal exported channels: {total}")


def export_movies():
    prepare_sub_output(BASE_OUTPUT_DIR, "vod", KEEP_PREV)

    categories_data = urls.categories(VOD_TYPE)
    if not categories_data:
        print("No VOD categories found")
        return

    for cat in categories_data:
        cat_id = cat["category_id"]
        cat_name = safe_filename(cat["category_name"])
        cat_dir = os.path.join(VOD_DIR, cat_name)
        os.makedirs(cat_dir, exist_ok=True)

        movies = urls.streams_by_category(VOD_TYPE, cat_id)
        if not movies:
            continue

        movie_lines = []

        for movie in movies:
            stream_id = movie.get("stream_id")
            name = movie.get("name", "Unknown")
            year = movie.get("year", "")

            if not stream_id:
                continue

            title = name.strip()
            if year:
                title = f"{title} ({year})"
            url = build_stream_url(stream_id, VOD_TYPE, VOD_CONTAINER)

            movie_lines.append(f"{title}, {url}")

        if not movie_lines:
            continue

        if EXPORT_TXT:
            write_txt(os.path.join(cat_dir, f"{cat_name}.txt"), movie_lines)

        if EXPORT_M3U:
            write_m3u(os.path.join(cat_dir, f"{cat_name}.m3u"), movie_lines)

        print(f"Wrote movies → {cat_name}")


def export_series():
    prepare_sub_output(BASE_OUTPUT_DIR, "series", KEEP_PREV)

    categories_data = urls.categories(SERIES_TYPE)
    if not categories_data:
        print("No series categories found")
        return

    for cat in categories_data:
        cat_id = cat["category_id"]
        series_list = urls.streams_by_category(SERIES_TYPE, cat_id)

        if not series_list:
            continue

        category_name = safe_filename(cat.get("category_name", "Unknown"))
        category_dir = os.path.join(SERIES_DIR, category_name)
        os.makedirs(category_dir, exist_ok=True)

        for series in series_list:
            series_id = series.get("series_id")
            series_name = safe_filename(series.get("name", "Unknown Series"))

            if not series_id:
                continue

            series_dir = os.path.join(category_dir, series_name)
            os.makedirs(series_dir, exist_ok=True)

            info = urls.series_info_by_id(series_id)
            if not info:
                continue

            episodes_by_season = info.get("episodes")
            if not isinstance(episodes_by_season, dict):
                continue

            for season_num, episodes in episodes_by_season.items():
                season_dir = os.path.join(series_dir, f"Season {int(season_num):02d}")
                os.makedirs(season_dir, exist_ok=True)

                season_lines = []

                for ep in episodes:
                    ep_num = ep.get("episode_num")
                    ep_id = ep.get("id")

                    if not ep_id or ep_num is None:
                        continue

                    title = f"{series_name} - S{int(season_num):02d}E{int(ep_num):02d}"
                    url = build_stream_url(ep_id, SERIES_TYPE, SERIES_CONTAINER)

                    season_lines.append(f"{title}, {url}")

                if not season_lines:
                    continue

                season_label = safe_filename(f"Season {int(season_num):02d}")

                if EXPORT_TXT:
                    write_txt(
                        os.path.join(season_dir, f"{season_label}.txt"), season_lines
                    )

                if EXPORT_M3U:
                    write_m3u(
                        os.path.join(season_dir, f"{season_label}.m3u"), season_lines
                    )

            print(f"Wrote series → {series_name}")


if __name__ == "__main__":
    ensure_venv()

    if args.live:
        export_live_streams()

    if args.vod:
        export_movies()

    if args.series:
        export_series()

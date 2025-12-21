import os
import argparse
import sys
import re

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

    return parser.parse_args()


args = parse_args()

OUTPUT_CONTAINER = args.container
EXPORT_TXT = args.txt or not args.m3u  # default TXT if nothing specified
EXPORT_M3U = args.m3u
SPLIT_BY_CATEGORY = not args.full

BASE_OUTPUT_DIR = args.output
TXT_DIR = os.path.join(BASE_OUTPUT_DIR, "txt")
M3U_DIR = os.path.join(BASE_OUTPUT_DIR, "m3u")

SEPARATOR = ";\n"
LIVE_TYPE = "live"


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


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
    os.makedirs(TXT_DIR, exist_ok=True)
    os.makedirs(M3U_DIR, exist_ok=True)

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

            url = build_stream_url(stream_id, LIVE_TYPE, OUTPUT_CONTAINER)
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


if __name__ == "__main__":
    ensure_venv()
    export_live_streams()

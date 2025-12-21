# Xtream Codes IPTV Exporter

Simple IPTV exporter for Xtream Codes providers.  
Generates **TXT** and/or **M3U** playlists, split by category or as a single file.  
Optimized for **VLC (iOS/macOS)** and large playlists.

---

## Features

- TXT and M3U export
- Category-based or full playlist
- Filters fake/header channels (####)
- Loads credentials from `.env`
- Command-line flags (no code edits required)
- Handles 15k+ channels

---

## Requirements

- Python 3.9+
- requests
- python-dotenv

---

## Setup

```bash
git clone <repo>
cd m3uDownloader
python3 -m venv .venv
source .venv/bin/activate
pip install requests python-dotenv
```

### .env Configuration

- Create a .env file in the project root:

```env
SERVER=http://your-server:port
USERNAME=your_username
PASSWORD=your_password
```

***Do not commit .env to Git.***

### Usage

- Default (TXT, split by category)
```bash
python main.py
```

- M3U only
```bash
python main.py --m3u
```

- TXT and M3U
```bash
python main.py --txt --m3u
```

- Single full playlist
```bash
python main.py --full
```

- Mobile-friendly streams
```bash
python main.py --container m3u8
```
```

```
## Output

output/
├── txt/
│   └── *.txt
├── m3u/
│   └── *.m3u
├── all.txt
└── all.m3u
```


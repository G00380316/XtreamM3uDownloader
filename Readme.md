# Xtream M3U Downloader

Advanced Xtream Codes playlist exporter for generating TXT and M3U playlists from a provider account.

It supports:

- Live TV, VOD, and series exports
- Full playlist output or split-by-category output
- Category filtering, for example Sports only
- M3U output with EPG metadata
- Custom EPG URLs
- Backup provider URLs
- Optional duplicate backup entries
- Basic channel deduplication
- Request retries and timeouts
- `.env` credentials
- A proper `--help` command

> Use this only with providers/accounts you are allowed to access.

---

## 1. Project files

Your project should look like this:

```text
XtreamM3uDownloader/
├── main.py
├── urls.py
├── .env
├── README.md
└── requirements.txt
```

---

## 2. Install requirements

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install requests python-dotenv
```

Optional, save dependencies:

```bash
pip freeze > requirements.txt
```

---

## 3. `.env` setup

Create a `.env` file in the project root:

```env
SERVER=http://your-server:port
USERNAME=your_username
PASSWORD=your_password
```

Optional backup servers can also be stored in `.env`:

```env
BACKUP_SERVERS=http://backup1:8080,http://backup2:8080
```

Backup servers with their own credentials use this format:

```env
BACKUP_SERVERS=http://backup1:8080|user1|pass1|Backup 1,http://backup2:8080|user2|pass2|Backup 2
```

Do not commit `.env` to GitHub. Add this to `.gitignore`:

```gitignore
.env
.venv/
output/
prev_output/
```

---

## 4. Basic usage

Show help:

```bash
python main.py --help
```

By default, if you do not choose `--live`, `--vod`, or `--series`, the script exports live TV.

By default, if you do not choose `--txt` or `--m3u`, the script exports TXT.

Default command:

```bash
python main.py
```

This exports live TV as TXT files.

---

## 5. List categories

List live categories:

```bash
python main.py --list-categories --live
```

List VOD categories:

```bash
python main.py --list-categories --vod
```

List series categories:

```bash
python main.py --list-categories --series
```

List only matching categories:

```bash
python main.py --list-categories --live --category sport
```

---

## 6. Export M3U playlist

Export live TV as M3U split by category:

```bash
python main.py --m3u --live
```

Export live TV as one full M3U playlist:

```bash
python main.py --m3u --full --live
```

Because live is the default, this also works:

```bash
python main.py --m3u --full
```

Output file:

```text
output/all_live.m3u
```

---

## 7. Export Sports only

Export only categories containing `sport`:

```bash
python main.py --m3u --full --category sport
```

Export sports, football, F1, and boxing categories:

```bash
python main.py --m3u --full --category "sport|football|f1|boxing"
```

Exclude adult categories:

```bash
python main.py --m3u --full --category sport --exclude-category "adult|xxx|18+"
```

Exclude SD categories and SD channels:

```bash
python main.py --m3u --full \
  --category "sport|football|world cup|ireland|^IE\||now tv|news|general|tnt" \
  --exclude-category sd \
  --exclude-channel sd
```

You do **not** need to type the long regex for SD anymore. For exclude filters, plain words like `sd` are treated as a separate word/token, so `--exclude-channel sd` matches `TNT Sport SD` but does not match random letters inside a bigger word.

Only include channels matching a name pattern:

```bash
python main.py --m3u --full --category sport --channel "sky sports|tnt|dazn"
```

Category and channel filters are case-insensitive. Regex is supported, but plain exclude words like `sd` are handled safely.

You can also use multiple `--category` flags:

```bash
python main.py --m3u --full --category sport --category football
```

---

## 8. EPG support

For M3U output, the script automatically adds the provider EPG URL:

```m3u
#EXTM3U x-tvg-url="http://server/xmltv.php?username=USER&password=PASS"
```

Each channel entry can include metadata like:

```m3u
#EXTINF:-1 tvg-id="channel-id" tvg-name="Channel Name" tvg-logo="logo-url" group-title="Sports",Channel Name
http://server/live/user/pass/123.ts
```

Disable automatic EPG:

```bash
python main.py --m3u --full --no-epg
```

Add your own custom EPG URL:

```bash
python main.py --m3u --full --epg-url "https://example.com/epg.xml"
```

Add multiple EPG URLs:

```bash
python main.py --m3u --full \
  --epg-url "https://example.com/epg1.xml" \
  --epg-url "https://example.com/epg2.xml"
```

Add backup provider EPG URLs too:

```bash
python main.py --m3u --full --backup-epg --include-backups
```

---

## 9. Backup servers

Backup servers are useful when you want extra fallback stream URLs in the generated playlist.

Important: backup servers work best when they are mirrors of the same provider/account, because the stream IDs need to match. If the backup is a totally different provider, the stream IDs may not point to the same channels.

Add one backup server:

```bash
python main.py --m3u --full --category sport \
  --backup-server "http://backup-server:8080" \
  --include-backups
```

Add multiple backup servers:

```bash
python main.py --m3u --full --category sport \
  --backup-server "http://backup1:8080" \
  --backup-server "http://backup2:8080" \
  --include-backups
```

Add backup server with different credentials:

```bash
python main.py --m3u --full --category sport \
  --backup-server "http://backup-server:8080|username|password|Backup 1" \
  --include-backups
```

Prompt for backup servers interactively:

```bash
python main.py --m3u --full --category sport --ask-backups --include-backups
```

---

## 10. Backup duplicate modes

Default backup mode adds the backup provider name to the channel:

```text
Sky Sports Main Event [Backup 1]
```

Command:

```bash
python main.py --m3u --full --category sport \
  --backup-server "http://backup-server:8080" \
  --include-backups \
  --backup-mode suffix
```

Keep backup channels with the same name:

```bash
python main.py --m3u --full --category sport \
  --backup-server "http://backup-server:8080" \
  --include-backups \
  --backup-mode duplicate
```

If you want real duplicate entries to remain, also disable dedupe:

```bash
python main.py --m3u --full --category sport \
  --backup-server "http://backup-server:8080" \
  --include-backups \
  --backup-mode duplicate \
  --dedupe none
```

---

## 11. Deduplication modes

The script supports these dedupe modes:

```text
none      Keep everything
name      Remove channels with the same name
url       Remove channels with the same URL
name-url  Remove only exact same name + URL combinations
```

Default:

```bash
--dedupe name-url
```

Examples:

```bash
python main.py --m3u --full --dedupe name
```

```bash
python main.py --m3u --full --dedupe none
```

---

## 12. TXT output

Export TXT split by category:

```bash
python main.py --txt --live
```

Export one full TXT playlist:

```bash
python main.py --txt --full --live
```

Output file:

```text
output/all_live.txt
```

TXT format:

```text
Channel Name, http://server/live/user/pass/123.ts;
```

---

## 13. VOD and series

Export VOD:

```bash
python main.py --m3u --vod
```

Export series:

```bash
python main.py --m3u --series
```

Export live, VOD, and series:

```bash
python main.py --m3u --live --vod --series
```

VOD and series use `mkv` stream URLs by default.

---

## 14. Output folders

Default output folder:

```text
output/
```

Use a different output folder:

```bash
python main.py --m3u --full --output playlists
```

By default, the script rotates old output folders into `prev_*` folders before creating new output.

Keep previous output instead:

```bash
python main.py --m3u --full --keep-prev
```

---

## 15. Live stream container

Default live container is `ts`:

```bash
python main.py --m3u --full --container ts
```

Use `m3u8` instead:

```bash
python main.py --m3u --full --container m3u8
```

---

## 16. Troubleshooting

### `Missing SERVER / USERNAME / PASSWORD`

Create a `.env` file:

```env
SERVER=http://your-server:port
USERNAME=your_username
PASSWORD=your_password
```

Or pass credentials directly:

```bash
python main.py --server "http://server:port" --username "user" --password "pass" --m3u --full
```

### `Read timed out`

The provider took too long to respond. The script now retries failed requests and uses separate connect/read timeouts.

You may still see messages like:

```text
[TIMEOUT] Primary: live category 123 attempt 1/3
[SKIPPED] Primary: live category 123 failed after 3 attempts
```

That means the script skipped one slow category instead of crashing.

### `JSON ERROR`

The provider returned invalid JSON, often because the server is down, blocked, expired, or returned an HTML error page instead of API data.

### Backup links do not play

Backup links only work if the backup server uses the same stream IDs. If it is a different provider, the stream IDs may not match.

### M3U has duplicates

Use stricter dedupe:

```bash
python main.py --m3u --full --dedupe name
```

Or keep duplicates intentionally:

```bash
python main.py --m3u --full --dedupe none
```

---

## 17. Recommended commands

Sports full M3U with EPG:

```bash
python main.py --m3u --full --category "sport|football|f1|boxing"
```

Sports/news/custom full M3U with backups and no SD:

```bash
python main.py --m3u --full \
  --category "sport|football|world cup|ireland|^IE\||now tv|news|general|tnt" \
  --exclude-category sd \
  --exclude-channel sd \
  --backup-server "http://backup1:8080" \
  --backup-server "http://backup2:8080" \
  --include-backups \
  --backup-mode suffix \
  --dedupe url \
  --output output/custom
```

Sports full M3U with custom EPG and no duplicates by name:

```bash
python main.py --m3u --full --category "sport|football|f1|boxing" \
  --epg-url "https://example.com/epg.xml" \
  --dedupe name
```


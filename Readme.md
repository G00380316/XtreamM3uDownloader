# XtreamM3uDownloader

Advanced Xtream Codes playlist exporter for live TV, VOD, and series playlists.

This tool can export filtered TXT/M3U playlists from an Xtream Codes account, add XMLTV/EPG URLs to M3U headers, remove unwanted categories/channels, and combine backup providers in several different ways.

## Features

- Live TV, VOD, and series category export
- TXT and M3U output
- Full live playlist or per-category live files
- Category include/exclude filters
- Channel include/exclude filters
- Friendly whole-token excludes such as `--exclude-channel sd`
- M3U XMLTV/EPG header support
- Backup providers in `auto`, `mirror`, `name`, or `merge` mode
- Looser backup name matching with a configurable threshold
- Merged provider category labels as `Category Name | Provider Name`
- Per-backup mode override
- Backup validation for providers with their own username/password
- Dedupe modes for names, URLs, or both
- Retry and timeout handling for slow Xtream APIs
- Safer terminal logs that mask EPG username/password values

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests python-dotenv
```

Every new terminal session needs the virtual environment activated again:

```bash
source .venv/bin/activate
```

## Project files

Expected project layout:

```text
XtreamM3uDownloader/
├── main.py
├── urls.py
├── .env
└── README.md
```

## Environment file

Create `.env` in the project root:

```env
SERVER=http://your-server:port
USERNAME=your_username
PASSWORD=your_password
```

Optional backup providers can also be stored in `.env`:

```env
BACKUP_SERVERS=http://mirror-domain.com,http://other-provider.com:80|other_user|other_pass|Other Provider|merge
```

Do not commit `.env` to Git.

Recommended `.gitignore` entry:

```gitignore
.env
output/
prev_output/
```

## Help command

```bash
python main.py --help
```

## Important defaults

If you run the script with no media type:

```bash
python main.py
```

it defaults to:

```text
--live
```

If you do not specify an output format:

```bash
python main.py --live
```

it defaults to:

```text
--txt
```

So this:

```bash
python main.py --category sport
```

means:

```bash
python main.py --live --txt --category sport
```

To create an M3U, always include:

```bash
--m3u
```

To create both TXT and M3U, include both:

```bash
--txt --m3u
```

## Argument reference

### Authentication arguments

| Argument | Value | Purpose |
|---|---|---|
| `--server` | URL | Xtream server URL. Overrides `SERVER` in `.env`. |
| `--username` | text | Xtream username. Overrides `USERNAME` in `.env`. |
| `--password` | text | Xtream password. Overrides `PASSWORD` in `.env`. |

Example without `.env`:

```bash
python main.py --m3u --full \
  --server "http://server:port" \
  --username "my_user" \
  --password "my_pass" \
  --category sport
```

### Media selection arguments

| Argument | Purpose |
|---|---|
| `--live` | Export live TV. Default when no media type is provided. |
| `--vod` | Export movies/VOD categories. |
| `--series` | Export series categories. |

You can combine them:

```bash
python main.py --m3u --live --vod --series --output output/all_media
```

### Output format arguments

| Argument | Purpose |
|---|---|
| `--txt` | Write TXT playlist files. Default when no output format is provided. |
| `--m3u` | Write M3U playlist files. |
| `--txt --m3u` | Write both TXT and M3U files. |

### Output layout arguments

| Argument | Value | Purpose |
|---|---|---|
| `--full` | none | For live TV, write one combined live playlist. |
| `--output` | directory | Base output folder. Default: `output`. |
| `--keep-prev` | none | Do not rotate/delete previous output folder. |
| `--container` | `ts` or `m3u8` | Live stream URL extension. Default: `ts`. |

`--full` currently affects live TV export. VOD and series currently write category folders.

### Filter arguments

| Argument | Can repeat? | Purpose |
|---|---:|---|
| `--category` | yes | Include categories matching this text or regex. |
| `--exclude-category` | yes | Exclude categories matching this text or regex. Plain words like `sd` match as whole tokens. |
| `--channel` | yes | Include channels/streams matching this text or regex. |
| `--exclude-channel` | yes | Exclude channels/streams matching this text or regex. Plain words like `sd` match as whole tokens. |
| `--list-categories` | no | Print matching categories and exit. |

Filters are case-insensitive.

Repeated filters are OR-style within that include/exclude group. These are equivalent:

```bash
--category sport --category football --category news
```

```bash
--category "sport|football|news"
```

Plain excludes such as this:

```bash
--exclude-channel sd
```

are treated safely as whole tokens, so you do not need to write a long regex.

### EPG/XMLTV arguments

| Argument | Value | Purpose |
|---|---|---|
| `--no-epg` | none | Do not write any XMLTV/EPG URL into M3U header. |
| `--auto-epg` | none | Add the primary provider `xmltv.php` URL. Enabled by default. |
| `--no-auto-epg` | none | Do not automatically add the primary provider XMLTV URL. |
| `--epg-url` | URL | Add a custom XMLTV URL. Can be used multiple times. |
| `--backup-epg` | none | Add backup provider XMLTV URLs too. |
| `--epg-header-mode` | `single` or `compat` | `single` writes only `x-tvg-url`; `compat` writes `x-tvg-url`, `url-tvg`, and `tvg-url`. Default: `compat`. |

The XMLTV guide is not embedded inside the M3U. The M3U points to it in the first line.

`single` header example:

```m3u
#EXTM3U x-tvg-url="http://server/xmltv.php?username=USER&password=PASS"
```

`compat` header example:

```m3u
#EXTM3U x-tvg-url="http://server/xmltv.php?username=USER&password=PASS" url-tvg="http://server/xmltv.php?username=USER&password=PASS" tvg-url="http://server/xmltv.php?username=USER&password=PASS"
```

### Backup arguments

| Argument | Value | Purpose |
|---|---|---|
| `--backup-server` | backup string | Add a backup provider. Can be used multiple times. |
| `--ask-backups` | none | Prompt for backup providers interactively. |
| `--include-backups` | none | Actually add backup channels to live output. Required for backup channels. |
| `--backup-mode` | `suffix` or `duplicate` | `suffix` adds `[Backup Name]`; `duplicate` keeps same display names. Default: `suffix`. |
| `--backup-match` | `auto`, `mirror`, `name`, `merge` | Controls how backup providers are used. Default: `auto`. |
| `--backup-search-all` | none | For name/merge backups, search all backup categories instead of matching backup categories by `--category`. |
| `--backup-name-threshold` | `0.82` | Loosen/tighten fuzzy name matching for `name` backups. Lower finds more matches but can risk wrong matches. |
| `--validate-backups` | none | Validate explicit-credential backups before export. Enabled by default. |
| `--no-validate-backups` | none | Skip explicit-credential backup validation. |
| `--dedupe` | `none`, `name`, `url`, `name-url` | Remove duplicates. Default: `name-url`. |

Backups are applied to live TV. VOD and series currently use the primary provider only.

## Backup provider formats

Supported formats:

```text
http://server:port
http://server:port|username|password
http://server:port|username|password|Display Name
http://server:port|username|password|Display Name|mirror
http://server:port|username|password|Display Name|name
http://server:port|username|password|Display Name|merge
```

Always quote backup provider strings because `|` has special meaning in shells:

```bash
--backup-server "http://server:port|username|password|Provider Name|merge"
```

## Backup modes explained

### `auto` mode

Default mode.

| Backup string | Auto behaviour |
|---|---|
| `http://mirror-domain.com` | `mirror` mode |
| `http://other.com:80|user|pass|Other Provider` | `name` mode |
| `http://other.com:80|user|pass|Other Provider|merge` | `merge` mode because per-backup override wins |

Command:

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://mirror-domain.com" \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider" \
  --include-backups \
  --backup-match auto
```

### `mirror` mode

Use for the same provider/account on another domain.

The script reuses primary provider stream IDs and builds alternate URLs on the backup domain.

Example:

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://mirror-domain.com" \
  --include-backups \
  --backup-match mirror \
  --output output/mirror_test
```

Per-backup mirror override:

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://other.com:80|user|pass|Other Provider|mirror" \
  --include-backups
```

Only force `mirror` with explicit credentials if you know stream IDs match.

### `name` mode

Use for a different provider where you want backup alternatives for channels already in the primary playlist.

The script fetches backup streams and matches by normalized channel name, then uses the backup provider's real stream IDs.

Example:

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider" \
  --include-backups \
  --backup-match name \
  --backup-name-threshold 0.82 \
  --dedupe url
```

After running, the summary includes exact/loose matches:

```text
Backup name-match summary for Other Provider: matched=212, fuzzy=38, missed=1267
```

`fuzzy` shows how many backup channels were matched by the looser matching logic.

#### Tuning name matching

The script normalizes channel names before matching. It ignores common noise such as `HD`, `FHD`, `UHD`, `4K`, `RAW`, `HEVC`, `VIP`, `UK`, `US`, and `IE`, and it treats common naming differences like `sport` vs `sports` as equivalent.

Default:

```bash
--backup-name-threshold 0.82
```

More matches, slightly higher risk of wrong matches:

```bash
--backup-name-threshold 0.75
```

Fewer but safer matches:

```bash
--backup-name-threshold 0.90
```

Keep the threshold higher if the providers have many numbered channels like `TNT Sport 1`, `TNT Sport 2`, `Sky Sports 1`, etc. The script blocks obvious number mismatches, but very low thresholds can still create bad matches.

Per-backup name override:

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider|name" \
  --include-backups
```

### `merge` mode

Use for a different provider where you want to add its filtered channels as extra channels/categories, not only alternatives to primary channels.

Merged backup categories are labelled with the provider at the end:

```text
Original category: UK| SPORT HD
Merged category:   UK| SPORT HD | Other Provider
```

That keeps category sorting focused on the original category name while still showing which provider the entries came from.

The script fetches backup categories/streams with the same filters and appends matching backup channels.

Example:

```bash
python main.py --m3u --full \
  --category "sport|football|news" \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider" \
  --include-backups \
  --backup-match merge \
  --dedupe url \
  --output output/merge_test
```

Per-backup merge override:

```bash
python main.py --m3u --full \
  --category "sport|football|news" \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider|merge" \
  --backup-server "http://mirror-domain.com" \
  --include-backups \
  --backup-match auto \
  --dedupe url \
  --output output/mixed_backups
```

That means:

```text
Other Provider = merge mode, uses own categories/streams
mirror-domain.com = mirror mode, reuses primary stream IDs
```

## Output paths

### Live TV with `--full`

```bash
python main.py --m3u --full --category sport --output output/custom
```

Output:

```text
output/custom/all_live.m3u
```

With TXT too:

```bash
python main.py --txt --m3u --full --category sport --output output/custom
```

Outputs:

```text
output/custom/all_live.txt
output/custom/all_live.m3u
```

### Live TV without `--full`

```bash
python main.py --m3u --category sport --output output/custom
```

Output:

```text
output/custom/m3u/<category>.m3u
```

If merge backups are used without `--full`, merged backup channels also go here:

```text
output/custom/m3u/backup_merged.m3u
```

### VOD

```bash
python main.py --m3u --vod --category "movies|action" --output output/custom
```

Output:

```text
output/custom/vod/<category>/<category>.m3u
```

### Series

```bash
python main.py --m3u --series --category "series|netflix|prime" --output output/custom
```

Output:

```text
output/custom/series/<category>/<category>.m3u
```

## Common command recipes

### List live categories

```bash
python main.py --list-categories --live
```

### List VOD categories

```bash
python main.py --list-categories --vod
```

### List series categories

```bash
python main.py --list-categories --series
```

### List matching live categories

```bash
python main.py --list-categories --live --category "sport|football|news|general"
```

### List categories but hide SD categories

```bash
python main.py --list-categories --live \
  --category "sport|football|news" \
  --exclude-category sd
```

### Basic live M3U full playlist

```bash
python main.py --m3u --full --category sport
```

### Basic live TXT full playlist

```bash
python main.py --txt --full --category sport
```

### Live TXT and M3U full playlist

```bash
python main.py --txt --m3u --full --category sport
```

### Per-category live M3U files

```bash
python main.py --m3u --category sport --output output/by_category
```

### Your custom sports/news/general playlist

```bash
python main.py --m3u --full \
  --category "sport|football|world cup|ireland|now tv sport|news|general|tnt" \
  --exclude-category "sd|max|flo|bally|sky sport+" \
  --exclude-channel sd \
  --output output/custom
```

### Include all Ireland `IE|` categories too

Use `^IE\|` to match category names that start with `IE|`:

```bash
python main.py --m3u --full \
  --category "sport|football|world cup|ireland|^IE\||now tv sport|news|general|tnt" \
  --exclude-category "sd|max|flo|bally|sky sport+" \
  --exclude-channel sd \
  --output output/custom
```

### Use M3U8 live links instead of TS

```bash
python main.py --m3u --full \
  --category sport \
  --container m3u8 \
  --output output/m3u8
```

### Keep previous output instead of rotating it

```bash
python main.py --m3u --full \
  --category sport \
  --keep-prev \
  --output output/custom
```

### Include only certain channel names

```bash
python main.py --m3u --full \
  --category sport \
  --channel "sky sports|tnt|dazn|espn" \
  --output output/selected_channels
```

### Exclude more than one category

Repeated style:

```bash
python main.py --m3u --full \
  --category sport \
  --exclude-category sd \
  --exclude-category kids \
  --exclude-category cinema
```

Regex group style:

```bash
python main.py --m3u --full \
  --category sport \
  --exclude-category "sd|kids|cinema|movies|music|documentary"
```

### Exclude SD categories and SD channels

```bash
python main.py --m3u --full \
  --category sport \
  --exclude-category sd \
  --exclude-channel sd
```

### Disable EPG header

```bash
python main.py --m3u --full \
  --category sport \
  --no-epg
```

### Use a clean single EPG header

```bash
python main.py --m3u --full \
  --category sport \
  --epg-header-mode single
```

### Use compatibility EPG header

This is the default, but you can set it explicitly:

```bash
python main.py --m3u --full \
  --category sport \
  --epg-header-mode compat
```

### Use only a custom EPG URL

```bash
python main.py --m3u --full \
  --category sport \
  --no-auto-epg \
  --epg-url "https://example.com/epg.xml"
```

### Use automatic EPG plus a custom EPG URL

```bash
python main.py --m3u --full \
  --category sport \
  --epg-url "https://example.com/extra-epg.xml"
```

### Include backup EPG URLs

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://mirror-domain.com" \
  --include-backups \
  --backup-epg
```

### Mirror backup domain

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://mirror-domain.com" \
  --include-backups \
  --backup-match auto \
  --dedupe url
```

### Different provider as backup alternatives by name

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider" \
  --include-backups \
  --backup-match auto \
  --dedupe url
```

### Different provider as extra merged channels

```bash
python main.py --m3u --full \
  --category "sport|football|news" \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider|merge" \
  --include-backups \
  --backup-match auto \
  --dedupe url \
  --output output/merged
```

### Mixed mirror + merge backups

```bash
python main.py --m3u --full \
  --category "sport|football|world cup|ireland|now tv sport|news|general|tnt" \
  --exclude-category "sd|max|flo|bally|sky sport+" \
  --exclude-channel sd \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider|merge" \
  --backup-server "http://mirror-domain.com" \
  --include-backups \
  --backup-match auto \
  --backup-mode suffix \
  --dedupe url \
  --output output/custom
```

### Same display names for backups

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://mirror-domain.com" \
  --include-backups \
  --backup-mode duplicate \
  --dedupe url
```

### Add backup suffixes

This is the default:

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://mirror-domain.com" \
  --include-backups \
  --backup-mode suffix
```

Example display names:

```text
Sky Sports Main Event
Sky Sports Main Event [Backup 1]
```

### Search all backup categories

Use this when backup category names do not match the primary provider's category names.

```bash
python main.py --m3u --full \
  --category "sport|football|news" \
  --channel "sky sports|tnt|dazn|espn" \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider|merge" \
  --include-backups \
  --backup-search-all \
  --dedupe url
```

Use `--backup-search-all` carefully. Without `--channel`, it may add too many backup channels.

### Skip backup validation

```bash
python main.py --m3u --full \
  --category sport \
  --backup-server "http://other-provider.com:80|user|pass|Other Provider|merge" \
  --include-backups \
  --no-validate-backups
```

### Prompt for backup providers

```bash
python main.py --m3u --full \
  --category sport \
  --ask-backups \
  --include-backups
```

### Dedupe by URL

Best when you want the same channel name from multiple providers but do not want identical URLs repeated.

```bash
python main.py --m3u --full \
  --category sport \
  --include-backups \
  --dedupe url
```

### Dedupe by name

Keeps only one entry per channel name.

```bash
python main.py --m3u --full \
  --category sport \
  --dedupe name
```

### No dedupe

Useful for testing.

```bash
python main.py --m3u --full \
  --category sport \
  --include-backups \
  --dedupe none
```

### Export VOD M3U

```bash
python main.py --m3u --vod \
  --category "movies|cinema|action|comedy" \
  --exclude-category "kids|xxx" \
  --output output/custom
```

### Export VOD TXT

```bash
python main.py --txt --vod \
  --category "movies|cinema|action" \
  --output output/custom
```

### Export series M3U

```bash
python main.py --m3u --series \
  --category "series|netflix|prime|apple|hbo" \
  --exclude-category "kids|xxx" \
  --output output/custom
```

### Export live + VOD + series

```bash
python main.py --m3u --live --vod --series \
  --category "sport|football|news|movies|series|netflix|prime" \
  --exclude-category "sd|kids|xxx" \
  --exclude-channel sd \
  --output output/all_media
```

## Argument combination guide

### Media type combinations

| Command flags | Result |
|---|---|
| no media flag | Live TV only. Same as `--live`. |
| `--live` | Live TV only. |
| `--vod` | VOD only. |
| `--series` | Series only. |
| `--live --vod` | Live TV and VOD. |
| `--live --series` | Live TV and series. |
| `--vod --series` | VOD and series. |
| `--live --vod --series` | All supported media types. |

### Output format combinations

| Command flags | Result |
|---|---|
| no output flag | TXT only. Same as `--txt`. |
| `--txt` | TXT only. |
| `--m3u` | M3U only. |
| `--txt --m3u` | TXT and M3U. |

### Live layout combinations

| Command flags | Result |
|---|---|
| `--live --m3u --full` | `output/all_live.m3u` or `<output>/all_live.m3u`. |
| `--live --txt --full` | `output/all_live.txt` or `<output>/all_live.txt`. |
| `--live --m3u` without `--full` | Per-category M3U files under `<output>/m3u/`. |
| `--live --txt` without `--full` | Per-category TXT files under `<output>/txt/`. |

### Filter combinations

| Combination | Meaning |
|---|---|
| `--category X` | Only categories matching `X`. |
| `--exclude-category X` | All categories except ones matching `X`. |
| `--category X --exclude-category Y` | Include categories matching `X`, then remove categories matching `Y`. |
| `--channel X` | Only streams whose names match `X`. |
| `--exclude-channel X` | Remove streams whose names match `X`. |
| `--category X --channel Y` | Category must match `X`, and channel name must match `Y`. |
| `--exclude-category sd --exclude-channel sd` | Remove SD categories and SD channels. |

### EPG combinations

| Combination | Meaning |
|---|---|
| `--m3u` | Auto EPG is added by default for live M3U. |
| `--m3u --no-epg` | No EPG header. |
| `--m3u --no-auto-epg --epg-url URL` | Only custom EPG URL. |
| `--m3u --epg-url URL` | Primary auto EPG plus custom URL. |
| `--m3u --backup-epg` | Primary auto EPG plus backup EPG URLs. |
| `--epg-header-mode single` | Only `x-tvg-url`. |
| `--epg-header-mode compat` | `x-tvg-url`, `url-tvg`, and `tvg-url`. |

### Backup combinations

| Combination | Meaning |
|---|---|
| `--backup-server ...` without `--include-backups` | Backup is parsed/validated but backup channels are not added. |
| `--backup-server ... --include-backups` | Add backup channels according to backup mode. |
| server-only backup + `--backup-match auto` | Mirror mode. |
| explicit username/password backup + `--backup-match auto` | Name-match mode. |
| any backup + `--backup-match mirror` | Force mirror mode globally. |
| any backup + `--backup-match name` | Force name-match mode globally. |
| any backup + `--backup-match merge` | Force merge mode globally. |
| backup string with 5th field `|mirror` | Force mirror for that backup only. |
| backup string with 5th field `|name` | Force name-match for that backup only. |
| backup string with 5th field `|merge` | Force merge for that backup only. |
| `--backup-mode suffix` | Add `[Backup Name]` to backup display names. |
| `--backup-mode duplicate` | Keep backup display names identical to original. |
| `--backup-search-all` | For name/merge backups, do not require backup category names to match the primary filters. |

## Checking output

List output files:

```bash
ls -lh output/custom
```

Open output folder on macOS:

```bash
open output/custom
```

Check M3U header:

```bash
head -1 output/custom/all_live.m3u
```

Count total channels:

```bash
grep -c '^#EXTINF' output/custom/all_live.m3u
```

Count backup entries by label:

```bash
grep -c '\[Backup 1\]' output/custom/all_live.m3u
```

Check for SD entries:

```bash
grep -i '^#EXTINF.*sd' output/custom/all_live.m3u | head -20
```

Check a backup provider URL appears:

```bash
grep -c 'other-provider.com' output/custom/all_live.m3u
```

Preview first channels:

```bash
head -40 output/custom/all_live.m3u
```

## Troubleshooting

### I expected an M3U but only got TXT

You probably did not pass `--m3u`.

```bash
python main.py --m3u --full --category sport
```

### I expected VOD/series but only got live

If no media type is provided, the script defaults to live. Add `--vod` or `--series`.

```bash
python main.py --m3u --vod --category movies
python main.py --m3u --series --category series
```

### Backup provider adds nothing

For a separate provider, try merge mode:

```bash
--backup-server "http://other-provider.com:80|user|pass|Other Provider|merge"
```

If category names are different, add:

```bash
--backup-search-all
```

For safer results with `--backup-search-all`, also add a channel filter:

```bash
--channel "sky sports|tnt|dazn|espn"
```

### Backup provider URLs are wrong

Do not use mirror mode for a different provider unless stream IDs match. Use name or merge mode.

```bash
--backup-match name
```

or:

```bash
--backup-match merge
```

### EPG header is missing

Make sure you used `--m3u` and did not use `--no-epg`.

```bash
head -1 output/custom/all_live.m3u
```

### EPG works in one player but not another

Try compatibility mode:

```bash
--epg-header-mode compat
```

Or try single mode:

```bash
--epg-header-mode single
```

### Too many backup channels were added

Avoid `--backup-search-all`, or add stricter filters:

```bash
--category "sport|football|news" --channel "sky sports|tnt|dazn|espn"
```

### SD channels still appear

Use both category and channel excludes:

```bash
--exclude-category sd --exclude-channel sd
```

Then check:

```bash
grep -i '^#EXTINF.*sd' output/custom/all_live.m3u | head -20
```

### Provider times out

The script retries requests and uses separate connect/read timeouts. If a provider is very slow, re-run the command or narrow the category filter.

## Security notes

- Do not share commands or logs containing real IPTV usernames/passwords.
- The script masks EPG credentials in terminal logs, but stream URLs inside M3U files necessarily contain credentials.
- Keep generated playlists private.
- Add `.env` and `output/` to `.gitignore`.

## Recommended command for mixed-provider live playlist

This is the polished setup for one primary provider, one separate backup provider that should add more channels, and one mirror domain:

```bash
python main.py --m3u --full \
  --category "sport|football|world cup|ireland|^IE\||now tv sport|news|general|tnt" \
  --exclude-category "sd|max|flo|bally|sky sport+" \
  --exclude-channel sd \
  --backup-server "http://other-provider.com:80|USER|PASS|Other Provider|merge" \
  --backup-server "http://mirror-domain.com" \
  --include-backups \
  --backup-match auto \
  --backup-mode suffix \
  --dedupe url \
  --epg-header-mode compat \
  --output output/custom
```



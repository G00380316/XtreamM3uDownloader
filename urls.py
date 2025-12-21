import requests

SERVER = ""
USERNAME = ""
PASSWORD = ""

LIVE_TYPE = "live"
VOD_TYPE = "vod"
SERIES_TYPE = "series"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/44.0.2403.89 Safari/537.36"
    )
}


def categories(streamType):
    if streamType == LIVE_TYPE:
        url = f"{SERVER}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_live_categories"
    else:
        return None

    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def streams_by_category(streamType, category_id):
    if streamType == LIVE_TYPE:
        url = f"{SERVER}/player_api.php?username={USERNAME}&password={PASSWORD}&action=get_live_streams&category_id={category_id}"
    else:
        return None

    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def build_stream_url(stream_id, stream_type, container_extension="ts"):
    return f"{SERVER}/live/{USERNAME}/{PASSWORD}/{stream_id}.{container_extension}"

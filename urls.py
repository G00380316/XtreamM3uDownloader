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
        action = "get_live_categories"
    elif streamType == VOD_TYPE:
        action = "get_vod_categories"
    elif streamType == SERIES_TYPE:
        action = "get_series_categories"
    else:
        return None

    url = f"{SERVER}/player_api.php?username={USERNAME}&password={PASSWORD}&action={action}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def streams_by_category(streamType, category_id):
    if streamType == LIVE_TYPE:
        action = "get_live_streams"
    elif streamType == VOD_TYPE:
        action = "get_vod_streams"
    elif streamType == SERIES_TYPE:
        action = "get_series"
    else:
        return None

    url = (
        f"{SERVER}/player_api.php?"
        f"username={USERNAME}&password={PASSWORD}"
        f"&action={action}&category_id={category_id}"
    )

    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def series_info_by_id(series_id):
    url = (
        f"{SERVER}/player_api.php?"
        f"username={USERNAME}&password={PASSWORD}"
        f"&action=get_series_info&series_id={series_id}"
    )

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"Xtream API Series Info Fetch Error for ID {series_id}: {e}")
        return None


def build_stream_url(stream_id, stream_type, container_extension="ts"):
    if stream_type == LIVE_TYPE:
        path = "live"
    elif stream_type == VOD_TYPE:
        path = "movie"
    elif stream_type == SERIES_TYPE:
        path = "series"
    else:
        return None

    return f"{SERVER}/{path}/{USERNAME}/{PASSWORD}/{stream_id}.{container_extension}"

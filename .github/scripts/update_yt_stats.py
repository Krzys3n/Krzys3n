import json
import os
import re
import urllib.parse
import urllib.request


def main() -> None:
    channel_id = os.environ["CHANNEL_ID"]
    api_key = os.environ["API_KEY"]

    url = (
        "https://www.googleapis.com/youtube/v3/channels"
        f"?part=statistics&id={urllib.parse.quote(channel_id)}"
        f"&key={urllib.parse.quote(api_key)}"
    )

    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"Brak kanału lub błąd API: {data}")

    stats = items[0]["statistics"]
    subs = f"{int(stats['subscriberCount']):,}".replace(",", " ")
    views = f"{int(stats['viewCount']):,}".replace(",", " ")

    subs_encoded = urllib.parse.quote(subs)
    views_encoded = urllib.parse.quote(views)
    yt_link = f"https://www.youtube.com/channel/{channel_id}"

    block = (
        "<!-- YT_STATS_START -->\n"
        f"[![Subscribers](https://img.shields.io/badge/Subscribers-{subs_encoded}-red?style=for-the-badge&logo=youtube)]({yt_link}) "
        f"[![Views](https://img.shields.io/badge/Views-{views_encoded}-blue?style=for-the-badge&logo=youtube)]({yt_link})\n"
        "<!-- YT_STATS_END -->"
    )

    with open("README.md", "r", encoding="utf-8") as f:
        readme = f.read()

    pattern = r"<!-- YT_STATS_START -->.*?<!-- YT_STATS_END -->"
    if re.search(pattern, readme, flags=re.S):
        new_readme = re.sub(pattern, block, readme, flags=re.S)
    else:
        new_readme = readme.rstrip() + "\n\n" + block + "\n"

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(new_readme)


if __name__ == "__main__":
    main()

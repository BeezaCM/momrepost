import json
import os
import re
import subprocess
import sys
import time

import feedparser
import requests

API = "https://api.upload-post.com/api"
KEY = os.environ["UPLOADPOST_API_KEY"]
USER = os.environ["UPLOADPOST_USER"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
PLATFORMS = [p.strip() for p in os.environ.get("PLATFORMS", "tiktok,instagram").split(",") if p.strip()]
DISCORD = os.environ.get("DISCORD_WEBHOOK", "").strip()
DEBUG = os.environ.get("DEBUG") == "1"   # set DEBUG=1 to print raw API responses (public repo logs are visible!)
MAX_PER_RUN = 3
SEEN_FILE = "seen.json"
HEADERS = {"Authorization": f"Apikey {KEY}"}

# Used to label links found in Upload-Post's responses.
PLATFORM_DOMAINS = {
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "linkedin.com": "LinkedIn",
    "x.com": "X",
    "twitter.com": "X",
    "threads.net": "Threads",
    "threads.com": "Threads",
    "pinterest.com": "Pinterest",
    "bsky.app": "Bluesky",
}


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return None
    with open(SEEN_FILE) as f:
        return set(json.load(f))


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=1)


def find_urls(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, dict):
        for v in obj.values():
            find_urls(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_urls(v, out)
    elif isinstance(obj, str) and obj.startswith("http"):
        out.append(obj)
    return out


def label_for(url):
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()
    for domain, name in PLATFORM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def links_from(payload):
    links = {}
    for url in find_urls(payload):
        name = label_for(url)
        if name and name not in links:
            links[name] = url
    return links


def safe_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {}


def download(url):
    if os.path.exists("video.mp4"):
        os.remove("video.mp4")
    subprocess.run(
        [
            "yt-dlp", "--no-playlist",
            "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
            "--merge-output-format", "mp4",
            "-o", "video.mp4", url,
        ],
        check=True,
    )


def upload(title, description):
    data = [("user", USER), ("title", title), ("description", description)]
    data += [("platform[]", p) for p in PLATFORMS]
    with open("video.mp4", "rb") as f:
        resp = requests.post(f"{API}/upload", headers=HEADERS, data=data,
                             files={"video": f}, timeout=900)
    payload = safe_json(resp)
    if DEBUG:
        print("upload response:", json.dumps(payload)[:2000])
    return resp, payload


def poll_status(request_id, tries=12, delay=15):
    last = {}
    for _ in range(tries):
        time.sleep(delay)
        resp = requests.get(f"{API}/uploadposts/status", headers=HEADERS,
                            params={"request_id": request_id}, timeout=60)
        last = safe_json(resp)
        if DEBUG:
            print("status response:", json.dumps(last)[:2000])
        if str(last.get("status", "")).lower() == "completed":
            break
    return last


def announce(title, yt_url, thumb, links):
    if not DISCORD:
        return
    lines = [f"[YouTube]({yt_url})"] + [f"[{name}]({url})" for name, url in links.items()]
    embed = {
        "title": title[:256],
        "url": yt_url,
        "description": "\n".join(lines)[:4000],
        "color": 5793266,
    }
    if thumb:
        embed["image"] = {"url": thumb}
    resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=30)
    print("discord announce:", resp.status_code)


def main():
    feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}")
    if not feed.entries:
        print("No entries in feed - check CHANNEL_ID.")
        return

    seen = load_seen()
    if seen is None:
        # First run: remember what already exists so the back catalog is NOT reposted.
        save_seen({e.yt_videoid for e in feed.entries})
        print(f"First run: marked {len(feed.entries)} existing videos as seen. Nothing posted.")
        return

    new = [e for e in reversed(feed.entries) if e.yt_videoid not in seen][:MAX_PER_RUN]
    if not new:
        print("Nothing new.")
        return

    for e in new:
        vid = e.yt_videoid
        print("New video:", vid)
        try:
            download(e.link)
            resp, payload = upload(e.title, e.get("summary", ""))
            print("upload status code:", resp.status_code)
            if not resp.ok:
                print("Upload failed; will retry next run.")
                continue

            seen.add(vid)          # mark as done as soon as the upload was accepted
            save_seen(seen)

            links = links_from(payload)
            request_id = payload.get("request_id") if isinstance(payload, dict) else None
            if not links and request_id:
                links = links_from(poll_status(request_id))

            thumb = None
            try:
                thumb = e.media_thumbnail[0]["url"]
            except (AttributeError, IndexError, KeyError):
                pass
            announce(e.title, e.link, thumb, links)
        except Exception as exc:  # keep going with the next video
            print("Error on", vid, "-", type(exc).__name__, exc)
        finally:
            if os.path.exists("video.mp4"):
                os.remove("video.mp4")


if __name__ == "__main__":
    sys.exit(main())

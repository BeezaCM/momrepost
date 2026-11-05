import json
import os
import random
import re
import subprocess
import sys
import time

import feedparser
import requests

API = "https://api.upload-post.com/api"
DEBUG = os.environ.get("DEBUG") == "1"   # DEBUG=1 prints raw API responses (public repo logs are visible!)
MAX_PER_RUN = 3                          # per account, per run
SEEN_FILE = "seen.json"
BACKLOG_FILE = "backlog.json"            # per account: queued back-catalog videos + times they were posted
ACCOUNTS_FILE = "accounts.json"
BACKLOG_PER_DAY = 2                      # default pace for backlog videos
MAX_TRIES = 3                            # failed attempts before a video is skipped for good
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SHORT_MAX_SECONDS = 180                  # a Short is vertical/square and at most 3 minutes long
TYPE_LABELS = {"shorts": "Short", "long": "regular (non-Short) video"}
YTDLP = [sys.executable, "-m", "yt_dlp"]  # works wherever the package is installed, no PATH needed

# GitHub passes every repo secret in as one JSON blob; on a home computer, plain env vars work too.
try:
    SECRETS = json.loads(os.environ.get("SECRETS_JSON") or "{}")
except ValueError:
    SECRETS = {}

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


def secret(name):
    if not name:
        return ""
    return (SECRETS.get(name) or os.environ.get(name) or "").strip()


def plist(value):
    if isinstance(value, str):
        value = value.split(",")
    return [p.strip() for p in (value or []) if p and p.strip()]


def field(acc, key):
    """A value can be written literally in accounts.json or point to a secret via '<key>_secret'."""
    if acc.get(key):
        return str(acc[key]).strip()
    return secret(acc.get(key + "_secret"))


def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE) as f:
            return json.load(f)["accounts"]
    # Fallback: single account from plain environment variables (old layout).
    return [{
        "name": "default",
        "channel_id_secret": "CHANNEL_ID",
        "profile_secret": "UPLOADPOST_USER",
        "api_key_secret": "UPLOADPOST_API_KEY",
        "discord_secret": "DISCORD_WEBHOOK",
        "platforms": os.environ.get("PLATFORMS", "tiktok,instagram"),
    }]


def load_seen(accounts):
    if not os.path.exists(SEEN_FILE):
        return {}
    with open(SEEN_FILE) as f:
        data = json.load(f)
    if isinstance(data, list):               # old single-account format -> first account
        return {accounts[0]["name"]: sorted(data)}
    return data


def save_seen(seen_all):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen_all, f, indent=1, sort_keys=True)


def load_backlog():
    if not os.path.exists(BACKLOG_FILE):
        return {}
    try:
        with open(BACKLOG_FILE) as f:
            return json.load(f)
    except ValueError:
        return {}


def save_backlog(backlog_all):
    with open(BACKLOG_FILE, "w") as f:
        json.dump(backlog_all, f, indent=1, sort_keys=True)


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
            *YTDLP, "--no-playlist", "--no-progress",
            "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
            "--merge-output-format", "mp4",
            "-o", "video.mp4", url,
        ],
        check=True,
    )


def load_comments(acc):
    """Lines of the account's comments file (one comment per line; blanks and #lines ignored)."""
    path = acc.get("comments_file")
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = [line.strip() for line in f.read().splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def log_problems(payload):
    """Show warnings and per-platform failures Upload-Post reports, so they're visible in the run log."""
    if not isinstance(payload, dict):
        return
    for w in payload.get("warnings") or []:
        print(f"  warning: {str(w)[:300]}")
    results = payload.get("results")
    if isinstance(results, dict):
        for plat, res in results.items():
            if not isinstance(res, dict):
                continue
            if res.get("skipped"):
                print(f"  {plat} skipped: {res.get('skip_reason') or res.get('error')}")
            elif res.get("success") is False:
                print(f"  {plat} FAILED: {str(res.get('error', ''))[:300]}")
            for w in res.get("warnings") or []:
                print(f"  {plat} warning: {str(w)[:300]}")


def upload(api_key, profile, platforms, title, description, comment=""):
    data = [("user", profile), ("title", title), ("description", description)]
    if comment:
        data.append(("first_comment", comment))
    data += [("platform[]", p) for p in platforms]
    with open("video.mp4", "rb") as f:
        resp = requests.post(f"{API}/upload", headers={"Authorization": f"Apikey {api_key}"},
                             data=data, files={"video": f}, timeout=900)
    payload = safe_json(resp)
    if DEBUG:
        print("upload response:", json.dumps(payload)[:2000])
    return resp, payload


def poll_status(api_key, request_id, tries=12, delay=15):
    last = {}
    for _ in range(tries):
        time.sleep(delay)
        resp = requests.get(f"{API}/uploadposts/status",
                            headers={"Authorization": f"Apikey {api_key}"},
                            params={"request_id": request_id}, timeout=60)
        last = safe_json(resp)
        if DEBUG:
            print("status response:", json.dumps(last)[:2000])
        if str(last.get("status", "")).lower() == "completed":
            break
    return last


def announce(webhook, title, yt_url, thumb, links):
    if not webhook:
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
    resp = requests.post(webhook, json={"embeds": [embed]}, timeout=30)
    print("  discord announce:", resp.status_code)


class Entry(dict):
    """Minimal stand-in for a feedparser entry (attribute access), used by the yt-dlp fallback."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def ytdlp_entries(channel):
    """Fallback: list the channel's latest uploads with yt-dlp (no descriptions in this mode)."""
    playlist = "https://www.youtube.com/playlist?list=UU" + channel[2:]
    try:
        out = subprocess.run([*YTDLP, "--flat-playlist", "--playlist-end", "15", "--dump-single-json", playlist],
                             check=True, capture_output=True, text=True, timeout=180).stdout
        items = json.loads(out).get("entries") or []
    except Exception as exc:
        detail = (getattr(exc, "stderr", "") or "").strip().splitlines()
        print(f"  yt-dlp fallback failed: {type(exc).__name__} {detail[-1] if detail else exc}")
        return []
    entries = []
    for item in items:
        vid = item.get("id")
        if vid and item.get("title"):
            entries.append(Entry(yt_videoid=vid, link=f"https://www.youtube.com/watch?v={vid}",
                                 title=item["title"], summary=""))
    if entries:
        print(f"  got {len(entries)} videos from yt-dlp instead of the RSS feed.")
    return entries


def fetch_entries(channel):
    """Latest videos of a channel, newest first: RSS feed (3 tries), then yt-dlp. [] if both fail."""
    for attempt in range(3):
        try:
            resp = requests.get(FEED_URL.format(channel), headers={"User-Agent": BROWSER_UA}, timeout=30)
            if resp.ok:
                entries = feedparser.parse(resp.content).entries
                if entries:
                    return entries
                print("  the feed answered but listed no videos.")
            else:
                print(f"  the feed request failed: HTTP {resp.status_code}")
        except Exception as exc:
            print(f"  the feed request failed: {type(exc).__name__} {exc}")
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    print("  RSS feed unavailable; trying yt-dlp...")
    return ytdlp_entries(channel)


def entry_info(e):
    thumb = None
    try:
        thumb = e.media_thumbnail[0]["url"]
    except (AttributeError, IndexError, KeyError):
        pass
    return {"id": e.yt_videoid, "link": e.link, "title": e.title,
            "summary": e.get("summary", ""), "thumb": thumb}


def normalize_types(value):
    v = str(value or "both").strip().lower()
    if v in ("short", "shorts"):
        return "shorts"
    if v in ("long", "longs", "full", "fullscreen", "regular", "video", "videos"):
        return "long"
    return "both"


def video_kind(url):
    """'shorts' or 'long', judged from yt-dlp metadata (length + shape). None if it can't be read."""
    try:
        out = subprocess.run([*YTDLP, "--no-playlist", "--skip-download", "--dump-single-json", url],
                             check=True, capture_output=True, text=True, timeout=180).stdout
        meta = json.loads(out)
    except Exception as exc:
        detail = (getattr(exc, "stderr", "") or "").strip().splitlines()
        print(f"  couldn't read video info: {type(exc).__name__} {detail[-1] if detail else exc}")
        return None
    duration = meta.get("duration") or 0
    width, height = meta.get("width"), meta.get("height")
    vertical = (height >= width) if (width and height) else True    # shape unknown -> go by length alone
    if DEBUG:
        print(f"  video info: duration={duration} size={width}x{height}")
    return "shorts" if (vertical and 0 < duration <= SHORT_MAX_SECONDS) else "long"


def triage(types, url):
    """'post', 'skip' (doesn't match this account's types) or 'error' (couldn't tell)."""
    if types == "both":
        return "post"
    kind = video_kind(url)
    if kind is None:
        return "error"
    if kind == types:
        return "post"
    print(f"  skipping: it's a {TYPE_LABELS[kind]}, and this account only posts {types}.")
    return "skip"


def post_video(creds, info, on_accepted):
    """Download + upload one video. True = Upload-Post accepted it, False = failed (counts as a try),
    None = the API key was rejected (401/403): nothing is wrong with the video, so it doesn't count."""
    api_key, profile, platforms, webhook, comments = creds
    vid = info["id"]
    accepted = False
    try:
        comment = random.choice(comments) if comments else ""
        download(info["link"])
        resp, payload = upload(api_key, profile, platforms, info["title"], info["summary"], comment)
        print(f"  upload status code: {resp.status_code}")
        if resp.status_code in (401, 403):
            print(f"  upload rejected: Upload-Post says the API key isn't valid (HTTP {resp.status_code}).")
            print("  Fix it: run setup_repo.py -> Edit an account -> Upload-Post API key. "
                  "This does NOT count as a failed try for the video.")
            return None
        if not resp.ok:
            print("  upload failed. Upload-Post said: " + (resp.text or "").strip()[:600])
            return False
        accepted = True
        on_accepted()                           # mark done as soon as the upload was accepted
        if comment:
            print(f"  first comment: {comment[:80]}")
        log_problems(payload)

        links = links_from(payload)
        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        if not links and request_id:
            links = links_from(poll_status(api_key, request_id))
        announce(webhook, info["title"], info["link"], info.get("thumb"), links)
    except Exception as exc:                    # keep going with the next video
        print(f"  error on {vid}: {type(exc).__name__} {exc}")
    finally:
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")
    return accepted


def backlog_due(state, per_day, now):
    """True when a backlog video may go out: fewer than per_day in the last 24h, spaced evenly."""
    state["posted"] = [t for t in state.get("posted", []) if now - t < 86400]
    if not state.get("queue") or len(state["posted"]) >= per_day:
        return False
    min_gap = 86400 / per_day * 0.9             # 2/day -> at least ~10.8h apart
    return not state["posted"] or now - max(state["posted"]) >= min_gap


def backlog_next_time(posted, per_day, now):
    """Earliest time a backlog video may go out, given when earlier ones were posted."""
    window = sorted(t for t in posted if now - t < 86400)
    t = now
    if window:
        t = max(t, window[-1] + 86400 / per_day * 0.9)
        if len(window) >= per_day:
            t = max(t, window[len(window) - per_day] + 86400)
    return t


def process_account(acc, seen_all, backlog_all):
    name = acc["name"]
    channel = field(acc, "channel_id")
    profile = field(acc, "profile")
    api_key = field(acc, "api_key")
    webhook = field(acc, "discord")
    platforms = plist(acc.get("platforms"))
    types = normalize_types(acc.get("types"))
    backlog_on = bool(acc.get("backlog"))
    per_day = max(1, int(acc.get("backlog_per_day") or BACKLOG_PER_DAY))

    missing = [label for label, val in (("channel ID", channel), ("profile", profile),
                                        ("Upload-Post API key", api_key),
                                        ("platforms", platforms)) if not val]
    if missing:
        print(f"[{name}] skipped - missing: {', '.join(missing)}")
        return

    entries = fetch_entries(channel)
    if not entries and name not in seen_all:
        print(f"[{name}] couldn't get this channel's videos (see above) - check the channel ID. Skipping.")
        return

    creds = (api_key, profile, platforms, webhook, load_comments(acc))

    if name not in seen_all:
        # First time we see this account: everything in the feed (the latest ~15 videos) counts as "known".
        seen_all[name] = sorted({e.yt_videoid for e in entries})
        save_seen(seen_all)
        if backlog_on:
            # ...and is queued (oldest first) to be posted slowly, per_day at a time.
            backlog_all[name] = {"queue": [entry_info(e) for e in reversed(entries)],
                                 "posted": [], "fails": {}}
            save_backlog(backlog_all)
            print(f"[{name}] first run: queued {len(entries)} existing videos as backlog ({per_day}/day).")
        else:
            print(f"[{name}] first run: marked {len(entries)} existing videos as seen. Nothing posted.")
            return

    state = backlog_all.setdefault(name, {})
    state.setdefault("queue", [])
    state.setdefault("posted", [])
    state.setdefault("fails", {})               # video id -> number of failed attempts
    seen = set(seen_all[name])

    def mark_seen(vid):
        seen.add(vid)
        seen_all[name] = sorted(seen)
        save_seen(seen_all)
        if state["fails"].pop(vid, None) is not None:
            save_backlog(backlog_all)

    def gave_up(vid):
        """Count a failed attempt; True once the video has failed MAX_TRIES times."""
        state["fails"][vid] = state["fails"].get(vid, 0) + 1
        tries = state["fails"][vid]
        if tries >= MAX_TRIES:
            print(f"  giving up on {vid} after {tries} failed attempts - skipping it for good.")
            return True
        print(f"  attempt {tries}/{MAX_TRIES} failed; will retry next run.")
        return False

    # ---- brand-new videos: post right away -------------------------------
    if not entries:
        print(f"[{name}] couldn't read the channel's video list this run - checking only the backlog queue.")
    new = [e for e in reversed(entries) if e.yt_videoid not in seen][:MAX_PER_RUN]
    auth_failed = False
    for e in new:
        vid = e.yt_videoid
        print(f"[{name}] new video: {vid}")
        info = entry_info(e)
        verdict = triage(types, info["link"])
        if verdict == "skip":
            mark_seen(vid)
            continue
        result = post_video(creds, info, lambda v=vid: mark_seen(v)) if verdict == "post" else False
        if result:
            continue
        if result is None:                      # API key rejected: stop, don't burn the video
            auth_failed = True
            break
        if gave_up(vid):
            mark_seen(vid)
        else:
            save_backlog(backlog_all)           # remember the failed attempt

    # ---- backlog: trickle out per_day videos per rolling 24 hours --------
    handled_backlog = False
    while backlog_on and not auth_failed and backlog_due(state, per_day, time.time()):
        handled_backlog = True
        item = state["queue"][0]
        vid = item["id"]
        print(f"[{name}] backlog video: {vid} ({len(state['queue'])} left in queue)")
        verdict = triage(types, item["link"])
        if verdict == "skip":
            state["queue"].pop(0)               # doesn't use up a slot - move on to the next one
            save_backlog(backlog_all)
            continue

        def accepted():
            state["queue"].pop(0)
            state["posted"].append(time.time())
            state["fails"].pop(vid, None)

        result = post_video(creds, item, accepted) if verdict == "post" else False
        if result is None:                      # API key rejected: leave the video queued
            auth_failed = True
        elif not result:
            if gave_up(vid):
                state["queue"].pop(0)
                state["fails"].pop(vid, None)
        save_backlog(backlog_all)
        break                                   # one real attempt per run
    if not new and not handled_backlog:
        if backlog_on and state["queue"]:
            mins = max(0, int((backlog_next_time(state["posted"], per_day, time.time()) - time.time()) / 60))
            print(f"[{name}] backlog: {len(state['queue'])} queued, next one in about {mins // 60}h {mins % 60}m.")
        elif backlog_on:
            print(f"[{name}] backlog is on but nothing is queued (the queue is only filled on an account's first run).")
        else:
            print(f"[{name}] nothing new.")


def main():
    accounts = load_accounts()
    seen_all = load_seen(accounts)
    backlog_all = load_backlog()
    for acc in accounts:
        try:
            process_account(acc, seen_all, backlog_all)
        except Exception as exc:                # one account failing must not stop the others
            print(f"[{acc.get('name', '?')}] error: {type(exc).__name__} {exc}")


if __name__ == "__main__":
    sys.exit(main())

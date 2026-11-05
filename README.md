# YouTube -> Upload-Post auto-repost

Watches one or more YouTube channels and reposts their videos to TikTok, Instagram, Facebook and other
platforms through Upload-Post. It can run on GitHub Actions (free, but YouTube sometimes blocks GitHub's
servers) or on your own computer (more reliable). You pick with "Run mode" in `setup_repo.py`.

An **account** is one YouTube channel + one Upload-Post profile + a list of platforms (and optionally a
Discord webhook and a list of random comments). One repo can hold any number of accounts.

## How a run works
Every 15 minutes (30 on private GitHub repos), for each account:
1. Read the channel's latest videos (RSS feed, then yt-dlp if the feed fails).
2. Post any brand-new videos right away (up to 3 per run), after the shorts/long filter.
3. Post at most one older "backlog" video if one is due.
4. Save progress (`seen.json`, `backlog.json`) back to the repo.

## First-time setup
1. Install Python 3.8+ and git. The GitHub CLI (`gh auth login`) is strongly recommended.
2. Save `setup_repo.py` in a normal folder (not as administrator) and run `python setup_repo.py`.
3. Type a NEW repo name, then answer the questions: channel, platforms, Upload-Post profile name and API key,
   shorts / long / both, backlog yes or no, optional Discord webhook, optional comments.
4. Don't upload a video to the channel until the account's first run has finished: that run decides
   what counts as backlog.

## Changing things later
Run `python setup_repo.py` again and type the repo's name. The menu:

    1) Add a new account
    2) Edit an account (platforms, video types, backlog, profile, API key, Discord, channel, comments)
    3) Remove an account
    4) Show the backlog schedule
    5) Run mode (GitHub Actions or this computer)
    6) Send the latest post to Discord now
    7) Finish (save changes and update the code)   <- default

Changes only take effect when you choose **Finish**. Finish also refreshes `repost.py`, the workflow and
this README to the newest version, so don't hand-edit those. `accounts.json`, `comments/`, `seen.json`,
`backlog.json` are kept.

## Where it runs
**GitHub Actions** (default): secrets live in the repo's GitHub secrets. If runs fail with "Sign in to
confirm you're not a bot", YouTube is blocking GitHub's servers: switch to local mode.

**This computer** (local mode): choose "Run mode" and switch. GitHub's schedule is turned off and
`run_local.py` does the same job from Windows Task Scheduler (or cron on Mac/Linux), every 15 minutes.
- The computer must be on, awake and online. A sleeping PC just runs at its next check after waking.
- Secrets are kept in `local_secrets.json` (git-ignored: never commit it). Output goes to `local_run.log`.
- Keep the repo folder where it is: the scheduled task points at it.
- Useful commands (Windows, replace REPO with the repo name):
      schtasks /Query /TN "YouTubeRepost-REPO"             is it scheduled?
      schtasks /Change /TN "YouTubeRepost-REPO" /DISABLE   pause
      schtasks /Change /TN "YouTubeRepost-REPO" /ENABLE    resume
  Run once by hand: `python run_local.py` inside the repo folder. On Mac/Linux use `crontab -l` / `crontab -e`.
- To go back to GitHub: "Run mode", then `g`.

## Backlog
On an account's first run, the channel's latest ~15 videos (all YouTube's feed shows) are queued oldest
first. With backlog on they post 2 per rolling 24 hours (change it under Edit -> Backlog), spaced at least
~10.8 hours apart. With backlog off they are just recorded and never posted. Brand-new videos are separate:
they post right away and don't use up backlog slots. Option 4 in the menu shows the estimated times.
To re-queue an existing account: Edit -> Backlog -> yes to "Queue this channel's latest 15 videos now?".
Anything from those 15 that was already posted would be posted again.

## Posting rules
- **Shorts / long:** `types` per account. A Short is at most 3 minutes and vertical or square. Videos that
  don't match are marked as seen and never posted. To send Shorts and long videos to different platforms,
  add the same channel twice as two accounts.
- **Failures:** a video that fails 3 times is skipped for good. A rejected API key (HTTP 401/403) does NOT
  count: the run stops and the video stays queued until you fix the key.
- **Descriptions** are trimmed to 2,000 characters (Instagram and TikTok reject more than 2,200).
- **Comments:** if an account has a comments file, each post gets one random line as its first comment.
- **Partial failures** (for example one platform's expired login) are logged but not retried.
- Videos are downloaded to a temporary file and deleted; they are never committed.

## Discord
Optional webhook per account (Edit -> Discord webhook). After each post, an embed with the YouTube link and
the platform links is sent. **Menu option 6, "Send the latest post to Discord now"**, looks up the account's
latest upload on Upload-Post and sends it to Discord with all the platform links. It works for posts made
earlier too, and it can also be used to test or replace a webhook. A webhook that returns 404 was deleted
or mistyped.

## Troubleshooting
| In the log | Meaning / fix |
| --- | --- |
| `upload rejected ... API key isn't valid` (401) | Wrong Upload-Post API key. Edit -> Upload-Post API key. Nothing is lost. |
| `upload failed. Upload-Post said: ...` | Upload-Post's own reason, e.g. a description that is too long, or a platform that isn't connected to the profile. |
| `Sign in to confirm you're not a bot` | YouTube blocks GitHub's servers. Use local mode. |
| `the feed request failed: HTTP 404/500` | YouTube's feed is flaky. The script falls back to yt-dlp, so this is usually harmless. |
| `discord announce: 404` | The webhook doesn't exist any more. Replace or remove it. |
| `attempt N/3 failed` | Read the lines above it. After 3 failures the video is skipped. |
| `backlog: N queued, next one in about Xh Ym` | Normal: waiting for the next slot. |
| `backlog is on but nothing is queued` | The account had its first run before backlog was on. Re-queue it (see Backlog). |
| Scheduled runs stopped (GitHub) | GitHub pauses schedules after 60 days without repo activity. Run the workflow once. |

## Files
- `repost.py` - the script. `run_local.py` - local-mode runner. `.github/workflows/repost.yml` - the GitHub schedule (off in local mode).
- `accounts.json` - settings for every account (no secrets). It also stores the run mode.
- `seen.json` - video IDs already handled. `backlog.json` - the queue, post times and failure counts.
- `comments/<account>.txt` - optional comments, one per line (blank lines and lines starting with # are ignored).
- `local_secrets.json`, `local_run.log` - local mode only, git-ignored.

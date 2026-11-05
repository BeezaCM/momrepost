# YouTube -> Upload-Post auto-repost (multi-account)

Checks YouTube channels' RSS feeds on a schedule (GitHub Actions). For every new video
it downloads the file with yt-dlp, posts it through Upload-Post with the same
title/description, and (optionally) sends a Discord embed with links.

* `repost.py` - the script
* `accounts.json` - one entry per YouTube channel -> Upload-Post profile + platforms (no secrets in here)
* `.github/workflows/repost.yml` - the schedule
* `seen.json` - IDs of videos already handled, per account
* `comments/<account>.txt` - optional list of comments, one per line (see Notes)
* `backlog.json` - the backlog queue: older videos waiting to be posted, when the last ones went out, and
  failure counts (`seen.json` only lists videos already known, not what is scheduled)

## Adding or changing accounts
Run `setup_repo.py` again and type this repo's name. A menu lets you add, edit or remove
accounts (platforms, video types, backlog, profile, API key, Discord webhook, channel).
You can also edit `accounts.json` by hand.

## Notes
* A new account's first run looks at the channel's latest ~15 videos (all YouTube's feed exposes).
  With backlog on (`"backlog": true` in accounts.json) they are queued oldest-first and posted
  2 per rolling 24 hours (`"backlog_per_day"` changes this), spaced about 11 hours apart.
  With backlog off they are just recorded and never posted. Brand-new videos always post right away
  and don't count toward the backlog pace.
* Comments: if an account has `"comments_file"`, each post gets one random line from that file as its
  first comment (blank lines and lines starting with # are ignored). You can edit the file right on GitHub.
  Upload-Post supports this on Instagram, Facebook, Threads, Bluesky, X, YouTube, LinkedIn and TikTok
  (TikTok needs the account reconnected with comment permission). A comment that can't be posted never
  blocks the post; it shows up as a warning in the run log. X strips links from comments.
* A video (new or backlog) that fails 3 times is skipped for good: it's marked as seen and the script moves on.
* `"types"` in accounts.json picks what an account reposts: `"shorts"`, `"long"` or `"both"` (default).
  A video counts as a Short if it is at most 3 minutes long and vertical or square (checked with yt-dlp).
  Non-matching videos are marked as seen and never posted. To send Shorts to some platforms and long
  videos to others, add the same channel twice as two accounts with different platforms and types.
* Videos are downloaded to the temporary runner and deleted; they are never committed.
* YouTube sometimes blocks downloads from GitHub's servers. If runs fail with a
  "confirm you're not a bot" error, run `repost.py` from a home computer with cron instead
  (set the secrets named in accounts.json as environment variables).
* GitHub disables scheduled workflows after 60 days without repo activity.
* To debug link extraction, add `DEBUG: "1"` to the workflow's env block and read the run log.
  Do this only briefly on a public repo, since the log is public.

# YouTube -> Upload-Post auto-repost

Checks your YouTube channel's RSS feed on a schedule (GitHub Actions). For every
new video it downloads the file with yt-dlp, posts it through Upload-Post with
the same title/description, and (optionally) sends a Discord embed with links.

* `repost.py` - the script
* `.github/workflows/repost.yml` - the schedule
* `seen.json` - IDs of videos already handled (created on the first run)

## Notes
* The first run only records existing videos; it does not repost your back catalog.
* Videos are downloaded to the temporary runner and deleted; they are never committed.
* YouTube sometimes blocks downloads from GitHub's servers. If runs fail with a
  "confirm you're not a bot" error, run `repost.py` from a home computer with cron instead
  (set the same values as environment variables).
* GitHub disables scheduled workflows after 60 days without repo activity.
* To debug link extraction, set `DEBUG: "1"` in the workflow's env block and read the run log.
  Do this only briefly on a public repo, since the log is public.

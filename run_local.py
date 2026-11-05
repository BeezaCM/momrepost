# run_local.py - runs repost.py from THIS computer instead of GitHub Actions.
#
# Each run: pull the latest state (if the repo has a remote), run repost.py, then commit and push
# seen.json / backlog.json. Output is also appended to local_run.log.
# Secrets are read from local_secrets.json, which is git-ignored and must never be committed.
import json
import os
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
LOG = "local_run.log"
LOCK = ".local_run.lock"
SECRETS_FILE = "local_secrets.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Tee:
    # Sends everything printed to the console (if there is one) and to the log file.
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, text):
        for s in self.streams:
            try:
                s.write(text)
                s.flush()
            except Exception:
                pass

    def flush(self):
        pass


def open_log():
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 1000000:     # keep the log small
            with open(LOG, "rb") as f:
                f.seek(-200000, os.SEEK_END)
                tail = f.read()
            with open(LOG, "wb") as f:
                f.write(tail)
    except OSError:
        pass
    return open(LOG, "a", encoding="utf-8", errors="replace")


def git(*args):
    return subprocess.run(["git", "-c", "user.name=repost-bot",
                           "-c", "user.email=repost-bot@users.noreply.github.com", *args],
                          capture_output=True, text=True, creationflags=NO_WINDOW)


def run_once():
    try:
        with open(SECRETS_FILE, encoding="utf-8") as f:
            secrets = json.load(f)
    except (OSError, ValueError):
        print(SECRETS_FILE + " is missing or unreadable - run setup_repo.py again and keep the local run mode.")
        return 1
    env = dict(os.environ, SECRETS_JSON=json.dumps(secrets), PYTHONIOENCODING="utf-8")

    has_remote = bool(git("remote").stdout.strip())
    if has_remote:
        res = git("pull", "--rebase")
        if res.returncode != 0:
            git("rebase", "--abort")
            print("git pull failed (carrying on anyway): " + (res.stderr or res.stdout).strip()[:300])

    proc = subprocess.Popen([sys.executable, "repost.py"], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=NO_WINDOW)
    for line in proc.stdout:
        print(line, end="")
    code = proc.wait()

    files = [f for f in ("seen.json", "backlog.json") if os.path.exists(f)]
    if files:
        git("add", *files)
        if git("commit", "-m", "update state").returncode == 0 and has_remote:
            res = git("push", "origin", "HEAD")
            if res.returncode != 0:
                res = git("pull", "--rebase")
                if res.returncode == 0:
                    res = git("push", "origin", "HEAD")
                else:
                    git("rebase", "--abort")
            print("state saved to GitHub." if res.returncode == 0 else
                  "couldn't push the state: " + (res.stderr or res.stdout).strip()[:300])
    return code


def main():
    sys.stdout = Tee(sys.__stdout__, open_log())
    sys.stderr = sys.stdout
    print("\n===== " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " local run =====")
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 2 * 3600:
        print("another run is still going (lock file found) - skipping this one.")
        return 0
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))
    try:
        return run_once()
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())

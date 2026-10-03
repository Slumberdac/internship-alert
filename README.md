# Stage Alert Async

[![Docker Image CI](https://github.com/Slumberdac/internship-alert/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Slumberdac/internship-alert/actions/workflows/docker-image.yml)

## Overview

**Stage Alert Async** is an automated job-application assistant for the ÉTS job board.
It asynchronously monitors new postings, analyzes them against a candidate's CV using OpenAI GPT, and sends results to Discord, all fully containerized for reliable 24/7 operation.

---

## Features

- **Asynchronous job fetching**: non-blocking concurrent network operations.
- **Discord integration**: posts alerts and summaries directly in a chosen channel.
- **GPT integration**: evaluates job/CV match quality.
- **Cookie & session management**: logs back in through Microsoft when the session expires and keeps every cookie the board sets.
- **Chromium automation**: handles the Microsoft sign-in in headless mode, including backing out of passkey prompts it can't answer.
- **2FA with automatic fallback**: YubiKey through a shared host `pcscd`, a host code generator over a unix socket, or an `rsc.io/2fa` keychain. Whichever is available gets used, no configuration needed.
- **Failure snapshots**: a screenshot and the page HTML are saved whenever a login fails, capped so they can't fill the disk.
- **Docker-based isolation**: consistent runtime across Linux hosts and Raspberry Pi.

---

## Project Structure

```
stage_alert
├── app.py
├── request.py
├── Pipfile
├── Pipfile.lock
├── Dockerfile
├── docker/
│   └── entrypoint.sh
├── compose.yaml
├── .env.example
└── README.md
```

---

## How the login works

When a request to the board gets redirected (HTTP 302), the session has expired and `refresh_cookie()` signs in again with Chromium:

1. Microsoft sign-in page: enters `EMAIL`.
2. ÉTS sign-in page: enters `PASSWORD`.
3. Microsoft MFA: walks whatever screens Microsoft shows until it reaches the code field, then enters a TOTP code from one of the 2FA sources below. If Microsoft opens on the passkey prompt ("Face, fingerprint, PIN or security key"), the bot waits a few seconds and clicks the back arrow to reach the other methods.
4. Back on `see.etsmtl.ca`: all of the board's cookies (`GASP2.WebEtudiant.Auth`, `ASP.NET_SessionId` and a load-balancer cookie) are stored and reused for every request.

Microsoft decides which MFA screen comes first, not the bot. See [Microsoft Authenticator notifications](#microsoft-authenticator-notifications) if your account has the Authenticator app registered.

---

## 2FA Setup

`refresh_cookie()` needs a TOTP code to get through the Microsoft login. It tries three sources in order and uses the first one that returns a valid 6 to 8 digit code:

| Order | Source      | Needs                                           | Secret lives     |
| ----- | ----------- | ----------------------------------------------- | ---------------- |
| 1     | `ykman`     | YubiKey plugged in, host `pcscd` socket mounted | On the key       |
| 2     | Unix socket | `/run/totp/totp.sock` mounted from the host     | On the host      |
| 3     | `2fa`       | `~/.2fa` keychain mounted into the container    | In the container |

A source that isn't set up is skipped silently, so you only need one. Nothing has to be configured to pick between them, and existing deployments keep working unchanged after a rebuild. If every source fails, the error message names each one and why.

Set `ACCOUNT` to the OATH label of your ÉTS account if it isn't `ets`. The same label is used for all three sources.

### Option A: YubiKey (host pcscd)

This is the setup the compose file ships with.

#### Debian / Raspberry Pi OS

```bash
sudo apt install -y pcscd libccid pcsc-tools
echo 'DAEMON_ARGS="--disable-polkit"' | sudo tee /etc/default/pcscd
sudo systemctl enable --now pcscd
sudo chmod 666 /run/pcscd/pcscd.comm   # or match group perms later
```

#### Arch Linux

```bash
sudo pacman -Syu --needed pcsclite ccid pcsc-tools
sudo systemctl edit pcscd
# Add:
# [Service]
# ExecStart=
# ExecStart=/usr/bin/pcscd --foreground --disable-polkit
sudo systemctl daemon-reload
sudo systemctl enable --now pcscd
sudo chmod 666 /run/pcscd/pcscd.comm
```

Verify:

```bash
pcsc_scan | head
```

You should see your YubiKey reader listed.

Then register the TOTP credential on the key, using the secret Microsoft shows when you add an "Authenticator app" in your account security settings:

```bash
ykman oath accounts add ets
```

The bot uses the key's OATH (TOTP) applet over PC/SC, not FIDO2. If the same key is also registered as a passkey on your account, Microsoft will open on the passkey prompt first. That's fine: the bot backs out of it automatically.

### Option B: rsc.io/2fa keychain (free, no hardware)

The `2fa` binary is built into the image. On the host, create the keychain with the TOTP secret Microsoft shows you when you set up "authenticator app":

```bash
go install rsc.io/2fa@latest
2fa -add ets        # paste the base32 secret when prompted
```

Then mount it read-only (see the compose file below). Watch out for:

- `~/.2fa` is mode 0600, so the container user must be able to read it. The image currently runs as root (`USER appuser` is commented out in the Dockerfile), which works on standard Docker but not under rootless Docker or userns-remap. If you uncomment `USER appuser`, mount the file at `/home/appuser/.2fa` and run with `--user $(id -u):$(id -g)`, or give the container its own copy owned by UID 10001.
- A read-only mount is fine for TOTP. HOTP credentials break, because `2fa` has to write the counter back after each use.
- The container can read every key in that file. If `~/.2fa` also holds personal accounts, make a dedicated keychain for the bot (`HOME=/srv/stage-alert 2fa -add ets`) and mount only that one, or use option C.

### Option C: host socket (keys never enter the container)

Keeps the secret on the host and lets the container ask for codes. Put this script at `/usr/local/bin/totp.sh`:

```sh
#!/bin/sh
read -r name
case "$name" in
  *[!a-zA-Z0-9_.-]*|"") echo "bad name" >&2; exit 1 ;;
esac
exec 2fa "$name"
```

The `case` check matters: the name comes from the container, and without it the container could pass arbitrary flags to `2fa`, such as `-add`.

Run the listener as the user who owns `~/.2fa`:

```bash
mkdir -p /run/totp
socat UNIX-LISTEN:/run/totp/totp.sock,fork,mode=660,group=docker EXEC:/usr/local/bin/totp.sh
```

Mount the socket's _directory_, not the socket file, since the listener recreates the socket on restart and a file mount would go stale. Override the path with `TOTP_SOCKET` if you put it elsewhere. A systemd socket unit is worth setting up if you want this to survive reboots.

### Microsoft Authenticator notifications

If your ÉTS account has Microsoft Authenticator registered, Microsoft always tries a push notification first, regardless of your preferred sign-in method. The bot then switches to a verification code and logs in normally, but your phone still gets an "Approve sign in?" notification each time the bot logs back in.

These requests can't be approved by accident (they require number matching), so ignoring or denying them is safe. To stop them entirely, pick one:

- Turn off notifications for the Microsoft Authenticator app in your phone's settings. Codes still work, but real sign-ins from a new device will need you to open the app to approve them.
- Remove Microsoft Authenticator from your account at https://mysignins.microsoft.com (Security info) and register a TOTP app instead via "Authenticator app" → "I want to use a different authenticator app". Microsoft can't send pushes to a TOTP-only setup.

---

## Environment Configuration

Copy the example file and fill in the required values:

```bash
cp .env.example .env
```

The file is split into three groups:

```
# ---- Required ----
EMAIL, PASSWORD, OPENAI_API_KEY, DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID
COOKIE=''                           # leave empty, the bot logs in on its first fetch

# ---- Optional features ----
CV_JSON                             # enables GPT fit analysis and the quick apply button
RANGE                               # cities you're willing to travel to, used in the fit analysis
DISCORD_ROLE_ID                     # role pinged on each new offer (role ID, not a user ID)

# ---- Optional settings (default shown) ----
DELAY=600                           # seconds between checks
POSTES_PATH=/data/postes.csv        # keep under /data in Docker so it survives rebuilds
ACCOUNT=ets                         # OATH label used by all 2FA sources
TOTP_SOCKET=/run/totp/totp.sock     # only for option C
DEBUG_DIR=/data/debug               # where failure snapshots go
```

Optional lines are commented out in `.env.example`, so uncomment only the ones you want to change. Left empty or unset, each one falls back to its default.

`COOKIE` is only a starting value. If you set it, use the full cookie string from a browser session on `see.etsmtl.ca` (`GASP2.WebEtudiant.Auth=...; ASP.NET_SessionId=...; NSC_...=...`). Old `.ASPXAUTH=...` values no longer work since the board moved to Microsoft sign-in.

`POSTES_PATH` is uncommented in the example on purpose: without it the bot writes `postes.csv` to its working directory, which in Docker is outside the volume and gets wiped on every rebuild.

You may create several `.env` files (e.g. `.env.a`, `.env.b`) for multiple parallel bots.

---

## Building the Image

```bash
docker build -t stage-alert-async .
```

---

## Running With Docker Compose (recommended)

### compose.yaml

```yaml
services:
  stage-alert:
    build: .
    image: stage-alert-async:latest
    init: true # reaps leftover Chromium processes
    shm_size: 1gb
    environment:
      - TZ=America/Toronto
      - COOKIE=${COOKIE}
      - EMAIL=${EMAIL}
      - PASSWORD=${PASSWORD}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - DISCORD_CHANNEL_ID=${DISCORD_CHANNEL_ID}
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}
      - DISCORD_ROLE_ID=${DISCORD_ROLE_ID}
      - POSTES_PATH=${POSTES_PATH:-/data/postes.csv}
      - CV_JSON=${CV_JSON}
      - RANGE=${RANGE}
      - DELAY=${DELAY}
      - ACCOUNT=${ACCOUNT}
      - TOTP_SOCKET=${TOTP_SOCKET}
      - DEBUG_DIR=${DEBUG_DIR}
    volumes:
      - data:/data # per-project named volume
      # Mount at least one 2FA source:
      - /run/pcscd:/run/pcscd # A: shared host pcscd socket (YubiKey)
      # - ${HOME}/.2fa:/root/.2fa:ro    # B: rsc.io/2fa keychain, read-only
      # - /run/totp:/run/totp           # C: host generator socket
    restart: unless-stopped
volumes:
  data: {}
```

Mounting more than one 2FA source is fine. The order in the table above decides which wins.

Every variable from `.env` must be listed under `environment` to reach the container: `--env-file` only fills in the `${...}` placeholders. Variables you leave unset arrive empty, and the bot treats empty as "use the default".

`init: true` matters on long-running hosts: without it the Python process is PID 1 and never cleans up Chromium processes that exit badly, which slowly eats memory on a Raspberry Pi. `shm_size` gives Chromium enough shared memory; Docker's 64 MB default makes it crash under load.

### Commands

```bash
# Build & start
docker compose -p internship-a --env-file .env.a up -d --build

# Another instance with different env
docker compose -p internship-b --env-file .env.b up -d

# Follow logs
docker compose -p internship-a logs -f
```

Each project name (`-p`) automatically creates its own volume
(`internship-a_data`, `internship-b_data`), so their `/data/postes.csv` files and failure snapshots are isolated.

---

## Verifying 2FA access inside a container

Pick the check that matches your setup:

```bash
# A: YubiKey through host pcscd
docker compose -p internship-a exec stage-alert ykman list
docker compose -p internship-a exec stage-alert ykman oath accounts list

# B: 2fa keychain
docker compose -p internship-a exec stage-alert 2fa ets

# C: host socket
docker compose -p internship-a exec stage-alert sh -c 'echo ets | socat - UNIX-CONNECT:/run/totp/totp.sock'
```

Any of these printing a 6-digit code means that source will work. On a successful refresh the logs print which one was used, for example `Got 2FA code from ykman`, followed by the cookie names the board returned.

---

## Local Development (optional)

Run directly on your host (no Docker) if Chromium and Chromedriver are installed:

```bash
pipenv install
pipenv run python app.py
```

`ykman` or `2fa` on your `PATH` is picked up the same way as in the container. Set `DEBUG_DIR=./debug` so snapshots land in the project folder.

To watch the login happen, comment out the `--headless=new` line in `app.py`. A physical security key plugged into your machine won't trigger Chrome's PIN dialog: the bot attaches an empty virtual authenticator, which takes the key's place.

---

## Maintenance & Updates

```bash
git pull
docker compose -p internship-a up -d --build
```

Logs:

```bash
docker compose -p internship-a logs -f stage-alert
```

To stop an instance:

```bash
docker compose -p internship-a down
```

### Failure snapshots

When a login fails, the log names the step that failed (`refresh_cookie failed at 'mfa': TimeoutException`) and the bot saves a screenshot and the page HTML to `DEBUG_DIR`. Only the 10 most recent failures are kept.

To copy them out of a running instance:

```bash
docker compose -p internship-a cp stage-alert:/data/debug ./debug
```

The HTML is the useful part when Microsoft changes its pages: it holds the element IDs and button text the bot looks for.

---

## Troubleshooting

| Symptom                                                | Likely Cause                                                                  | Fix                                                                                 |
| ------------------------------------------------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `No 2FA code available (...)`                          | No source reachable; the message names each attempt                           | Mount one of the three sources, check the per-source errors                         |
| `PC/SC not available`                                  | Missing `python3-pyscard` or unmounted `/run/pcscd`                           | Rebuild image or check volume mount                                                 |
| `No YubiKey detected`                                  | Host pcscd not running / bad socket perms                                     | Restart `pcscd`, `chmod 666 /run/pcscd/pcscd.comm`                                  |
| `ykman: ... exit status 1`                             | Wrong OATH label or locked applet                                             | Verify with `ykman oath accounts list`, set `ACCOUNT`                               |
| `2fa: open /root/.2fa: permission denied`              | Keychain unreadable by the container user                                     | See option B notes on UID and rootless Docker                                       |
| `socket: [Errno 111] Connection refused`               | Host listener not running                                                     | Restart the `socat` listener on the host                                            |
| `unexpected output '...'`                              | Source returned something that isn't a code                                   | Run the matching verify command above by hand                                       |
| `refresh_cookie failed at 'email'` or `'password'`     | Sign-in page changed or didn't load                                           | Check the snapshot in `DEBUG_DIR`                                                   |
| `refresh_cookie failed at 'mfa'`                       | Microsoft showed a screen the bot doesn't recognize, or the code was rejected | Check the snapshot; the screenshot shows where it stopped                           |
| `REQUEST FAILED: 302` right after a successful refresh | Board needs a cookie the browser didn't get                                   | Compare the logged cookie names with a working browser session                      |
| Phone gets "Approve sign in?" on every refresh         | Microsoft Authenticator push is registered                                    | See [Microsoft Authenticator notifications](#microsoft-authenticator-notifications) |
| `Permission denied: '/data/postes.csv'`                | Shared bind mount                                                             | Use named volume (default)                                                          |

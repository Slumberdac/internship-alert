# Stage Alert Async
[![Docker Image CI](https://github.com/Slumberdac/internship-alert/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Slumberdac/internship-alert/actions/workflows/docker-image.yml)

## Overview

**Stage Alert Async** is an automated job-application assistant for the ÉTS job board.
It asynchronously monitors new postings, analyzes them against a candidate's CV using OpenAI GPT, and sends results to Discord, all fully containerized for reliable 24/7 operation.

---

## Features

* **Asynchronous job fetching**: non-blocking concurrent network operations.
* **Discord integration**: posts alerts and summaries directly in a chosen channel.
* **GPT integration**: evaluates job/CV match quality.
* **Cookie & session management**: auto-refreshes job-board sessions.
* **Chromium automation**: interacts with the board in headless mode when needed.
* **2FA with automatic fallback**: YubiKey through a shared host `pcscd`, a host code generator over a unix socket, or an `rsc.io/2fa` keychain. Whichever is available gets used, no configuration needed.
* **Docker-based isolation**: consistent runtime across Linux hosts and Raspberry Pi.

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

## 2FA Setup

`refresh_cookie()` needs a TOTP code to get through the Microsoft login. It tries three sources in order and uses the first one that returns a valid 6 to 8 digit code:

| Order | Source | Needs | Secret lives |
| ----- | ------ | ----- | ------------ |
| 1 | `ykman` | YubiKey plugged in, host `pcscd` socket mounted | On the key |
| 2 | Unix socket | `/run/totp/totp.sock` mounted from the host | On the host |
| 3 | `2fa` | `~/.2fa` keychain mounted into the container | In the container |

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

Then add the YubiKey as a 2FA method in your Microsoft account security settings, and register the OATH credential on the key:

```bash
ykman oath accounts add ets
```

### Option B: rsc.io/2fa keychain (free, no hardware)

The `2fa` binary is built into the image. On the host, create the keychain with the TOTP secret Microsoft shows you when you set up "authenticator app":

```bash
go install rsc.io/2fa@latest
2fa -add ets        # paste the base32 secret when prompted
```

Then mount it read-only (see the compose file below). Watch out for:

* `~/.2fa` is mode 0600, so the container user must be able to read it. The image currently runs as root (`USER appuser` is commented out in the Dockerfile), which works on standard Docker but not under rootless Docker or userns-remap. If you uncomment `USER appuser`, mount the file at `/home/appuser/.2fa` and run with `--user $(id -u):$(id -g)`, or give the container its own copy owned by UID 10001.
* A read-only mount is fine for TOTP. HOTP credentials break, because `2fa` has to write the counter back after each use.
* The container can read every key in that file. If `~/.2fa` also holds personal accounts, make a dedicated keychain for the bot (`HOME=/srv/stage-alert 2fa -add ets`) and mount only that one, or use option C.

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

Mount the socket's *directory*, not the socket file, since the listener recreates the socket on restart and a file mount would go stale. Override the path with `TOTP_SOCKET` if you put it elsewhere. A systemd socket unit is worth setting up if you want this to survive reboots.

---

## Environment Configuration

Copy the example file and fill your credentials:

```bash
cp .env.example .env
```

Typical variables:

```
COOKIE=...
EMAIL=...
PASSWORD=...
OPENAI_API_KEY=sk-...
DISCORD_CHANNEL_ID=...
DISCORD_BOT_TOKEN=...
DISCORD_ROLE_ID=...
CV_JSON=...
POSTES_PATH=/data/postes.csv        # default
ACCOUNT=ets                         # default, OATH label used by all 2FA sources
TOTP_SOCKET=/run/totp/totp.sock     # default, only for option C
```

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
      - ACCOUNT=${ACCOUNT:-ets}
    volumes:
      - data:/data                      # per-project named volume
      # Mount at least one 2FA source:
      - /run/pcscd:/run/pcscd           # A: shared host pcscd socket (YubiKey)
      # - ${HOME}/.2fa:/root/.2fa:ro    # B: rsc.io/2fa keychain, read-only
      # - /run/totp:/run/totp           # C: host generator socket
    restart: unless-stopped
volumes:
  data: {}
```

Mounting more than one is fine. The order in the table above decides which wins.

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
(`internship-a_data`, `internship-b_data`), so their `/data/postes.csv` files are isolated.

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

Any of these printing a 6-digit code means that source will work. On a successful refresh the logs print which one was used, for example `Got 2FA code from ykman`.

---

## Local Development (optional)

Run directly on your host (no Docker) if Chromium and Chromedriver are installed:

```bash
pipenv install
pipenv run python app.py
```

`ykman` or `2fa` on your `PATH` is picked up the same way as in the container.

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

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
| ------- | ------------ | --- |
| `No 2FA code available (...)` | No source reachable; the message names each attempt | Mount one of the three sources, check the per-source errors |
| `PC/SC not available` | Missing `python3-pyscard` or unmounted `/run/pcscd` | Rebuild image or check volume mount |
| `No YubiKey detected` | Host pcscd not running / bad socket perms | Restart `pcscd`, `chmod 666 /run/pcscd/pcscd.comm` |
| `ykman: ... exit status 1` | Wrong OATH label or locked applet | Verify with `ykman oath accounts list`, set `ACCOUNT` |
| `2fa: open /root/.2fa: permission denied` | Keychain unreadable by the container user | See option B notes on UID and rootless Docker |
| `socket: [Errno 111] Connection refused` | Host listener not running | Restart the `socat` listener on the host |
| `unexpected output '...'` | Source returned something that isn't a code | Run the matching verify command above by hand |
| `Permission denied: '/data/postes.csv'` | Shared bind mount | Use named volume (default) |

---
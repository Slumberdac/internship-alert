# Stage Alert Async
[![Docker Image CI](https://github.com/Slumberdac/internship-alert/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Slumberdac/internship-alert/actions/workflows/docker-image.yml)

## Overview

**Stage Alert Async** is an automated job-application assistant for the ÉTS job board.
It asynchronously monitors new postings, analyzes them against a candidate’s CV using OpenAI GPT, and sends results to Discord — all fully containerized for reliable 24/7 operation.

---

## Features

* **Asynchronous job fetching** — non-blocking concurrent network operations.
* **Discord integration** — posts alerts and summaries directly in a chosen channel.
* **GPT integration** — evaluates job–CV match quality.
* **Cookie & session management** — auto-refreshes job-board sessions.
* **Chromium automation** — interacts with the board in headless mode when needed.
* **YubiKey 2FA support** — retrieves OATH codes through a shared host `pcscd`.
* **Docker-based isolation** — consistent runtime across Linux hosts and Raspberry Pi.

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

## Host Setup (once per machine)

### 1. Install pcscd (host YubiKey service)

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

### 2. Connect your ETS email account to your YubiKey
On your Microsoft account security settings, add your YubiKey as a 2FA method.
Make sure your new YubiKey account has an OATH label of `ETS`.

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
POSTES_PATH=/data/postes.csv   # default
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
    volumes:
      - data:/data             # per-project named volume
      - /run/pcscd:/run/pcscd  # shared host pcscd socket
    restart: unless-stopped
volumes:
  data: {}
```

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

## Verifying YubiKey access inside a container

```bash
docker compose -p internship-a exec stage-alert ykman list
docker compose -p internship-a exec stage-alert ykman oath accounts list
```

If you see your key and accounts, the pcscd link works.

---

## Local Development (optional)

Run directly on your host (no Docker) if Chromium and Chromedriver are installed:

```bash
pipenv install
pipenv run python app.py
```

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

| Symptom                                 | Likely Cause                                        | Fix                                                |
| --------------------------------------- | --------------------------------------------------- | -------------------------------------------------- |
| `PC/SC not available`                   | Missing `python3-pyscard` or unmounted `/run/pcscd` | Rebuild image or check volume mount                |
| `No YubiKey detected`                   | Host pcscd not running / bad socket perms           | Restart `pcscd`, `chmod 666 /run/pcscd/pcscd.comm` |
| `refresh_cookie ... exit 1`             | Wrong OATH label or locked applet                   | Verify with `ykman oath accounts list`             |
| `Permission denied: '/data/postes.csv'` | Shared bind mount                                   | Use named volume (default)                         |

---

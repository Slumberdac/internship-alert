# Stage Alert Async

## Overview

**Stage Alert Async** is an automated job application bot designed to interact with job postings from the ÉTS job board.
It leverages **asynchronous programming** for efficient, non-blocking operations and provides **real-time Discord notifications** and **automated job analysis** through OpenAI’s GPT models.

---

## Features

* **Asynchronous Job Fetching** — Fetches new postings concurrently without blocking other tasks.
* **Discord Integration** — Sends job alerts and summaries directly to a Discord channel.
* **GPT Integration** — Analyzes postings against the applicant’s CV to evaluate suitability.
* **Cookie Management** — Automatically refreshes session cookies to stay authenticated with the job board.
* **Chromium Automation** — Uses headless Chromium to interact with job listings when required.
* **Dockerized Environment** — Runs consistently across systems without manual Python setup.

---

## Project Structure

```
stage_alert
├── app.py
├── request.py
├── Pipfile
├── Pipfile.lock
├── .env.example
├── Dockerfile
├── .dockerignore
└── README.md
```

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd stage_alert
```

### 2. Configure environment variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

You can edit `.env` to include your Discord token, GPT API key, and job board credentials.

---

## Running the Application

### Option A — Using Docker (recommended)

1. **Build the image:**

   ```bash
   docker build -t stage-alert-async .
   ```

2. **Run the container with your `.env`:**

   ```bash
   docker run --env-file .env stage-alert-async
   ```

---

### Option B — Run locally (advanced)

If you prefer to use your local Python installation instead of Docker:

```bash
pipenv install --dev
pipenv run python app.py
```

Make sure Chromium and Chromedriver are installed on your system.

---

## Development Notes

* The app installs dependencies via **Pipenv** directly into the system environment in Docker (`--system --deploy`).
* Chromium and Chromedriver are included in the container image.
* To debug or test interactively:

  ```bash
  docker run -it --env-file .env --entrypoint bash stage-alert-async
  ```
* Logs and errors are printed to stdout; you can redirect them if needed:

  ```bash
  docker logs <container-id>
  ```

---

## Deploy with Docker Compose

Use Docker Compose to keep the bot running with automatic restarts and centralized logs.

### `compose.yml`

```yaml
version: "3.9"

services:
  stage-alert:
    build: .
    image: stage-alert-async:latest
    env_file:
      - .env
    restart: unless-stopped
    shm_size: 1gb
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

### Commands

```bash
# Build and start in the background
docker compose up -d --build

# Follow logs
docker compose logs -f stage-alert

# Restart after changing only environment vars
docker compose restart stage-alert

# Stop
docker compose down
```

### Updating

If you’re building locally:

```bash
git pull
docker compose up -d --build
```

If you’re pulling from a registry:

```bash
docker compose pull
docker compose up -d
```

### Notes

* Put secrets in `.env` (do **not** commit it).
* If Chromium still complains, ensure your code launches it with flags like `--no-sandbox` and `--disable-dev-shm-usage`.
* To run one-off commands inside the container:

  ```bash
  docker compose exec stage-alert bash
  ```

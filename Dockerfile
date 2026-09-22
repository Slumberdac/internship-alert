# syntax=docker/dockerfile:1.7

# Build rsc.io/2fa as a static binary
FROM golang:1 AS twofa
RUN CGO_ENABLED=0 go install rsc.io/2fa@latest

FROM python:3.13-slim

# Runtime defaults (add POSTES_PATH so code can use it)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POSTES_PATH=/data/postes.csv

# OS deps: Chromium + YubiKey tooling + PC/SC client libs + socat for the host 2FA socket
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium chromium-driver \
      nano \
      ca-certificates xdg-utils fonts-liberation \
      libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
      libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libu2f-udev \
      libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
      libxkbcommon0 libxrandr2 \
      yubikey-manager pcscd pcsc-tools libccid libpcsclite1 python3-pyscard \
      socat \
  && rm -rf /var/lib/apt/lists/*

# 2fa CLI (reads $HOME/.2fa)
COPY --from=twofa /go/bin/2fa /usr/local/bin/2fa

# Make Debian's dist-packages visible to upstream Python (python:3.13)
ENV PYTHONPATH=/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}

# Non-root user + writable data dir
RUN useradd -m -u 10001 appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /data

WORKDIR /app

# Dependencies (Pipenv → system site-packages)
COPY Pipfile Pipfile.lock ./
RUN python -m pip install --upgrade pip pipenv \
 && PIPENV_NOSPIN=1 pipenv install --system --deploy

# App code
COPY . .

# Use YOUR entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# Run as appuser; entrypoint should NOT start pcscd if /run/pcscd/pcscd.comm exists
# USER appuser
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "app.py"]
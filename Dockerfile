# syntax=docker/dockerfile:1.7
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# OS deps: chromium stack + yubikey + pcsc + gosu to drop privileges
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium chromium-driver \
      ca-certificates xdg-utils fonts-liberation \
      libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
      libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libu2f-udev \
      libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 \
      libxkbcommon0 libxrandr2 \
      yubikey-manager pcscd libccid pcsc-tools \
      python3-pyscard gosu \
  && rm -rf /var/lib/apt/lists/*


# Create non-root user
RUN useradd -m -u 10001 appuser

WORKDIR /app

# Dependencies (pipenv → system)
COPY Pipfile Pipfile.lock ./ 
RUN python -m pip install --upgrade pip pipenv \
 && PIPENV_NOSPIN=1 pipenv install --system --deploy
# create a writable data dir
RUN mkdir -p /data && chown -R appuser:appuser /data
ENV POSTES_PATH=/data/postes.csv

# optional: seed an initial CSV
COPY postes.csv /data/postes.csv
RUN chown appuser:appuser /data/postes.csv


# App code
COPY . .

# Entrypoint that starts pcscd as root, then drops to appuser
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# IMPORTANT: keep container default user as root so entrypoint can start pcscd
USER root
ENTRYPOINT ["/entrypoint.sh"]
# Your app runs as appuser *after* entrypoint drops privileges
CMD ["python", "app.py"]

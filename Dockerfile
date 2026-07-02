FROM python:3.12-slim

LABEL org.opencontainers.image.title="Bibliocapsa"
LABEL org.opencontainers.image.description="Read-only REST API for Calibre libraries"
LABEL org.opencontainers.image.source="https://github.com/jwapps-app/bibliocapsa"

# No root after setup
RUN useradd -m -u 1001 bridge

WORKDIR /app

# Calibre CLI (calibredb) for the "Sync to Calibre" write-back. Installed as an
# early, cached layer so ordinary backend rebuilds stay fast. Headless: Qt runs
# offscreen. (calibredb only runs during a deliberate, confirmed sync.)
ENV DEBIAN_FRONTEND=noninteractive
# The Debian calibre package drags in ~240 MB that calibredb never touches:
# scipy/sympy/numpy/mpmath (hard deps of python3-fonttools, used only for
# variable-font math), docs, and calibre's UI localization. Stripped in the
# same layer so the image never carries them (1.44 GB -> ~1.2 GB).
RUN apt-get update && apt-get install -y --no-install-recommends calibre \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/lib/python3/dist-packages/scipy \
              /usr/lib/python3/dist-packages/sympy \
              /usr/lib/python3/dist-packages/numpy* \
              /usr/lib/python3/dist-packages/mpmath \
              /usr/share/doc \
              /usr/share/calibre/localization
# gosu lets the entrypoint fix bind-mount ownership as root, then drop to `bridge`.
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*
ENV QT_QPA_PLATFORM=offscreen
ENV HOME=/home/bridge

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Placeholder no-cover asset directory
RUN mkdir -p ./app/assets

# Writable cache for proxied native-book covers (backed by a named volume in compose)
RUN mkdir -p /app/cover_cache && chown -R bridge:bridge /app/cover_cache

# Holding area for uploaded books pending "Sync to Calibre" (named volume in compose)
RUN mkdir -p /app/uploads && chown -R bridge:bridge /app/uploads

# WebDAV store for KOReader statistics cloud-sync (named volume in compose)
RUN mkdir -p /app/webdav && chown -R bridge:bridge /app/webdav

# Entrypoint fixes data-dir ownership (for bind mounts) then drops root → bridge.
# We intentionally do NOT set `USER bridge`: the container starts as root so the
# entrypoint can chown bind-mounted host folders, then runs the app as bridge.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Calibre library is mounted at /calibre (read-only via docker-compose)
ENV CALIBRE_DB_PATH=/calibre/metadata.db
ENV CALIBRE_LIBRARY_PATH=/calibre

EXPOSE 8000

# Single worker on purpose: the login rate-limiter and background job-status are
# in-process, so multiple workers would each keep their own (weakening the
# brute-force limit and confusing status reads). One worker is plenty for a
# household-scale instance; scale with replicas + a shared store if ever needed.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

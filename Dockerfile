FROM python:3.12-slim

LABEL org.opencontainers.image.title="Bibliocapsa"
LABEL org.opencontainers.image.description="Bibliocapsa — self-hosted library manager: Calibre + physical books, KOReader sync"
LABEL org.opencontainers.image.source="https://github.com/jwapps-app/bibliocapsa"

# No root after setup
RUN useradd -m -u 1001 bridge

WORKDIR /app

# Calibre CLI (calibredb + ebook-meta) for the "Sync to Calibre" write-back.
# Installed from Calibre's official build, pinned, rather than Debian's package:
# Debian is stuck on 8.5, while the library is managed by a much newer desktop
# Calibre. An older calibredb writing to a library whose schema a newer Calibre
# has migrated is the risk this avoids — that binary edits real books. Bump
# CALIBRE_VERSION deliberately to track the desktop version.
#
# The official build is self-contained, so it also avoids Debian's python3-*
# dependency tree (scipy/sympy/numpy, ~220 MB) that we previously stripped by
# hand. Early layer so ordinary backend rebuilds stay cached. Headless: Qt runs
# offscreen; calibredb only runs during a deliberate, confirmed sync.
ARG CALIBRE_VERSION=9.13.0
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      wget xz-utils ca-certificates \
      libgl1 libegl1 libopengl0 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 \
      libglib2.0-0 libdbus-1-3 libxcb1 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 \
      libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
      libxcb-xkb1 libx11-xcb1 libxrandr2 libxi6 libxtst6 libxcomposite1 libxdamage1 \
      libnss3 libasound2 libfreetype6 libharfbuzz0b \
 && arch="$(dpkg --print-architecture)" \
 && case "$arch" in amd64) ca=x86_64 ;; arm64) ca=arm64 ;; *) echo "unsupported arch $arch" >&2; exit 1 ;; esac \
 && wget -q -O /tmp/calibre.txz "https://download.calibre-ebook.com/${CALIBRE_VERSION}/calibre-${CALIBRE_VERSION}-${ca}.txz" \
 && mkdir -p /opt/calibre && tar xf /tmp/calibre.txz -C /opt/calibre && rm /tmp/calibre.txz \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc
ENV PATH="/opt/calibre:${PATH}"
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

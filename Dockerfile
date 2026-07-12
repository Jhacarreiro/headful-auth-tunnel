FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PROFILE_DIR=/data/profile \
    TOKEN_FILE=/data/state/token \
    BIND_HOST=0.0.0.0 \
    PORT=19192 \
    DISPLAY=:99 \
    SCREEN_WIDTH=1440 \
    SCREEN_HEIGHT=1100

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir . \
    && python -m patchright install --with-deps chromium \
    && useradd --create-home --uid 1000 tunnel \
    && mkdir -p /data/profile /data/state /ms-playwright /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix \
    && chown -R tunnel:tunnel /data /ms-playwright /app

USER tunnel
EXPOSE 19192
VOLUME ["/data/profile", "/data/state"]
ENTRYPOINT ["/app/scripts/run-foreground.sh"]
CMD ["headful-auth-tunnel"]

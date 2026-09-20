FROM python:3.12-slim-bookworm AS build

# git is only needed to fetch the pinned ptouch commit; it stays out of the runtime
# image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir .

FROM python:3.12-slim-bookworm

# libusb is what pyusb talks to; DejaVu is the font the renderer looks for first.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libusb-1.0-0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PTOUCH_LISTEN_HOST=0.0.0.0 \
    PTOUCH_PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status==200 else 1)"

CMD ["ptouch-mcp"]

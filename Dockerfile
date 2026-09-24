# ffmpeg is the one non-Python dependency, and it is the thing most likely to be
# missing or the wrong version on an event laptop. Shipping it in the image is
# why `docker compose up` is the recommended way to run this at an event.
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY calandria ./calandria
RUN pip install --no-cache-dir . && pip install --no-cache-dir redis

# Config, glossary and sample audio are mounted rather than baked, so an
# operator changes a stage without rebuilding anything.
COPY calandria.example.yaml glossary.example.yaml ./
COPY samples ./samples

ENV PYTHONUNBUFFERED=1 CALANDRIA_PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

ENTRYPOINT ["python", "-m", "calandria"]
CMD ["-c", "calandria.yaml"]

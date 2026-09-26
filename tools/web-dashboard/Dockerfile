# BEG_WORK read-only web dashboard.
#
# python:3.11-alpine with no pip install step: the application uses only the standard
# library, so the image is the base image plus a few hundred kilobytes of source. That
# is deliberate for a Synology NAS, where this is expected to sit running all day
# beside real workloads, and it also means the image has no third-party dependency
# tree to track for advisories.
FROM python:3.11-alpine

# Unbuffered so `docker logs` in Container Manager shows a line as it happens rather
# than when a buffer fills; no .pyc files to write into a read-only filesystem.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BEGWORK_HOST=0.0.0.0 \
    BEGWORK_PORT=8080

WORKDIR /app

# Runs as a non-root user. The process needs no write access to anything: there is no
# database, no cache directory and no log file, so the container can also be run with a
# read-only root filesystem (see docker-compose.yml).
RUN addgroup -S -g 10001 begwork \
 && adduser -S -u 10001 -G begwork -H -D begwork

COPY app/ /app/app/
COPY static/ /app/static/

USER 10001:10001

EXPOSE 8080

# The health check asks the app's own endpoint, which reports liveness. It returns 200
# while the process can serve even when GitHub is unreachable: restarting a dashboard
# that is waiting out an outage would discard the cached snapshot, which is the one
# thing still worth showing. Readiness detail is in the response body.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status==200 else 1)"

ENTRYPOINT ["python", "-m", "app"]

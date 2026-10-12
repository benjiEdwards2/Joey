# stackctl (2026-10-12): pull + recreate the media-server stack on request from Joey's hub. See README.md.
# Runs as root on purpose: it drives the host's Docker through /var/run/docker.sock.
FROM python:3.12-alpine
RUN apk add --no-cache docker-cli docker-cli-compose
WORKDIR /app
COPY stackctl.py .
ENV PYTHONUNBUFFERED=1 \
    COMPOSE_FILE=/volume1/media-server/docker-compose.yml \
    EXCLUDE="wud stackctl" \
    PORT=8810
EXPOSE 8810
CMD ["python", "/app/stackctl.py"]

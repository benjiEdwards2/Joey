# powerctl (JY-274, 2026-11-05): stop the media stack, then power the NAS off, on request from Joey's hub. See README.md.
# Runs as root on purpose: it drives the host's Docker through /var/run/docker.sock and enters the host's namespaces
# (compose: pid: host + privileged) to run the host's own poweroff. util-linux-misc provides nsenter.
FROM python:3.12-alpine
RUN apk add --no-cache docker-cli docker-cli-compose util-linux-misc
WORKDIR /app
COPY powerctl.py .
ENV PYTHONUNBUFFERED=1 \
    STOP_CMD="docker compose -p media-server stop -t 45" \
    SHUTDOWN_CMD="nsenter -t 1 -m -u -i -n -p -- poweroff" \
    GRACE_S=3 \
    PORT=8811
EXPOSE 8811
CMD ["python", "/app/powerctl.py"]

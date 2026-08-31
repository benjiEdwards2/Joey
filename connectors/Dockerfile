# Jarvis connectors. Build context is the REPO ROOT (config/ + tests/ must be
# inside it), same rule as hub/Dockerfile:
#   docker build -f connectors/Dockerfile -t life-connectors .
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 jarvis
WORKDIR /app

COPY connectors/requirements.txt connectors/requirements.txt
RUN pip install --no-cache-dir -r connectors/requirements.txt

# The suite ships in the image so deploy.sh tests exactly what runs (rule 13)
COPY connectors/ connectors/
COPY config/ config/
COPY tests/ tests/

USER jarvis
ENV SNAPSHOT_DIR=/data/snapshots \
    CONNECTOR_MODE=live \
    PYTHONUNBUFFERED=1
# Hourly sweep via a sleep loop, NOT crond (D16) — the compose entrypoint owns
# the loop so a single sweep stays runnable by hand for debugging.
CMD ["python", "-m", "connectors.run_all"]

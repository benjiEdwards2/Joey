# Joey hub. Build context is the REPO ROOT (config/ must be inside it):
#   docker build -f hub/Dockerfile -t life-hub .
# Never build with context ./hub — Docker would refuse COPY config/.
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 joey
WORKDIR /app

COPY hub/requirements.txt hub/requirements.txt
COPY requirements-dev.txt requirements-dev.txt
RUN pip install --no-cache-dir -r hub/requirements.txt -r requirements-dev.txt

# The suite ships in the image so deploy.sh tests exactly what runs (rule 13)
COPY hub/ hub/
COPY config/ config/
COPY connectors/schema/ connectors/schema/
COPY tests/ tests/

USER joey
ENV SNAPSHOT_DIR=/data/snapshots
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"
CMD ["python", "-m", "uvicorn", "hub.main:app", "--host", "0.0.0.0", "--port", "8000"]

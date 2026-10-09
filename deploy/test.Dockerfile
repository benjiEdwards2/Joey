# Joey TEST image — the rule-13 gate. Build context is the REPO ROOT:
#   docker build -f deploy/test.Dockerfile -t life-test .
#
# The production images each carry only their own service's dependencies, so
# neither can run the FULL cumulative suite (tests/hub needs FastAPI+httpx2,
# tests/connectors needs icalendar AND the hub, tests/money needs scripts/ and
# the git binary, tests/deploy reads deploy/). This union image exists solely
# to run all of tests/ against the exact code the production images are built
# from — deploy.sh (WP9) builds it and gates on its exit code. It is never
# `up`'d and publishes nothing.
FROM python:3.12-slim

# No node on purpose (review D-09, 2026-10-09): tests/hub/test_history_replace.py's one node
# test skips here and runs on the laptop, where node is installed. Debian's nodejs pulls in
# libnode + ICU (~100+ MB) for a single 10-line JS check, on a 3.7 GB NAS that rebuilds this
# image after every base bump. Add `nodejs` to the line below if the gate must run it too.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 joey
WORKDIR /app

COPY hub/requirements.txt hub/requirements.txt
COPY connectors/requirements.txt connectors/requirements.txt
COPY requirements-dev.txt requirements-dev.txt
RUN pip install --no-cache-dir -r hub/requirements.txt \
    -r connectors/requirements.txt -r requirements-dev.txt

# Everything the suite touches (.dockerignore keeps **/.env, **/*.env -- incl. deploy/.env --
# history.log and data out)
COPY . .

USER joey
CMD ["python", "-m", "pytest", "-q", "tests/"]

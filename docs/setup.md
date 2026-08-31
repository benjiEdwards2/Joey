# Dev clone setup

Hooks don't clone with a repo — every fresh clone does this once:

```
git clone https://github.com/benjiEdwards2/life-dashboard.git
cd life-dashboard
pip install --user -r hub/requirements.txt -r requirements-dev.txt
git config core.hooksPath scripts/hooks
```

That last line installs the **money pre-commit guard**
(`scripts/precommit_money_guard.py`): it blocks any staged plaintext money data —
files under `connectors/money/` or any `*.csv`/`*.db` that isn't `.age`-encrypted
or allowlisted, and any staged line shaped like a bank transaction row. The
`.gitignore` rules (WP0) are the first layer; this hook is the second.

Run the suite from the repo root (fixture-mode, no credentials, no network):

```
python -m pytest -q tests/
```

Dev hub with demo data:

```
python -m hub.seed_demo
set SNAPSHOT_DIR=data/demo-snapshots && python -m uvicorn hub.main:app --port 8800
```

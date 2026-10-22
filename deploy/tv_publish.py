"""Joey TV WP-B8 step 4 (Q36 = a): publish the GitHub Release for the tree's tv/VERSION into the NAS `tv-app` dir that
joey-media serves at https://media.joeyhome.net/app/.

deploy.sh runs it after smoke passes (and on NOTHING-TO-DEPLOY), in the life-hub image, never inside rollback:

    docker run --rm --env-file deploy/tv.env -v <repo>:/repo:ro -v /volume1/Docker/joey/data/tv-app:/out \
        life-hub python /repo/deploy/tv_publish.py

1. versionCode from <repo>/tv/VERSION; <out>/version.json already has it -> `current` (no HTTP).
   A LOWER tree versionCode than the published one is refused (Android never downgrades: roll forward instead).
2. GET /repos/<slug>/releases/tags/tv-<code> with GH_TV_TOKEN (fine-grained, Contents: read, this repo only).
   404 -> `pending:<code>` (the Actions release job has not finished, or this tree is not a release).
3. Both assets (the APK + version.json) -> <out>/.staging/ (Accept: application/octet-stream; the token is never
   forwarded to the storage redirect).
4. Verify: version.json is valid, its versionCode == the tree's, its url == the APK asset name, sha256 + size match.
5. Move the APK first and version.json LAST (os.replace), so a client never sees a version.json without its APK.
6. Keep the newest 3 APKs. Staging is always removed.

Stdout's only line is the status token (no spaces) deploy.sh puts in the history line as `tv=<status>`:
    published:<code> | current | pending:<code> | skipped:no-token | FAIL:<reason>
    (reasons: version-file, downgrade, auth, network, github-<http>, download-<http>, verify-json, verify-code,
    verify-url, verify-sha256, verify-size, <ExceptionName>)
Exit 0 for every non-FAIL status; 1 = verification / network failure; 2 = the token was rejected (401/403).
Progress lines go to stderr. The token is never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tv_version  # noqa: E402

API = "https://api.github.com"
SLUG = "benjiEdwards2/life-dashboard"
KEEP_APKS = 3
STAGING = ".staging"
USER_AGENT = "joey-tv-publish"


class PublishError(Exception):
    """`status` is one space-free token for the history line; `detail` goes to stderr."""

    def __init__(self, status: str, detail: str, code: int = 1):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _request(url: str, token: str, accept: str) -> urllib.request.Request:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT,
                                               "X-GitHub-Api-Version": "2022-11-28"})
    # Unredirected: the asset download 302s to a storage host that rejects (and must never see) the token.
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def _open(req: urllib.request.Request, timeout: int):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PublishError("FAIL:auth", f"HTTP {exc.code}: GitHub rejected the token - renew GH_TV_TOKEN in "
                               "deploy/tv.env (docs/tv-release.md, NAS token renewal)", 2) from None
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PublishError("FAIL:network", f"cannot reach GitHub ({type(exc).__name__})") from None


def published_code(out: Path) -> int | None:
    try:
        doc = json.loads((out / "version.json").read_text(encoding="utf-8"))
        return int(doc["versionCode"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _apk_code(name: str) -> int:
    return int(name.rsplit("-", 1)[1].removesuffix(".apk"))


def prune(out: Path, keep: int = KEEP_APKS) -> list[str]:
    apks = sorted((p.name for p in out.iterdir() if p.is_file() and tv_version.APK_NAME_RE.match(p.name)),
                  key=_apk_code, reverse=True)
    removed = apks[keep:]
    for name in removed:
        (out / name).unlink()
    return removed


def publish(repo: Path, out: Path, token: str | None, api: str = API, slug: str = SLUG) -> str:
    try:
        values = tv_version.read_version(repo)
    except (OSError, ValueError) as exc:
        raise PublishError("FAIL:version-file", f"tv/VERSION: {exc}") from None
    code = int(values["versionCode"])
    current = published_code(out)
    if current == code:
        return "current"
    if current is not None and current > code:
        raise PublishError("FAIL:downgrade", f"tree versionCode {code} is below the published {current}: Android "
                           "never downgrades - revert with a HIGHER versionCode")
    if not token:
        return "skipped:no-token"

    url = f"{api.rstrip('/')}/repos/{slug}/releases/tags/tv-{code}"
    try:
        with _open(_request(url, token, "application/vnd.github+json"), 30) as resp:
            release = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return f"pending:{code}"
        raise PublishError(f"FAIL:github-{exc.code}", f"release lookup answered HTTP {exc.code}") from None
    assets = {a.get("name"): a.get("url") for a in release.get("assets", []) if isinstance(a, dict)}
    apk_name = tv_version.apk_name(values)
    if apk_name not in assets or "version.json" not in assets:
        return f"pending:{code}"   # the release job is still uploading

    staging = out / STAGING
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for name in (apk_name, "version.json"):
            try:
                with _open(_request(assets[name], token, "application/octet-stream"), 300) as resp, \
                        open(staging / name, "wb") as fh:
                    shutil.copyfileobj(resp, fh, 1 << 20)
            except urllib.error.HTTPError as exc:
                raise PublishError(f"FAIL:download-{exc.code}", f"{name} download answered HTTP {exc.code}") from None
        try:
            doc = json.loads((staging / "version.json").read_text(encoding="utf-8"))
        except ValueError:
            raise PublishError("FAIL:verify-json", "version.json is not JSON") from None
        problems = tv_version.validate_version_json(doc)
        if problems:
            raise PublishError("FAIL:verify-json", "; ".join(problems))
        if doc["versionCode"] != code:
            raise PublishError("FAIL:verify-code", f"version.json versionCode {doc['versionCode']} != tree {code}")
        if doc["url"] != apk_name:
            raise PublishError("FAIL:verify-url", f"version.json url {doc['url']} != {apk_name}")
        apk = staging / apk_name
        if tv_version.sha256_file(apk) != doc["sha256"]:
            raise PublishError("FAIL:verify-sha256", "sha256 of the APK does not match version.json")
        if apk.stat().st_size != doc["size"]:
            raise PublishError("FAIL:verify-size", "APK size does not match version.json")
        os.replace(apk, out / apk_name)                        # the APK first ...
        os.replace(staging / "version.json", out / "version.json")   # ... version.json LAST
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    removed = prune(out)
    if removed:
        log(f"tv_publish: removed old APKs {', '.join(removed)}")
    return f"published:{code}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the Joey TV release for tv/VERSION")
    parser.add_argument("--repo", type=Path, default=Path("/repo"))
    parser.add_argument("--out", type=Path, default=Path("/out"))
    parser.add_argument("--api", default=os.environ.get("GH_API_URL", API))
    parser.add_argument("--slug", default=SLUG)
    args = parser.parse_args(argv)
    token = (os.environ.get("GH_TV_TOKEN") or "").strip()
    try:
        status, rc = publish(args.repo, args.out, token, args.api, args.slug), 0
    except PublishError as exc:
        log(f"tv_publish: {exc.status}: {exc.detail}")
        status, rc = exc.status, exc.code
    except Exception as exc:  # noqa: BLE001 - one status line whatever happened; never a traceback with a URL
        status, rc = f"FAIL:{type(exc).__name__}", 1
    print(status)
    return rc


if __name__ == "__main__":
    sys.exit(main())

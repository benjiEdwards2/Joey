"""Cloudflare Access JWT verification in joey-hub (Joey TV WP-A6a, 2026-10-19; Q25b pulled forward; parent H-64).

The hub stops trusting the bare `Cf-Access-Authenticated-User-Email` header once `ACCESS_JWT_VERIFY` is set:
unset / `0` = off (today's behaviour, the default), `audit` = verify and log only, `1` = enforce (401 / 503).

Every value here is invented (rule 20): the AUD tags, the addresses (example.com) and the RSA keys, which are generated
per test session and never stored. Tokens are minted in-test with epoch-relative times, so the UTC gate clock is
irrelevant. The JWKS fetch is monkeypatched; no test touches the network.
"""
import base64
import hashlib
import hmac
import importlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from hub import access_jwt
from hub.identity import IDENTITY_HEADER
from tests.hub.helpers import make_area, make_tile, write_envelope, write_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
JWT_HEADER = "Cf-Access-Jwt-Assertion"
YOU = "you@example.com"
OTHER = "other@example.com"
AUD_A = "test-aud-alpha-0000"
AUD_B = "test-aud-bravo-1111"
ISS = "https://joeyhomeed.cloudflareaccess.com"   # the in-code default team (not a secret; named in the plan)
KID = "testkid-a1b2c3d4e5f6"
OTHER_KID = "testkid-ffffeeee0000"


# ---- keys and tokens ----

@pytest.fixture(scope="session")
def keys():
    """A throwaway signing key and an unrelated second key (proves `kid` selection); never written to disk."""
    return (rsa.generate_private_key(public_exponent=65537, key_size=2048),
            rsa.generate_private_key(public_exponent=65537, key_size=2048))


def _jwk(private_key, kid):
    d = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    d.update(kid=kid, alg="RS256", use="sig")
    return d


def _jwks(keys):
    return {"keys": [_jwk(keys[1], OTHER_KID), _jwk(keys[0], KID)]}


def _claims(**over):
    now = int(time.time())
    c = {"aud": [AUD_A], "email": YOU, "exp": now + 3600, "iat": now - 60, "nbf": now - 60, "iss": ISS,
         "sub": "00000000-0000-0000-0000-000000000000", "type": "app"}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def mint(keys, kid=KID, signer=0, **over):
    return jwt.encode(_claims(**over), keys[signer], algorithm="RS256", headers={"kid": kid})


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _segments(header: dict, claims: dict) -> str:
    return _b64(json.dumps(header).encode()) + "." + _b64(json.dumps(claims).encode())


# ---- the app under test ----

@pytest.fixture()
def fetches(monkeypatch, keys):
    """The JWKS fetch, monkeypatched and counted; `fetches.fail = True` makes it raise."""
    class Fetcher:
        count = 0
        fail = False

        def __call__(self, url):
            self.count += 1
            self.url = url
            if self.fail:
                raise OSError("certs unreachable (test)")
            return _jwks(keys)

    f = Fetcher()
    monkeypatch.setattr(access_jwt, "_fetch_jwks", f)
    access_jwt.reset()
    yield f
    access_jwt.reset()


@pytest.fixture()
def hub(tmp_path, monkeypatch, fetches):
    """hub.main with one area: a you-tile (YOU-VAL) and a her-tile (HER-VAL), so the page shows whose view it is."""
    monkeypatch.setenv("OWNER_EMAIL_YOU", YOU)
    for key in ("ACCESS_JWT_VERIFY", "ACCESS_AUD", "ACCESS_TEAM"):
        monkeypatch.delenv(key, raising=False)
    area = make_area("mixed", "you-t")
    area["tiles"] = [make_tile("you-t", owner="you", snapshot="jellyfin", stale_after_minutes=120),
                     make_tile("her-t", owner="her", snapshot="gcal", stale_after_minutes=120)]
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area)))
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", data={"summary": "YOU-VAL"})
    write_envelope(snaps, "gcal", data={"summary": "HER-VAL"})
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))
    import hub.main
    importlib.reload(hub.main)
    return hub.main.app


@pytest.fixture()
def client(hub):
    with TestClient(hub) as c:
        yield c


@pytest.fixture()
def enforce(monkeypatch):
    monkeypatch.setenv("ACCESS_JWT_VERIFY", "1")
    monkeypatch.setenv("ACCESS_AUD", AUD_A)


def signed_in(token, email=YOU):
    return {JWT_HEADER: token, IDENTITY_HEADER: email}


def fail_lines(caplog):
    return [r.getMessage() for r in caplog.records if "access_jwt" in r.getMessage() and "FAIL" in r.getMessage()]


# 1. flag off: today's trust, byte for byte

@pytest.mark.parametrize("flag", [None, "0", " "])
def test_flag_off_still_trusts_a_bare_header(client, fetches, monkeypatch, caplog, flag):
    """The default (merge + deploy changes nothing until B. sets the env): a forged header with no token is believed,
    no JWKS fetch happens, and the hub logs nothing about access_jwt."""
    if flag is not None:
        monkeypatch.setenv("ACCESS_JWT_VERIFY", flag)
    with caplog.at_level(logging.DEBUG):
        her = client.get("/a/mixed", headers={IDENTITY_HEADER: OTHER})
        nobody = client.get("/a/mixed")
    assert her.status_code == 200 and "HER-VAL" in her.text and "YOU-VAL" not in her.text
    assert nobody.status_code == 200 and "HER-VAL" in nobody.text and "YOU-VAL" in nobody.text   # the "both" view
    assert fetches.count == 0
    assert not [r for r in caplog.records if "access_jwt" in r.getMessage()]


def test_gate_is_the_innermost_middleware(hub):
    """FIRST add_middleware call = innermost, so ShellMiddleware's request line still logs the gate's 401."""
    classes = [m.cls for m in hub.user_middleware]
    assert classes[-1] is access_jwt.AccessGate
    assert classes[-2].__name__ == "ShellMiddleware"


# 2. enforce: a valid token passes and the signed claim is "you"

def test_valid_token_and_matching_header_pass_as_you(client, enforce, keys, fetches):
    r = client.get("/a/mixed", headers=signed_in(mint(keys)))
    assert r.status_code == 200
    assert "YOU-VAL" in r.text and "HER-VAL" not in r.text
    assert fetches.count == 1 and fetches.url == ISS + "/cdn-cgi/access/certs"


# 3. no token

def test_missing_token_is_401_plain_text(client, enforce, caplog):
    with caplog.at_level(logging.INFO):
        r = client.get("/a/mixed", headers={IDENTITY_HEADER: YOU})
        bare = client.get("/")
    for resp in (r, bare):
        assert resp.status_code == 401
        assert resp.headers["content-type"].startswith("text/plain")
        assert "<" not in resp.text and "VAL" not in resp.text
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=missing path=/a/mixed", "access_jwt: FAIL reason=missing path=/"]
    assert any(r.getMessage().startswith("GET / owner=") and r.getMessage().endswith("-> 401") for r in caplog.records)


# 4. tampered payload

def test_tampered_payload_is_401_sig(client, enforce, keys, caplog):
    head, _, sig = mint(keys).split(".")
    forged = head + "." + _b64(json.dumps(_claims(email=OTHER)).encode()) + "." + sig
    r = client.get("/", headers=signed_in(forged, OTHER))
    assert r.status_code == 401
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=sig path=/"]


def test_malformed_token_is_401(client, enforce, caplog):
    assert client.get("/", headers=signed_in("not.a.jwt")).status_code == 401
    assert client.get("/", headers=signed_in("garbage")).status_code == 401


# 5. algorithm confusion

def test_alg_none_and_hs256_are_401_alg(client, enforce, keys, caplog):
    none_token = _segments({"alg": "none", "typ": "JWT", "kid": KID}, _claims()) + "."
    pem = keys[0].public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    signing_input = _segments({"alg": "HS256", "typ": "JWT", "kid": KID}, _claims())
    hs_token = signing_input + "." + _b64(hmac.new(pem, signing_input.encode(), hashlib.sha256).digest())
    for token in (none_token, hs_token):
        assert client.get("/", headers=signed_in(token)).status_code == 401
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=alg path=/"] * 2


# 6. audience

def test_wrong_aud_is_401_and_a_two_value_list_accepts_either(client, enforce, keys, monkeypatch, caplog):
    assert client.get("/", headers=signed_in(mint(keys, aud=["some-other-app"]))).status_code == 401
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=aud path=/"]
    monkeypatch.setenv("ACCESS_AUD", f"{AUD_A}, {AUD_B}")
    assert client.get("/", headers=signed_in(mint(keys, aud=[AUD_A]))).status_code == 200
    assert client.get("/", headers=signed_in(mint(keys, aud=[AUD_B]))).status_code == 200
    assert client.get("/", headers=signed_in(mint(keys, aud=AUD_B))).status_code == 200   # a bare string aud too


# 7. issuer

def test_wrong_iss_is_401(client, enforce, keys, caplog):
    r = client.get("/", headers=signed_in(mint(keys, iss="https://someone-else.cloudflareaccess.com")))
    assert r.status_code == 401
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=iss path=/"]


# 8. expiry, with 60 s leeway

def test_expired_beyond_leeway_is_401_within_leeway_passes(client, enforce, keys, caplog):
    now = int(time.time())
    assert client.get("/", headers=signed_in(mint(keys, exp=now - 120))).status_code == 401
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=exp path=/"]
    assert client.get("/", headers=signed_in(mint(keys, exp=now - 30))).status_code == 200


def test_missing_time_claims_and_future_nbf_are_401(client, enforce, keys):
    now = int(time.time())
    for over in ({"exp": None}, {"iat": None}, {"nbf": None}, {"nbf": now + 600}):
        assert client.get("/", headers=signed_in(mint(keys, **over))).status_code == 401, over


# 9. the header must be the signed email

def test_header_email_must_equal_the_claim(client, enforce, keys, caplog):
    assert client.get("/a/mixed", headers=signed_in(mint(keys), OTHER)).status_code == 401
    assert client.get("/a/mixed", headers={JWT_HEADER: mint(keys)}).status_code == 401   # token, no header
    assert client.get("/", headers=signed_in(mint(keys, email=None))).status_code == 401   # no email claim
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=email path=/a/mixed"] * 2 + ["access_jwt: FAIL reason=email path=/"]
    r = client.get("/a/mixed", headers=signed_in(mint(keys), "You@Example.COM"))
    assert r.status_code == 200 and "YOU-VAL" in r.text and "HER-VAL" not in r.text


# 10. unknown kid: one re-fetch, then throttled for 60 s

def test_unknown_kid_refetches_once_then_waits(client, enforce, keys, fetches, monkeypatch, caplog):
    clock = [1000.0]
    monkeypatch.setattr(access_jwt, "_clock", lambda: clock[0])
    assert client.get("/", headers=signed_in(mint(keys))).status_code == 200
    assert fetches.count == 1
    assert client.get("/", headers=signed_in(mint(keys, kid="testkid-unknown-1"))).status_code == 401
    assert fetches.count == 2
    clock[0] += 30
    assert client.get("/", headers=signed_in(mint(keys, kid="testkid-unknown-2"))).status_code == 401
    assert fetches.count == 2   # within 60 s of the last unknown-kid re-fetch
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=kid path=/"] * 2
    clock[0] += 31
    assert client.get("/", headers=signed_in(mint(keys, kid="testkid-unknown-3"))).status_code == 401
    assert fetches.count == 3
    assert client.get("/", headers=signed_in(mint(keys, kid=OTHER_KID, signer=1))).status_code == 200  # 2nd key works


def test_first_request_with_unknown_kid_fetches_once(client, enforce, keys, fetches):
    assert client.get("/", headers=signed_in(mint(keys, kid="testkid-unknown-1"))).status_code == 401
    assert fetches.count == 1


def test_keys_refresh_every_24h(client, enforce, keys, fetches, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(access_jwt, "_clock", lambda: clock[0])
    for _ in range(3):
        assert client.get("/", headers=signed_in(mint(keys))).status_code == 200
    assert fetches.count == 1
    clock[0] += 24 * 3600 + 1
    assert client.get("/", headers=signed_in(mint(keys))).status_code == 200
    assert fetches.count == 2
    fetches.fail = True   # a failed refresh keeps the cached keys
    clock[0] += 24 * 3600 + 1
    assert client.get("/", headers=signed_in(mint(keys))).status_code == 200


# 11. no keys at all: 503, distinguishable from a forged request; /healthz always open

def test_no_keys_is_503_and_healthz_stays_open(client, enforce, keys, fetches, caplog):
    fetches.fail = True
    r = client.get("/", headers=signed_in(mint(keys)))
    assert r.status_code == 503 and "<" not in r.text
    assert fail_lines(caplog) == ["access_jwt: FAIL reason=no_keys path=/"]
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz", headers={IDENTITY_HEADER: OTHER}).status_code == 200


# 12. loopback peer is exempt (smoke.py, docker exec reads, local dev)

def test_loopback_peer_is_exempt(hub, enforce, fetches):
    for peer in ("127.0.0.1", "::1"):
        with TestClient(hub, client=(peer, 1)) as c:
            assert c.get("/").status_code == 200
    with TestClient(hub, client=("172.18.0.5", 1)) as c:   # a bridge neighbour is not
        assert c.get("/").status_code == 401
    assert fetches.count == 0


# 13. audit: verify and log, never refuse; logs carry no email and no token

def test_audit_logs_but_never_refuses(client, keys, monkeypatch, caplog):
    monkeypatch.setenv("ACCESS_JWT_VERIFY", "audit")
    monkeypatch.setenv("ACCESS_AUD", AUD_A)
    token = mint(keys)
    with caplog.at_level(logging.DEBUG):
        forged = client.get("/a/mixed", headers={IDENTITY_HEADER: OTHER})
        assert forged.status_code == 200 and "HER-VAL" in forged.text
        assert fail_lines(caplog) == ["access_jwt: audit FAIL reason=missing path=/a/mixed"]
        assert client.get("/a/mixed", headers=signed_in(token)).status_code == 200
        assert len(fail_lines(caplog)) == 1
    text = caplog.text
    assert "keys loaded" in text
    assert "access_jwt: audit ok kid=testkid- owner=you" in text   # the first 8 chars of the kid only
    for secret in (YOU, OTHER, token, token.split(".")[1], token.split(".")[2], KID):
        assert secret not in text


# 14. startup validation: a misconfigured flag fails the deploy at wait_for_hub instead of silently opening

@pytest.mark.parametrize("flag", ["1", "audit"])
def test_check_config_requires_aud(monkeypatch, flag):
    monkeypatch.setenv("ACCESS_JWT_VERIFY", flag)
    for blank in (None, "", " , "):
        if blank is None:
            monkeypatch.delenv("ACCESS_AUD", raising=False)
        else:
            monkeypatch.setenv("ACCESS_AUD", blank)
        with pytest.raises(ValueError, match="ACCESS_AUD"):
            access_jwt.check_config()
    monkeypatch.setenv("ACCESS_AUD", AUD_A)
    access_jwt.check_config()


def test_check_config_off_needs_nothing_and_rejects_unknown_flags(monkeypatch):
    monkeypatch.delenv("ACCESS_AUD", raising=False)
    for flag in (None, "", "0"):
        if flag is None:
            monkeypatch.delenv("ACCESS_JWT_VERIFY", raising=False)
        else:
            monkeypatch.setenv("ACCESS_JWT_VERIFY", flag)
        access_jwt.check_config()
    monkeypatch.setenv("ACCESS_JWT_VERIFY", "yes")
    with pytest.raises(ValueError, match="ACCESS_JWT_VERIFY"):
        access_jwt.check_config()


def test_import_hub_main_with_flag_on_and_no_aud_raises():
    env = {k: v for k, v in os.environ.items() if not k.startswith("ACCESS_")}
    env["ACCESS_JWT_VERIFY"] = "1"
    out = subprocess.run([sys.executable, "-c", "import hub.main"], cwd=REPO_ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode != 0
    assert "ValueError" in out.stderr and "ACCESS_AUD" in out.stderr


# 15. compose / env hygiene: the keys live only in NAS env files (a future joey-media can never inherit them)

def test_access_keys_only_in_nas_env_files():
    compose = yaml.safe_load((REPO_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, svc in compose["services"].items():
        env = svc.get("environment") or {}
        names = env if isinstance(env, dict) else [e.split("=", 1)[0] for e in env]
        assert not [n for n in names if str(n).startswith("ACCESS_")], name
    example = (REPO_ROOT / "deploy" / ".env.example").read_text(encoding="utf-8").splitlines()
    for key in ("ACCESS_JWT_VERIFY", "ACCESS_AUD"):
        assert any(ln.startswith(f"# {key}=") for ln in example), key
        assert not any(ln.startswith(f"{key}=") for ln in example), key   # commented only: unset = off

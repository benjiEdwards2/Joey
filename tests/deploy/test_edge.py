"""Joey TV WP-A3 (2026-10-18) — the public edge: SWAG (`joey-swag`) + DDNS (`joey-ddns`), dark behind compose
profiles. Network mode (a) HOST since WP-A4 (2026-10-19): on this NAS the DNAT rule that keeps the real client IP on a
published port is written by ADM Defender, not dockerd, and a container started right after another one stops gets
none, so a bridge-mode swag saw every client as the bridge gateway after deploy.sh. In host mode nginx binds 443 itself.

Pins the edge requirements R4-E1…E9 offline: no published port (swag binds host 443 itself), one server_name and one
upstream (`127.0.0.1:8096`, Jellyfin's published port: the rule-14 exception), AU + NZ geo with our own `$joey_country` variable, the fail2ban auth jail, and
the Cloudflare token reaching only swag + ddns through the NAS-only `deploy/edge.env` (Q6). `nginx -t`, certbot and
fail2ban-regex only run live (WP-A4); these tests pin the file shapes they run against.
"""

import configparser
import ipaddress
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"
SWAG = DEPLOY / "swag"
COMPOSE_TEXT = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load(COMPOSE_TEXT)
SERVICES = COMPOSE["services"]

PROXY_CONF = SWAG / "proxy-confs" / "jellyfin.subdomain.conf"
GEO_CONF = SWAG / "site-confs" / "00-geo-au.conf"
DEFAULT_CONF = SWAG / "site-confs" / "default.conf"
JAIL = SWAG / "fail2ban" / "jail.local"
FILTER = SWAG / "fail2ban" / "filter.d" / "jellyfin-auth.local"
NGINX_CONFS = (PROXY_CONF, GEO_CONF, DEFAULT_CONF)

# the five repo confs and where SWAG reads them (bind-mounted file by file, read-only)
CONF_BINDS = {
    "./swag/site-confs/00-geo-au.conf": "/config/nginx/site-confs/00-geo-au.conf",
    "./swag/site-confs/default.conf": "/config/nginx/site-confs/default.conf",
    "./swag/proxy-confs/jellyfin.subdomain.conf": "/config/nginx/proxy-confs/jellyfin.subdomain.conf",
    "./swag/fail2ban/jail.local": "/config/fail2ban/jail.local",
    "./swag/fail2ban/filter.d/jellyfin-auth.local": "/config/fail2ban/filter.d/jellyfin-auth.local",
}

# E6, mode (a) host: the LAN ranges, plus loopback. No external client can arrive as a Docker bridge address in host
# mode, so 172.16/12 is gone. 127.0.0.1 can only be a local process: deploy.sh's host-network smoke curl, which would
# otherwise be geo-403'd and roll the deploy back. fail2ban's ignoreip mirrors this set.
E6_PRIVATE = {"192.168.0.0/16", "10.0.0.0/8", "127.0.0.1/32"}

TOKEN_KEY = "CLOUDFLARE_API_TOKEN"  # never written next to "=" with a value in this file (rule 20)


def _code(path: Path) -> str:
    """nginx conf text with `#` comments removed (our confs carry no `#` inside strings)."""
    return "\n".join(line.split("#", 1)[0].rstrip() for line in path.read_text(encoding="utf-8").splitlines())


def _blocks(code: str) -> dict:
    """`geo|map <source> <$var> { k v; ... }` blocks -> {var: {key: value}} (keys unquoted)."""
    out = {}
    for _kind, _src, var, body in re.findall(r"\b(geo|map)\s+(\S+)\s+(\$\w+)\s*\{(.*?)\}", code, re.S):
        entries = {}
        for stmt in body.split(";"):
            parts = stmt.split()
            if len(parts) == 2:
                entries[parts[0].strip('"')] = parts[1]
        out[var] = entries
    return out


# ---- E1: one inbound port, host 443 bound by swag's nginx itself; nothing on 80 ----

def test_edge_publish_shape():
    swag = SERVICES["swag"]
    assert swag["network_mode"] == "host"  # Q44 = (a): nginx listens on host 443 (Q5: free on the NAS, WP0 (a))
    assert "ports" not in swag and "networks" not in swag  # host mode has neither
    for name, svc in SERVICES.items():
        assert "ports" not in svc, name  # no service publishes a port at all
    assert not re.search(r":80(?!\d)", COMPOSE_TEXT)  # no port-80 mapping anywhere (hub:8000 is fine)
    for conf in NGINX_CONFS:
        code = _code(conf)
        assert not re.search(r"\blisten\s+80\b", code), conf.name
        assert not re.search(r"\blisten\s+\[::\]", code), conf.name  # E4: no IPv6 listener
        assert set(re.findall(r"\blisten\s+([^;]+);", code)) <= {"443 ssl", "443 ssl default_server"}, conf.name


# ---- swag service shape (verdict table) ----

def test_swag_shape():
    swag = SERVICES["swag"]
    assert re.match(r"^(lscr\.io/)?linuxserver/swag:[0-9]", swag["image"])  # exact tag, never latest (D-06)
    assert swag["container_name"] == "joey-swag"  # joey-* = held from WUD updates (hub.server.update_hold, Q10)
    assert swag["profiles"] == ["edge"]
    assert swag["cap_add"] == ["NET_ADMIN"]  # fail2ban's iptables bans inside the container
    assert swag["restart"] == "unless-stopped"
    assert swag["env_file"] == [{"path": "edge.env", "required": False}]  # Q6
    env = swag["environment"]
    assert env["URL"] == "joeyhome.net"
    assert env["SUBDOMAINS"] == "wildcard"  # E3: *.joeyhome.net
    assert env["ONLY_SUBDOMAINS"] == "true"
    assert env["VALIDATION"] == "dns" and env["DNSPLUGIN"] == "cloudflare"
    assert env["PUID"] == "1000" and env["PGID"] == "1000"
    assert env["DOCKER_MODS"] == "linuxserver/mods:swag-dbip"
    assert "EMAIL" not in env  # E3: Let's Encrypt sends no expiry mail any more; Kuma watches the cert
    assert "STAGING" not in env  # first issuance sets STAGING=true in edge.env (edge_cf_ini.sh), not here
    assert "/volume1/Docker/joey/swag:/config" in swag["volumes"]
    for src, dst in CONF_BINDS.items():
        assert f"{src}:{dst}:ro" in swag["volumes"], src
        assert (DEPLOY / src).is_file(), src


# ---- E5: DDNS only for jellyfin., never proxied, no IPv6 ----

def test_ddns_only_jellyfin_never_proxied():
    ddns = SERVICES["ddns"]
    assert re.match(r"^favonia/cloudflare-ddns:[0-9]", ddns["image"])  # pinned
    assert ddns["container_name"] == "joey-ddns"
    assert ddns["profiles"] == ["ddns"]  # Q3 static IP: built, never enabled
    assert ddns["env_file"] == [{"path": "edge.env", "required": False}]
    env = ddns["environment"]
    assert env["DOMAINS"] == "jellyfin.joeyhome.net"  # E4: never the apex, media. or macromates.
    assert env["PROXIED"] == "false"
    assert env["IP6_PROVIDER"] == "none"
    assert env["UPDATE_CRON"] == "@every 5m"
    assert "ports" not in ddns


# ---- E8: the Cloudflare token reaches swag and ddns only ----

def test_token_reaches_only_edge_containers():
    for name, svc in SERVICES.items():
        files = svc.get("env_file") or []
        uses_edge = any((f if isinstance(f, str) else f["path"]) == "edge.env" for f in files)
        assert uses_edge == (name in {"swag", "ddns"}), name
        assert TOKEN_KEY not in (svc.get("environment") or {}), name
    assert TOKEN_KEY not in COMPOSE_TEXT  # no interpolation of the token anywhere in compose
    # the app containers' env files are untouched by the edge (D-05 split stays as it was)
    assert SERVICES["hub"]["env_file"] == [".env", {"path": "hub.env", "required": False}]
    assert SERVICES["connectors"]["env_file"] == [".env", {"path": "connectors.env", "required": False}]
    assert "env_file" not in SERVICES["cloudflared"] and "env_file" not in SERVICES["macromates"]


# ---- E2: one server_name, one upstream (127.0.0.1:8096, the rule-14 exception), geo-gated ----

def test_proxy_conf_single_upstream_and_geo_gated():
    code = _code(PROXY_CONF)
    assert re.findall(r"\bserver_name\s+([^;]+);", code) == ["jellyfin.joeyhome.net"]
    # mode (a): Jellyfin's published port on loopback, as a literal: the one proxy target, no resolver needed
    assert set(re.findall(r"\bproxy_pass\s+([^;]+);", code)) == {"http://127.0.0.1:8096"}
    assert not re.search(r"\bset\s+\$upstream_", code)  # no variable upstream that could point elsewhere
    assert not re.search(r"\bupstream\s+\S+\s*\{", code)  # no upstream{} block with other targets
    assert set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", code)) == {"127.0.0.1"}  # the only IPv4 literal
    assert re.search(r"if\s*\(\$geo_allowed\s*=\s*0\)\s*\{\s*return\s+403;\s*\}", code)  # E6
    assert "include /config/nginx/proxy.conf;" in code  # SWAG's websocket Upgrade/Connection headers
    assert "include /config/nginx/ssl.conf;" in code
    assert re.search(r'add_header\s+Strict-Transport-Security\s+"max-age=\d+', code)  # HSTS


# ---- E6: AU + NZ, plus the private ranges for the mode ----

def test_geo_au_plus_private():
    code = _code(GEO_CONF)
    assert re.search(r"geoip2\s+/config/geoip2db/dbip-country-lite\.mmdb\s*\{\s*\$joey_country\s+country\s+iso_code;",
                     code)
    assert "$geoip2_data_country_iso_code" not in code  # never the dbip mod's own variable
    blocks = _blocks(code)
    country = blocks["$joey_country_allowed"]
    assert country.pop("default") == "0"
    assert {k for k, v in country.items() if v == "1"} == {"AU", "NZ"} and set(country.values()) == {"1"}
    private = blocks["$joey_private"]
    assert private.pop("default") == "0"
    assert set(private) == E6_PRIVATE and set(private.values()) == {"1"}
    combine = blocks["$geo_allowed"]
    assert combine["default"] == "0"
    assert re.search(r'map\s+"\$joey_private\$joey_country_allowed"\s+\$geo_allowed', code)

    def allowed(ip: str, iso: str) -> str:
        p = "1" if any(ipaddress.ip_address(ip) in ipaddress.ip_network(n) for n in private) else "0"
        c = country.get(iso, "0")
        return combine.get(p + c, combine["default"])

    assert allowed("1.1.1.1", "AU") == "1"
    assert allowed("203.0.113.9", "NZ") == "1"  # B., 2026-10-18: NZ added
    assert allowed("8.8.8.8", "US") == "0"
    assert allowed("192.168.68.55", "") == "1"  # LAN client (WP0 probe address)
    assert allowed("10.1.2.3", "") == "1"
    assert allowed("127.0.0.1", "") == "1"  # deploy.sh's host-network smoke curl (--resolve ...:127.0.0.1)
    assert allowed("172.31.250.1", "") == "0"  # mode (a): no client arrives as a bridge address any more
    assert allowed("172.18.0.5", "") == "0"
    assert allowed("100.104.0.1", "") == "0"  # CGNAT is not private for E6


# ---- E2: every other Host / SNI / bare IP -> 444 ----

def test_default_444_keeps_include():
    code = _code(DEFAULT_CONF)
    assert re.search(r"\blisten\s+443\s+ssl\s+default_server;", code)
    assert re.search(r"\bserver_name\s+_;", code)
    assert re.search(r"\breturn\s+444;", code)
    assert "include /config/nginx/proxy-confs/*.subdomain.conf;" in code
    assert not re.search(r"\blisten\s+\[::\]", code) and not re.search(r"\blisten\s+80\b", code)
    assert "proxy_pass" not in code and "fastcgi_pass" not in code and "try_files" not in code


# ---- E7: fail2ban jail on Jellyfin auth 401s in SWAG's access log ----

AUTH_401 = [
    '203.0.113.7 - - [18/Oct/2026:10:00:00 +1100] "POST /Users/AuthenticateByName HTTP/1.1" 401 0 "-" "Sample TV/1.0"',
    '203.0.113.8 - - [18/Oct/2026:10:00:01 +1100] "POST /Users/AuthenticateWithQuickConnect HTTP/2.0" 401 12 "-" "x"',
    '203.0.113.9 - - [18/Oct/2026:10:00:02 +1100] "POST /users/authenticatebyname HTTP/1.1" 401 0 "-" "Sample App"',
    # fail2ban cuts the matched timestamp out of the line before failregex runs (the stock nginx filters match `\[\]`)
    '203.0.113.10 - - [] "POST /Users/AuthenticateByName HTTP/1.1" 401 0 "-" "Sample TV/1.0"',
]
NOT_AUTH_401 = [
    '203.0.113.7 - - [18/Oct/2026:10:00:00 +1100] "POST /Users/AuthenticateByName HTTP/1.1" 200 950 "-" "Sample TV/1.0"',
    '203.0.113.7 - - [18/Oct/2026:10:00:00 +1100] "GET /Users/AuthenticateByName HTTP/1.1" 401 0 "-" "Sample TV/1.0"',
    '203.0.113.7 - - [18/Oct/2026:10:00:00 +1100] "GET /Items/abc HTTP/1.1" 401 0 "-" "Sample TV/1.0"',  # stale token
    '203.0.113.7 - - [18/Oct/2026:10:00:00 +1100] "POST /Sessions/Playing HTTP/1.1" 401 0 "-" "Sample TV/1.0"',
]


def _jail() -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=True)
    cp.read_string(JAIL.read_text(encoding="utf-8"))
    return cp


def test_fail2ban_numbers_and_regex():
    jail = _jail()["jellyfin-auth"]
    assert jail["enabled"] == "true"
    assert jail["filter"] == "jellyfin-auth"
    assert (jail["maxretry"], jail["findtime"], jail["bantime"]) == ("5", "600", "3600")
    assert jail["logpath"] == "/config/log/nginx/access.log"  # SWAG's own log: the real client IP (WP0 (k))

    flt = configparser.ConfigParser(interpolation=None)
    flt.read_string(FILTER.read_text(encoding="utf-8"))
    regexes = [r for r in flt["Definition"]["failregex"].splitlines() if r.strip()]
    assert regexes
    compiled = [re.compile(r.strip().replace("<HOST>", r"(?P<host>\S+)")) for r in regexes]
    for line in AUTH_401:
        hits = [m for m in (c.search(line) for c in compiled) if m]
        assert hits and hits[0].group("host") == line.split()[0], line
    for line in NOT_AUTH_401:
        assert not any(c.search(line) for c in compiled), line


def test_swags_catch_all_401_jail_is_off():
    """SWAG's stock `nginx-unauthorized` bans on ANY 401 (5 in 10 min). Jellyfin answers every request from a TV
    with a stale token with 401, so it would ban friends' households; E7's auth-only jail replaces it."""
    jail = _jail()
    assert jail["nginx-unauthorized"]["enabled"] == "false"
    ignore = set(jail["DEFAULT"]["ignoreip"].split())
    assert ignore == E6_PRIVATE  # never ban what the geo gate treats as local: the LAN and loopback


def test_fail2ban_bans_are_drop_not_reject():
    """The ADM 6.6 kernel lacks the REJECT extension for iptables-nft ("revision 0 not supported"), so fail2ban's default
    REJECT verdict records bans but never enforces them. DROP is a native nft verdict (WP-A4 step 11). Every jail
    inherits [DEFAULT]'s banaction unless it sets its own; neither may use the REJECT default."""
    jail = _jail()
    assert "blocktype=DROP" in jail["jellyfin-auth"]["banaction"]
    for name in jail.sections():
        if jail.has_option(name, "banaction"):  # a jail's own banaction must be DROP too
            assert "blocktype=DROP" in jail[name]["banaction"], name


# ---- E8: edge.env never reaches git or an image; the template names its keys ----

def test_edge_env_never_in_git_or_images():
    git = [ln.strip() for ln in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "*.env" in git  # unanchored: matches deploy/edge.env
    assert [ln for ln in git if ln.startswith("!") and ".env" in ln] == ["!*.env.example"]
    docker = [ln.strip() for ln in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()]
    assert "**/*.env" in docker  # `*` does not cross `/` in .dockerignore (review D-01)
    assert [ln for ln in docker if ln.startswith("!") and ".env" in ln] == ["!**/*.env.example"]

    example = [ln.strip() for ln in (DEPLOY / ".env.example").read_text(encoding="utf-8").splitlines()]
    uncommented = [ln.lstrip("#").strip() for ln in example]
    assert f"{TOKEN_KEY}=" in uncommented  # documented blank, value NAS-only
    assert f"{TOKEN_KEY}=" not in example  # ...and only as a comment: the token never goes in .env (Q6)
    assert any(ln.startswith("COMPOSE_PROFILES=") for ln in uncommented)
    assert "edge.env" in "\n".join(example)


def test_no_cloudflare_token_value_anywhere_in_deploy():
    """Rule 20: the key may appear blank, never with a value (step 7's git grep, offline)."""
    value = re.compile(re.escape(TOKEN_KEY) + r"=\S")
    for path in list(DEPLOY.rglob("*")) + list((REPO_ROOT / "tests" / "deploy").rglob("*.py")):
        if path.is_file() and path.suffix not in {".pyc"}:
            assert not value.search(path.read_text(encoding="utf-8", errors="ignore")), path

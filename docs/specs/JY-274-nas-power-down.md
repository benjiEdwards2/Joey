# JY-274 Server page: "Power down NAS" button

Status: ready (B. 2026-11-05: "Take defaults" on the options page https://claude.ai/artifact/XLwxwZ1SmTL7GQcPnRVByb; building 2026-11-05)
Size: M
Live risk: HIGH (the button powers off the host that runs the hub itself)
Area: `hub/server.py` (new `hub/server_power.py` beside `server_stack.py`), `hub/templates/server.html`, a new `server_power.html` confirm page, a host-side helper (Option A script or Option B sidecar under `stackctl/`-style folder), `tests/hub/`
Needs: B.'s answers to Q1-Q6; deploy window only (07:00-21:30)
Options page: yes (button place + confirm), desktop / iPad / phone / TV

## Problem
B., 2026-11-02: "I would like a button sitting at the top of the page that allows me to power down the NAS. Is this possible? Is there a way to have it run its own code to turn off the system?" Review question Q11: confirm step, who may press it, how it powers back on. JY-170 (NAS 24/7) is the opposite ask; B. keeps the power-off for now.

## What the code does today
- The hub runs as a container ON the NAS, so "power down the NAS" also kills the page that asked for it.
- The hub has no way to reach the host's shell. Today it only talks to peers over HTTP: WUD, and `stackctl` (`hub/server_stack.py`), a tiny bearer-token helper container with the Docker socket that restarts the media stack. That is the precedent for a host-side helper.
- Deploys use ssh from the PC to the NAS as root (`deploy/deploy.sh`); the hub has no ssh key.
- `CLAUDE.md`: the NAS is off 22:00-07:00 on the DSM power schedule; deploy only 07:00-21:30; secrets only in git-ignored `.env`.
- The Server page already has a confirm-page pattern (`server_stack.html`, `server_update_all.html`) and a `same_origin` POST that redirects with a `?flash=` code. Reuse it.
- Wake-on-LAN: nothing in the repo or docs records whether the NAS supports it. Unknown (Q3).

## Mechanism options
- A. Host script via one-shot ssh key. A small script on the host (`power-down.sh`) runs `shutdown -h +1`. The hub container holds a key restricted in `authorized_keys` to that one command (`command=...,no-pty,no-port-forwarding`). Trade-off: a private key sits in the hub's `.env`/volume; if the hub is compromised the attacker can only run that one command, but the host's sshd must accept a key from the container network.
- B. Sidecar with the docker socket. A new tiny helper, built like `stackctl` (bearer token, 202 / 409, status endpoint), started with host PID access, that runs `shutdown -h +1` (or `docker run --privileged` host shutdown). Trade-off: the Docker socket is root on the host, but the helper exposes only one endpoint and the hub gets no socket; same trust model B. already accepted for `stackctl`.
- C. DSM web API. Hub calls the DSM power endpoint with an admin session. Trade-off: needs an NAS admin password in the hub, and DSM sessions/2FA make it fragile. Not recommended.
- Recommendation: B. It copies a pattern already live, keeps credentials to one bearer token, and is the easiest to fake in tests.

## Flow (all options)
1. Owner opens the confirm page; it states what will happen, the time, and how the NAS comes back.
2. Owner types `POWER DOWN` and posts. The hub checks owner, same-origin and the typed text.
3. The hub asks the helper for a delayed shutdown (60 s) and gets 202. The hub writes the log line first, then renders "Shutting down in 60 s. The page will stop answering."
4. The delay lets the response, the log write and the SQLite flush finish before the host stops containers. The helper refuses a second request while one is pending.
5. A cancel within the delay is out of scope unless Q5 says yes.

## Acceptance criteria
1. The button sits at the top of the Server page, owner only; friends and guests never see it and get 403 on the route (reuse the owner check from `hub/identity.py`).
2. No one-click path: GET shows the confirm page only; POST without the typed text, from another origin, or without owner does nothing and shows why.
3. A valid POST calls the helper exactly once and the page shows "shutting down" before the hub stops; a second POST while pending shows "already pending".
4. A helper that is unreachable, refuses, or is unconfigured shows an error and the NAS is untouched; the button is hidden when `POWER_URL` / `POWER_TOKEN` are unset (as stackctl).
5. Every attempt is logged (who, when, outcome; no tokens) and the Server page shows "Last shutdown: <relative time> by <name>" from that log; "none yet" when empty.
6. The confirm page says how it powers back on: the 07:00 DSM schedule, plus Wake-on-LAN only if Q3 confirms support.
7. A request is allowed at any hour; after 21:30 the confirm page warns that friends are cut off (Q4 may change this).
8. The token never appears in a template, log, test or PR; `deploy/*.env.example` lists the new keys.
9. Tests use a fake host runner (an in-process stub the hub is pointed at); no test, build step or preview ever calls the real NAS or real helper.
10. Page budget: Server page p95 unchanged (no new request on load; the "last shutdown" line reads the local log).

## Data
One append-only log (`power.log` in the hub data dir, or a `power_events` table in `media.db`): time, user, outcome. Builder picks the table if a migration is trivial.

## Performance budget
Server page <= 3 s and never blocks; the request returns in <= 2 s (202 from the helper, 2 s cap).

## Out of scope
Restart / reboot, power-on from the page (the hub is off), scheduled shutdowns, changing the DSM schedule (JY-170), UPS integration, Joey TV UI for the button (TV shows the line only).

## Accept checklist
- [ ] Button visible to B. only, at the top, on desktop, iPad and phone.
- [ ] Typed confirm required; wrong text does nothing.
- [ ] On the fake runner: shutdown requested once, log line written, "last shutdown" line updates.
- [ ] B. approves one live shutdown inside a day window with him present, after merge and deploy.

## Questions for B.
1. Mechanism: A. ssh key, B. sidecar like stackctl (recommended), C. DSM API.
2. Who may press: A. B. only (recommended), B. any signed-in admin.
3. Does the NAS support Wake-on-LAN (BIOS/DSM setting, and can the PC or phone send it)? If not, the only power-on is the 07:00 schedule or the physical button; is that OK?
4. After 21:30 or before 07:00: allow, warn, or block?
5. Add a "Cancel" during the 60 s delay?
6. Should the shutdown also stop the media stack cleanly first (slower, safer for downloads)?

## 2026-11-05 additions (from JY-324)
- B.: "shut down the system with a button press at night" / "NAS services too" / "set up a lot of them later on with home assistant where I can just tell my phone Goodnight and it will turn off the Nas system for now. That is an idea to look at post installation for the NAS system."
- So the power-down must be ONE action a later Home Assistant automation can call (a token-gated POST on the hub or the helper itself), not only a page button. Option B (sidecar) already gives that endpoint.
- Note: the host is an Asustor NAS running ADM (docs/PLAN.md), not DSM; read "DSM" above as ADM (Settings, Hardware, Power for the schedule). Wake-on-LAN support on ADM still unknown (Q3).

## Decisions (B. 2026-11-05 "Take defaults")
- Q1 mechanism: B, a sidecar like `stackctl` (bearer token, one endpoint, 202/409, status endpoint). Also the hook Home Assistant calls later.
- Q2 who: B. only (owner check from `hub/identity.py`).
- Q3 Wake-on-LAN: assume none; power-on = the 07:00 ADM schedule or the physical button. The confirm page says so.
- Q4 after 21:30 / before 07:00: allow, with a warning that friends are cut off until 07:00.
- Q5 cancel during the 60 s: no.
- Q6 stop the media stack cleanly first: yes (the helper stops the media compose project, waits up to 60 s, then `shutdown -h now`; the hub's own 60 s delay runs in parallel so the page answers first).
- Q7 placement: A, the red "Power down" pill in the Server page header row; TV shows the "Last shutdown" line only.
- Host is Asustor ADM: `shutdown -h now` (or `poweroff`) from the helper with host PID namespace; builder documents the exact command in `deploy/README.md` and the operator proves it on the live test (accept checklist).

## Shipped notes

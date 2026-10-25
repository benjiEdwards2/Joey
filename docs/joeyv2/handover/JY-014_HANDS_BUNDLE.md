# JY-014 — B.'s hands bundle (one sitting, ~10 min)

Drafted 2026-10-23 by the Joey orchestrator while JY-012 (preview slot) builds. Do these in one go; Claude checks each one afterwards.

## 1. Allow rules (laptop, ~2 min)
Already there (no action): `gh pr merge *`, `gh api *`, `gh run *`, `ssh -i ~/.ssh/joey_nas root@192.168.68.59 *`, `scp -i ~/.ssh/joey_nas *`.

Open `C:\Users\b.edwards\Documents\Claude\.claude\settings.local.json` in Notepad. Inside the `"allow": [` list, add these lines after `"Bash(gh pr merge *)",`:

```
      "Bash(git push *)",
      "Bash(git -C * push *)",
      "Bash(gh pr create *)",
      "Bash(gh pr edit *)",
      "Bash(gh pr comment *)",
      "Bash(python scripts/joey.py *)",
      "Bash(python scripts/budgets.py *)",
      "Bash(ssh -i ~/.ssh/joey_nas -o BatchMode=yes -o ConnectTimeout=10 root@192.168.68.59 *)",
```
Save. (Claude then runs one test push and one merge to prove them.)

## 2. Cloudflare: preview hostname (~4 min)
1. one.dash.cloudflare.com → Networks → Tunnels → `joey-nas` → Configure → Public Hostnames → **Add a public hostname**.
2. Subdomain `preview`, Domain `joeyhome.net`, Path empty. Service: Type `HTTP`, URL `joey-preview:8000`. Save hostname.
3. Access → Applications → `Joey` → Edit → Overview (or "Application domain") → **Add domain**: subdomain `preview`, domain `joeyhome.net`. Save application. (Same policy as Joey: only you two.)
Check (Claude): `curl -I https://preview.joeyhome.net` → 302 to `*.cloudflareaccess.com`.

## 3. Laptop stays on 24/7 (~2 min)
- Sleep on AC: **already Never** (read 2026-10-23 with `powercfg`: standby AC 0, hibernate AC 0). No action.
- Lid close: `powercfg` cannot read it on this laptop (likely set by Interroll policy). Control Panel → Hardware and Sound → Power Options → **Choose what closing the lid does** → "When I close the lid" → **Plugged in: Do nothing** → Save changes. If the drop-down is greyed out, policy owns it: keep the lid open instead.

## 4. Say "full permission" once
In the Joey orchestrator session, one message: `full permission` (Q4 A).

## NAS window (Claude, same window, no action from B.)
- Repoint the NAS clone's remote from `benjiEdwards2/life-dashboard` (read 2026-10-23) to `git@github.com:benjiEdwards2/Joey.git`, then a read-only `fetch` to prove the deploy key still works.
- JY-012 live run: `preview up main` → `/healthz` → memory ≥ 1,200 MB → `preview down`.

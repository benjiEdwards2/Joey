#!/bin/sh
# JY-274: powerctl install steps 1-5 of powerctl/NAS_INSTALL.md as one run (NAS, root, inside the deploy window).
# Prints PASS/FAIL per step. Never prints the token. Idempotent: an existing powerctl.env token is reused.
# Does NOT run deploy.sh --force (step 4b): run that after this script passes.
set -u
D=/volume1/Docker/joey/life-dashboard/deploy
cd "$D" || { echo "FAIL cd $D"; exit 1; }
ok(){ echo "PASS $1"; }; bad(){ echo "FAIL $1"; FAILED=1; }; FAILED=0

# 1+2 token + powerctl.env
if [ -s powerctl.env ] && grep -q '^POWERCTL_TOKEN=[0-9a-f]\{64\}$' powerctl.env; then
  TOKEN=$(sed -n 's/^POWERCTL_TOKEN=//p' powerctl.env); ok "1-2 powerctl.env exists, token reused"
else
  TOKEN=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  printf 'POWERCTL_TOKEN=%s\n' "$TOKEN" > powerctl.env && chmod 600 powerctl.env && ok "1-2 token made, powerctl.env written (600)" || bad "1-2 write powerctl.env"
fi

# 3 profile
if grep -q '^COMPOSE_PROFILES=.*\bpower\b' .env; then ok "3 COMPOSE_PROFILES already has power"
elif grep -q '^COMPOSE_PROFILES=' .env; then sed -i 's/^COMPOSE_PROFILES=\(.*\)$/COMPOSE_PROFILES=\1,power/' .env && ok "3 power added to COMPOSE_PROFILES ($(sed -n 's/^COMPOSE_PROFILES=//p' .env))"
else echo 'COMPOSE_PROFILES=power' >> .env && ok "3 COMPOSE_PROFILES=power set (no profiles before)"; fi
docker compose up -d --build powerctl >/tmp/powerctl-up.log 2>&1 && ok "3 powerctl up" || { bad "3 compose up (tail):"; tail -5 /tmp/powerctl-up.log; }
sleep 3; docker logs joey-powerctl 2>&1 | tail -2 | grep -q 'listening on :8811' && ok "3 powerctl listening" || { bad "3 powerctl log:"; docker logs joey-powerctl 2>&1 | tail -5; }

# 4 hub env (same token)
HUBENV=.env; [ -f hub.env ] && HUBENV=hub.env
for kv in "POWER_URL=http://powerctl:8811" "POWER_TOKEN=$TOKEN"; do k=${kv%%=*}
  if grep -q "^$k=" "$HUBENV"; then sed -i "s|^$k=.*$|$kv|" "$HUBENV"; else echo "$kv" >> "$HUBENV"; fi; done
chmod 600 "$HUBENV"; grep -q "^POWER_TOKEN=$TOKEN$" "$HUBENV" && ok "4 hub env ($HUBENV) carries POWER_URL + POWER_TOKEN; deploy.sh --force still needed" || bad "4 hub env write"

# 5 prove the parts, no power-off
L1=$(docker exec joey-powerctl nsenter -t 1 -m -u -i -n -p -- sh -c 'command -v poweroff; uname -n' 2>&1); echo "$L1" | grep -q poweroff && ok "5a host poweroff + host name: $(echo $L1 | tr '\n' ' ')" || bad "5a nsenter/poweroff: $L1"
docker exec joey-powerctl nsenter -t 1 -m -u -i -n -p -- ls -l /sbin/poweroff 2>&1 | sed 's/^/     /'
L2=$(docker exec joey-powerctl docker compose -p media-server ps --format '{{.Name}}' 2>&1); N=$(echo "$L2" | grep -c .); [ "$N" -ge 1 ] && ok "5b media-server project lists $N containers" || bad "5b media-server ps: $L2"
S=$(docker exec joey-powerctl wget -qO- --header "Authorization: Bearer $TOKEN" http://127.0.0.1:8811/status 2>&1); echo "$S" | grep -q '"pending": *false' && ok "5c /status with token: idle" || bad "5c /status: $S"
docker exec joey-powerctl wget -qO- http://127.0.0.1:8811/status >/dev/null 2>&1 && bad "5d /status WITHOUT token answered (must be 401)" || ok "5d /status without token refused"
echo "mem free MB $(free -m | awk 'NR==2{print $7}')"
[ $FAILED -eq 0 ] && echo "ALL PASS" || echo "SOME FAILED"

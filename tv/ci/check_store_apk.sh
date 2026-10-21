#!/usr/bin/env bash
# CI check on the store-flavor debug APK (WP-B8 step 7): no self-updater in the store build.
#   tv/ci/check_store_apk.sh <store apk>
# The merged manifest must not carry REQUEST_INSTALL_PACKAGES or the updater's status receiver.
set -uo pipefail

apk="$1"
bt="$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)"
aapt2="$bt/aapt2"
fails=0
result() { if [ "$1" = 0 ]; then echo "PASS $2"; else echo "FAIL $2"; fails=$((fails + 1)); fi; }

perms="$("$aapt2" dump permissions "$apk" | sed -n "s/^uses-permission: name='\([^']*\)'.*/\1/p" | sort | tr '\n' ' ')"
echo "store permissions: ${perms}"
! grep -q "REQUEST_INSTALL_PACKAGES" <<<"$perms"; result $? "store flavor has no REQUEST_INSTALL_PACKAGES"
[ "$perms" = "android.permission.INTERNET " ]; result $? "store permissions = INTERNET only"
manifest="$("$aapt2" dump xmltree --file AndroidManifest.xml "$apk")"
! grep -q "UpdateStatusReceiver" <<<"$manifest"; result $? "store manifest has no updater receiver"

if [ "$fails" -ne 0 ]; then echo "${fails} store check(s) failed"; exit 1; fi
echo "all store APK checks passed"

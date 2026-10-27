#!/usr/bin/env bash
# CI checks on the built debug APK (WP-B7 steps 2-3). aapt2 is not on the laptop, so these run in Actions only.
#   tv/ci/check_apk.sh <apk> <expected package> <banner png> [lint xml]
# Prints PASS/FAIL per check and exits non-zero if any failed.
set -uo pipefail

apk="$1"; pkg="$2"; banner="$3"; lint_xml="${4:-}"
bt="$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -1)"
aapt2="$bt/aapt2"
fails=0
result() { if [ "$1" = 0 ]; then echo "PASS $2"; else echo "FAIL $2"; fails=$((fails + 1)); fi; }

echo "aapt2: $aapt2"
badging="$("$aapt2" dump badging "$apk")"
echo "$badging" | grep -E "^(package|[a-zA-Z]*dkVersion|application-label|leanback-launchable-activity|launchable-activity|uses-permission|uses-feature)" || true

grep -q "^package: name='${pkg}'" <<<"$badging"; result $? "package is ${pkg}"
# aapt2 37 prints minSdkVersion:'28'; older aapt2 prints sdkVersion:'28'.
grep -Eq "^(min)?[sS]dkVersion:'28'" <<<"$badging"; result $? "minSdk 28"
grep -q "^leanback-launchable-activity:" <<<"$badging"; result $? "leanback-launchable-activity present"

perms="$("$aapt2" dump permissions "$apk" | sed -n "s/^uses-permission: name='\([^']*\)'.*/\1/p" | sort | tr '\n' ' ')"
echo "permissions: ${perms}"
# JY-057: Media3 ExoPlayer declares ACCESS_NETWORK_STATE and WAKE_LOCK (normal permissions, no prompt).
[ "$perms" = "android.permission.ACCESS_NETWORK_STATE android.permission.INTERNET android.permission.REQUEST_INSTALL_PACKAGES android.permission.WAKE_LOCK " ]
result $? "permissions = ACCESS_NETWORK_STATE + INTERNET + REQUEST_INSTALL_PACKAGES + WAKE_LOCK"

size="$(python3 -c 'import struct,sys; d=open(sys.argv[1],"rb").read(24); print("%dx%d" % struct.unpack(">II", d[16:24]))' "$banner")"
echo "banner: ${size}"
[ "$size" = "320x180" ]; result $? "banner is 320x180"

if [ -n "$lint_xml" ]; then
  for id in MissingLeanbackLauncher MissingTvBanner ImpliedTouchscreenHardware MissingLeanbackSupport; do
    ! grep -q "id=\"${id}\"" "$lint_xml"; result $? "lint has no ${id}"
  done
fi

if [ "$fails" -ne 0 ]; then echo "${fails} check(s) failed"; exit 1; fi
echo "all APK checks passed"

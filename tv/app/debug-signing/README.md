# DEBUG signing key: not for release

`joeytv-debug.p12` signs every **debug** build of the Joey TV shell (`net.joeyhome.media.debug`), so each CI debug
APK carries the same signature and `adb install -r` keeps the TV's cookies and settings.

- PKCS12, alias `joeytv-debug`, store and key password `android`, subject `CN=Joey TV DEBUG key - not for release, O=Joey`.
- SHA-256 certificate fingerprint `5E:91:D8:26:4B:93:0A:EF:55:A7:F4:3D:1F:95:2C:74:84:24:35:BF:5F:F4:BF:4F:22:39:2B:30:5B:DB:12:6F`.
- It is public on purpose. It is the only keystore allowed in git (`.gitignore` negation); the release key
  (`joeytv`, RSA 4096) lives outside the repo (D-P10, WP-B8/B9) and is never committed.

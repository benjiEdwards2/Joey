"""HITLIST sweep 8 (2026-10-25): JY-249..251 rows from the grouped TV session."""
p = "HITLIST.md"
s = open(p, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
lines = s.split(nl)
k = max(j for j, l in enumerate(lines) if l.startswith("| JY-248 |"))
lines[k + 1:k + 1] = [
    "| JY-249 | Flaky `test_tv_shelves_tmdb` (failed once in CI, passed on rerun) | Tests | S | idea | Seen on JY-191's CI, 2026-10-25 | — |",
    "| JY-250 | TV session fixes: 404 centring, Tonight safe area, season eyebrow 12 px, Back from episode, Diary month row | Joey TV | M | idea | Grouped TV session 2026-10-25: checks 7, 9, 13, 15, 28, 36 | — |",
    "| JY-251 | Friend sees household Follow state (\"Following George Kay\") on a TMDB title page | Media | M | idea | Grouped TV session 2026-10-25, phone width as joeytest | — |",
]
open(p, "w", encoding="utf-8", newline="").write(nl.join(lines))
cf = "scripts/hitlist_seed_check.py"
t = open(cf, encoding="utf-8").read()
end = t.index("\n]\n", t.index("SOURCES = ["))
t = t[:end] + ''.join(f'\n    ("grouped TV session (2026-10-25)", "{a}", "{b}", ""),' for a, b in [
    ("flaky tv shelves tmdb test", "JY-249"), ("TV session fixes", "JY-250"), ("friend sees household follow state", "JY-251")]) + t[end:]
open(cf, "w", encoding="utf-8").write(t)
print("sweep8 ok")

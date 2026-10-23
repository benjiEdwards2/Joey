# docs

- `setup.md` - dev clone, env files, signed-in user, Media / Awards / play-recorder settings.
- `public-edge.md` - the Jellyfin public edge (SWAG + DDNS behind compose profiles): request path, `edge.env`, first bring-up, kill switch, moving Jellyfin to another host.
- `tv-release.md` - the Joey TV Android app release runbook: cut a release, roll forward, first install (ADB, Downloader), signing key, NAS token renewal, `tv=` history tokens, updater behaviour.
- `network.md` - the Joey ↔ media stack shared Docker network: what changed in compose, the NAS `.env` follow-up, ports that could close.
- `connector-contract.md` - the frozen envelope, every feed, and the numbered live-call exceptions.
- `style-guide.md` - the MediaHub style guide Joey adopted, with Joey's dated deviations.
- `hub-changelog.md` - the dated narrative of how the hub got its current shape (architecture: `hub/README.md`).
- `server-updates-live-check.md` - the one-off live check of the Server "Update now" button.
- `joeyv2/` - how Joey is run since 2026-10-23 (MediaHub model): the JoeyV2 plan with every JY item, its decisions, research, and Jack's workflow doc.
- `reference/tech-notes.md` - lessons and gotchas by area (NAS, deploy gate, secrets, git, Windows, Jellyfin/arr, edge/TV, tests, hub UI, Media and Awards data, previews). Builders read their area before starting.
- `mockup/` - historical: the superseded Control Surface goldens (2026-10-06), kept for reference only.

Deploy runbook: `../deploy/README.md`.

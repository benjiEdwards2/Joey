# JY-049 — Transcode box for Jellyfin (research)

As of 2026-10-23. Read-only web research. Nothing on the NAS was touched. Prices are AUD, from retailer listings seen on 22–23 Oct 2026, and they change often.

## Recommendation

- **Buy an Intel Core Ultra 5 125H mini PC (MSI Cubi NUC AI 1UMG barebone) with 2×16 GB DDR5 and a 1 TB NVMe. It costs about A$1,190–1,315 built.** Its Arc iGPU is the strongest common Intel iGPU for 4K HDR → 1080p SDR tone mapping. It also leaves CPU and RAM spare for a GitHub Actions runner and Home Assistant.
- **Run Linux on bare metal (Ubuntu Server 24.04 LTS) with Docker Compose.** Don't use Windows with Docker Desktop. Jellyfin's docs say Quick Sync "is not available on Windows Docker and WSL/WSL2", so Jellyfin in Docker on Windows would fall back to the CPU.
- **Architecture: start with option (a).** The box runs Jellyfin and the runner, and the media stays on the NAS over NFS. Later, move the RAM-hungry NAS containers across, which is option (b).
- **Budget fallback: ASUS NUC 14 Essential N150, about A$475–600 built.** It is good for 1–2 tone-mapped streams. It is capped at 16 GB of single-channel RAM.

## 1. What Jellyfin needs

| Intel iGPU generation | H.264 | HEVC 8-bit | HEVC 10-bit (needed for HDR) | VP9 decode | AV1 decode | AV1 encode |
|---|---|---|---|---|---|---|
| 6th gen Skylake | Yes | Yes | No | Partial | No | No |
| 7th–10th gen, Gemini Lake | Yes | Yes | Yes | Yes | No | No |
| 11th–14th gen (UHD 7xx / Iris Xe), N100/N150/N305 | Yes | Yes | Yes | Yes | Yes | No |
| Core Ultra (Meteor/Arrow Lake Arc iGPU), Arc dGPU | Yes | Yes | Yes | Yes | Yes | Yes |

- **HDR → SDR tone mapping** works on any Intel GPU that can decode HEVC 10-bit. There are two methods. OpenCL has more tuning and supports Dolby Vision Profile 5. QSV VPP draws less power and is Linux-only. Tone mapping is the heavy part. Plain 4K → 1080p without HDR is roughly 4–6× cheaper.
- **Jellyfin's ranking:** Intel QSV is the recommended path. NVIDIA works but needs more driver effort and a discrete card. The docs say "AMD is NOT recommended" for iGPU transcoding. Intel has no limit on concurrent encode sessions; NVIDIA NVENC does.
- **Avoid:** CPUs with an "F" suffix (no iGPU). Avoid 7th–10th gen for new purchases, because Intel deprecated their toolkit.
- **Other needs:** the OS and Jellyfin data on an SSD (≥100 GB) and wired gigabit Ethernet or faster. Remote use needs ≥20 Mbps upload.

## 2. Simultaneous 4K HDR → 1080p SDR transcodes (tone-mapped)

| iGPU | Streams | Basis |
|---|---|---|
| N100 / N150 (24 EU, single-channel RAM) | ~1–2 | Estimate (user reports and review commentary) |
| N305 (32 EU) | ~2 | Estimate |
| i3-12100 / UHD 730 | 1 | Forum report, 2023 (older drivers) |
| i5-12500–14500 / UHD 770 (2 media engines) | ~2–3 | Estimate. A forum claim of 5 is untested. |
| Tiger Lake Iris Xe (96 EU) | 4–5 | **Measured** (computingforgeeks, Oct 2026) |
| Core Ultra 5 125H Arc (7 Xe-cores) | ~5+ | Estimate (rated above the measured Iris Xe) |

**Reality check:** home upload is 32.5 Mbps. That carries only about 2–3 remote 1080p streams at once, so 2–3 tone-mapped transcodes is the real target. The Core Ultra gives that with headroom. The N150 is borderline.

## 3. Architecture

| Option | What runs on the box | Pros | Cons |
|---|---|---|---|
| **(a) Jellyfin box** (recommended start) | Jellyfin, GitHub runner, maybe Home Assistant. Media read from NAS over NFS (read-only). | Smallest change. Takes the heaviest container off the swapping NAS. | Media is unavailable 22:00–07:00 while the NAS is off. |
| (b) Box takes most of the stack | Above, plus Radarr/Sonarr/Prowlarr/Seerr, qBittorrent + gluetun, Joey hub | NAS becomes plain storage, so the swapping ends | Bigger migration. Downloads write to the NAS over the LAN. |
| (c) Keep the NAS, add RAM / pre-transcode | Nothing new | Cheapest | J4125 iGPU is too weak for HDR tone mapping. Doesn't fix the goal. |

- **Network:** 1 GbE is enough. A 4K remux is about 40–100 Mbps per stream. The NAS has 2×2.5 GbE, so 2.5 GbE on the box is a nice-to-have for bulk copies, not a requirement.
- **NAS off-hours:** Jellyfin and runner deploys will fail 22:00–07:00. Keep Jellyfin's config and metadata on the box's SSD. Don't schedule library scans while the share is offline, so items aren't flagged missing. Run the box 24/7 or on the same hours as the NAS. Cost barely differs (see below).

## 4. Shortlist (Australia)

| | Budget | Comfortable (recommended) | Ready-built alternative |
|---|---|---|---|
| Machine | ASUS NUC 14 Essential N150 barebone (RNUC14MNK1500000) | MSI Cubi NUC AI 1UMG-011BAU barebone | MINISFORUM M1 Pro-125H |
| CPU / iGPU | N150, 4C/4T / 24 EU UHD | Core Ultra 5 125H, 14C/18T / Arc 7 Xe-cores | Core Ultra 5 125H / Arc |
| Base price | A$199 (MSY, Umart). Scorptec A$309, PLE A$349. | A$559 (MSY, Umart) | A$989.99 for 32 GB / 512 GB (Amazon AU search snapshot, not confirmed on page) |
| RAM | 1× DDR5 SO-DIMM, max 16 GB. Add 16 GB ≈ A$168. | 2× DDR5 SO-DIMM. Add 2×16 GB ≈ A$529. | Included |
| Storage | Add 1 TB NVMe ≈ A$97–225 | Add 1 TB NVMe ≈ A$97–225 | 512 GB included |
| LAN | 1× 2.5 GbE | 2× 2.5 GbE, 2× Thunderbolt 4 | 2.5 GbE (count not confirmed) |
| Idle power | ~6–12 W (measured on other N150 boxes) | ~10 W short idle (ENERGY STAR, 155H sibling, Windows). Linux is likely lower. | ~10 W (estimate) |
| **Built total** | **≈ A$475–600** (+ mains cord, "No Cord" listing) | **≈ A$1,190–1,315** | ≈ A$990 |
| Link | [MSY](https://www.msy.com.au/product/asus-nuc-14-essential-barebone-kit-intel-n150-no-cord-rnuc14mnk1500000-87046) · [PLE](https://www.ple.com.au/products/672688/asus-nuc-14-essential-celeron-n150-barebones-mini-pc) | [Umart](https://www.umart.com.au/product/msi-cubi-nuc-ai-core-ultra-5-125h-barebone-mini-pc-cubi-nuc-ai-1umg-011bau-85437) · [MSY](https://www.msy.com.au/product/msi-cubi-nuc-ai-core-ultra-5-125h-barebone-mini-pc-cubi-nuc-ai-1umg-011bau-85437) | [Amazon AU](https://www.amazon.com.au/MINISFORUM-M1-Pro-125H-Barebone-OCuLink/dp/B0FH69812H) |

- **Parts:** RAM is [Corsair 2×16 GB DDR5-4800 at CPL](https://cplonline.com.au/corsair-cmsx32gx5m2a4800c40-vengeance-ddr5-sodimm-32gb-2x16gb-4800mhz-c40-1-1v-notebook-memory.html) or [Corsair 1×16 GB at CPL](https://cplonline.com.au/corsair-cmsx16gx5m1a4800c40-vengeance-ddr5-sodimm-16gb-1x16gb-4800mhz-c40-1-1v-notebook-memory.html). SSD is [PNY CS3040 1 TB at CPL](https://cplonline.com.au/pny-m280cs3040-1tb-rb-cs3040-1tb-m-2-nvme-gen4-x4-pcie-ssd.html) or Kingston NV3 1 TB (A$225, Umart/MSY).
- **Prices:** RAM is very expensive right now (32 GB DDR5 SO-DIMM costs A$404–599). Ready-built mini PCs have risen too. For example, a Beelink S13 Pro N150 is A$720.89 on Amazon AU, and the Beelink EQ14 is unavailable. Barebone plus parts is currently the better value.
- **Upgrade option:** the same MSI box with a Core Ultra 7 155H barebone is A$699. That gets one more Xe-core, which is a small gain.

## 5. Always-on dev box (coordinator addendum)

- **24/7 running cost** at 30 c/kWh: 1 W continuous ≈ A$2.63/yr.
  - Budget box at ~8 W average ≈ **A$21/yr**.
  - Comfortable box at ~10–15 W average, with occasional transcodes and builds ≈ **A$26–39/yr**.
  - Running on the NAS's hours only (15 h/day) saves about a third of that.
- **GitHub Actions self-hosted runner** (Linux, Docker): it needs only outbound HTTPS on port 443, so no port forward. Building preview containers is a CPU burst. The 125H's 14 cores handle a build alongside 2–3 QSV transcodes easily, because transcoding runs on the iGPU media engines and not the CPU cores. The N150's 4 cores will be slow on builds. Use private repos only: GitHub says self-hosted runners "should almost never be used for public repositories".
- **RAM sizing** (estimates):

| Service | RAM |
|---|---|
| Jellyfin | 1–2 GB, plus shared iGPU memory while tone mapping |
| Runner and Docker builds | 2–4 GB peak |
| Home Assistant Container | ~0.5–1 GB |
| Home Assistant OS in a VM | 2–4 GB |
| Option (b) services (arr apps, qBittorrent + gluetun, Joey hub) | ~2–3 GB |
| OS and page cache | 2+ GB |

16 GB fits option (a). **32 GB is recommended** for option (b) plus Home Assistant plus builds. Fit it as 2×16 GB so the iGPU gets dual-channel bandwidth, which helps tone mapping.

- **Home Assistant:** HA OS is HA's recommended install and the only one with apps (add-ons). HA Container runs in the same Docker setup but has no apps. On this box, use HA Container, or run HA OS in a KVM VM if you need apps.

## 6. Open questions for B.

1. What is the budget ceiling: about A$600 (N150) or about A$1,300 (Core Ultra 5)?
2. Where will it sit? It needs wired Ethernet near the switch or NAS.
3. Should it run 24/7, or on the NAS's 07:00–22:00 schedule?
4. Does Home Assistant go on it? If so, as HA Container, as an HA OS VM, or on a separate device?
5. Option (a) only, or plan the move to (b)? Option (b) also ends the NAS swapping.
6. Will the runner's repos all be private?

## Sources (opened 2026-10-23)

- Jellyfin, Intel hardware acceleration: https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/intel
- Jellyfin, hardware acceleration overview: https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/
- Jellyfin, selecting hardware: https://jellyfin.org/docs/general/administration/hardware-selection
- Measured Iris Xe 4–5 streams, plus estimates (updated 16 Oct 2026): https://computingforgeeks.com/best-mini-pc-plex-jellyfin/
- Forum stream reports (UHD 730/770, i3-12100): https://forum.jellyfin.org/t-hardware-for-4-5-4k-and-home-lab
- Quick Sync codec history (VP9): https://en.wikipedia.org/wiki/Intel_Quick_Sync_Video
- N150 idle measurements (Jun 2026): https://www.starryhope.com/minipcs/mini-pc-power-cost-24-7-2026/
- MSI Cubi NUC AI 1UMG ENERGY STAR record (short idle 10 W): https://www.energystar.gov/productfinder/product/certified-computers/details/4437580
- AU prices: https://www.staticice.com.au (searches for N150, 125H, DDR5 SO-DIMM, 1 TB NVMe) and the retailer pages linked above
- Home Assistant installation types: https://www.home-assistant.io/installation/
- GitHub self-hosted runner requirements: https://docs.github.com/en/actions/reference/runners/self-hosted-runners
- GitHub Actions security hardening: https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions

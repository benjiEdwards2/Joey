# JY-051 library inventory and test-file set

Read 2026-10-24 inside joey-hub with `python scripts/player_study.py inventory` (read only). Query:
`GET /Items?Recursive=true&IncludeItemTypes=Movie,Episode&Fields=MediaSources,MediaStreams&EnableImages=false&EnableUserData=false`,
paged 200 at a time, first MediaSource per item (no item has more than one). Counts and item ids only: no titles, paths or users.

## Headline
- 536 items: 488 episodes, 48 films. All have probed streams.
- 96 % MKV (512), 4 % MP4 (24). Video: HEVC 65 % (346; 313 of them 10-bit SDR), H.264 35 % (190). 533 of 536 are 1080p SDR.
- Default audio is mostly Dolby: EAC3 or AC3 on 66 % of items (353). DTS on 15, TrueHD on none.
- Subtitles: SRT 401 items, PGS 157 (29 %), VobSub 8, mov_text 2, ASS none. 24 items have no subtitles.
- The top 3 combinations are 57 % of the library; the top 15 are 94.8 % (28 combinations in all).
- Not in the library (reported, not imported): AV1, TrueHD, ASS/SSA, plain HDR10 or HLG, H.264 10-bit, legacy codecs (VC-1, MPEG-2), AVI/TS containers, anything below 1080p.

## Top 15 combinations
Container | video (codec, bit depth, range, resolution) | default audio track | subtitle kinds present.

| # | Combination | Items | % | Cum % | Sample id |
|---|---|---|---|---|---|
| 1 | mkv \| h264 8-bit SDR 1080p \| eac3 5.1 \| subs text | 127 | 23.7 % | 23.7 % | `d64f611c17a8d1e628dc0baf8625c536` |
| 2 | mkv \| hevc 10-bit SDR 1080p \| eac3 5.1 \| subs text | 98 | 18.3 % | 42.0 % | `ff2240b0477c0f0e53772543e772988d` |
| 3 | mkv \| hevc 10-bit SDR 1080p \| aac 5.1 \| subs image | 81 | 15.1 % | 57.1 % | `8e272a6eab2388ea32b247333da9794a` |
| 4 | mkv \| hevc 10-bit SDR 1080p \| aac 5.1 \| subs text | 35 | 6.5 % | 63.6 % | `75bd8094149b87b7ea659542df28341f` |
| 5 | mkv \| hevc 10-bit SDR 1080p \| eac3 5.1 \| subs image+text | 34 | 6.3 % | 70.0 % | `714ed17c3ce016d516b8707d4ba8a83e` |
| 6 | mkv \| h264 8-bit SDR 1080p \| aac 2.0 \| subs text | 26 | 4.9 % | 74.8 % | `216115751b36075634f7ace255140bbc` |
| 7 | mkv \| hevc 8-bit SDR 1080p \| eac3 5.1 \| subs text | 24 | 4.5 % | 79.3 % | `2055b49539eaf8bc3100d955b0661ccb` |
| 8 | mkv \| hevc 10-bit SDR 1080p \| eac3 5.1 \| subs image | 20 | 3.7 % | 83.0 % | `bb3ad6de105ff1becdc8978ba367b015` |
| 9 | mkv \| hevc 10-bit SDR 1080p \| ac3 5.1 \| subs text | 14 | 2.6 % | 85.6 % | `6637897d0c45630bf1eb481c8d148c3a` |
| 10 | mp4 \| hevc 10-bit SDR 1080p \| aac 5.1 \| subs none | 10 | 1.9 % | 87.5 % | `91c55b10825a46ea01cdf50ea760a6ea` |
| 11 | mkv \| h264 8-bit SDR 1080p \| dts 5.1 \| subs text | 10 | 1.9 % | 89.4 % | `fdbb56885c9e44e039ca5c0aa056d2d4` |
| 12 | mkv \| hevc 10-bit SDR 1080p \| aac 5.1 \| subs image+text | 10 | 1.9 % | 91.2 % | `60c5be8b04f6693b0a6a017af8f787ba` |
| 13 | mp4 \| h264 8-bit SDR 1080p \| aac 2.0 \| subs none | 8 | 1.5 % | 92.7 % | `dcd12e5bf6856e60c225472186cd6cb6` |
| 14 | mkv \| hevc 8-bit SDR 1080p \| aac 5.1 \| subs text | 6 | 1.1 % | 93.8 % | `9163544383ca5c53cfeb18c3bfa85ea8` |
| 15 | mkv \| h264 8-bit SDR 1080p \| eac3 5.1 \| subs image+text | 5 | 0.9 % | 94.8 % | `27fc3c0e870d502967749ddadf8f4816` |

## Rare and hard properties
An item counts once per property (any track).

| Property | Items | % | Sample ids |
|---|---|---|---|
| AC3/EAC3 audio | 353 | 65.9 % | `6637897d0c45630bf1eb481c8d148c3a`, `bb3ad6de105ff1becdc8978ba367b015`, `d64f611c17a8d1e628dc0baf8625c536` |
| HEVC 10-bit SDR | 313 | 58.4 % | `6637897d0c45630bf1eb481c8d148c3a`, `bb3ad6de105ff1becdc8978ba367b015`, `91c55b10825a46ea01cdf50ea760a6ea` |
| PGS subtitles | 157 | 29.3 % | `bb3ad6de105ff1becdc8978ba367b015`, `8e272a6eab2388ea32b247333da9794a`, `644337b3ec4f5fe0e504c7c9237a3c44` |
| Multi-audio | 49 | 9.1 % | `75bd8094149b87b7ea659542df28341f`, `f353569994df95433990a5b1daac948e`, `12677371d71c9072d496f68f76d93217` |
| External subtitles | 37 | 6.9 % | `fdbb56885c9e44e039ca5c0aa056d2d4`, `ce49a6b29bb46e5402542a03cf201312`, `d11043d8eb826214e19aac269df0e926` |
| DTS (incl. DTS-HD MA) | 15 | 2.8 % | `fdbb56885c9e44e039ca5c0aa056d2d4`, `ce49a6b29bb46e5402542a03cf201312`, `d11043d8eb826214e19aac269df0e926` |
| 7.1 audio | 11 | 2.1 % | `51a2003ebcbce12e58ae829bf58d7e58`, `a7c02d4aef1aedeabbdbbaf7d419d71b`, `3aac99a6e9d06ca476ee9d39d1835508` |
| VobSub subtitles | 8 | 1.5 % | `910c6153145342b775e9fbaa911d11aa`, `c84274f91a599e8c94d1cff221f94bf8`, `51a2003ebcbce12e58ae829bf58d7e58` |
| HEVC 10-bit HDR (all Dolby Vision with HDR10 fallback, 2160p) | 3 | 0.6 % | `2da3a189e2c7f9d7166cb63aeb849b23`, `0fc19ee50e310c68987dd14714e824da`, `5235524f5a9b1209d17e5d54ef000554` |
| Bitrate over 40 Mbps | 1 | 0.2 % | `b171da2503dbcb65d7e9aeffee75b9f0` |
| AV1, TrueHD, ASS, H.264 10-bit, legacy codecs, other containers | 0 | 0 % | none |

Other counts. Audio languages (items with a track): eng 532, ita 24, und 4, spa 2, one each fra, dan, fin, isl, nor, swe.
Channels (any track): 5.1 on 503, 2.0 on 45, 7.1 on 11. Bitrate: under 5 Mbps 276, 5 to 10 Mbps 223, 10 to 20 Mbps 34, 20 to 40 Mbps 2, over 40 Mbps 1.

## Test-file set (12)
Stream indexes are Jellyfin `MediaStream.Index`; "on" means the study selects that subtitle track. The same list is `TEST_ITEMS` in `scripts/player_study.py`.

| # | Item id | Type | Tests | Size, bitrate, length |
|---|---|---|---|---|
| 1 | `dcd12e5bf6856e60c225472186cd6cb6` | Episode | Control: MP4, H.264 High 8-bit, AAC 2.0, no subtitles | 0.65 GB, 2.0 Mbps, 44 min |
| 2 | `d64f611c17a8d1e628dc0baf8625c536` | Episode | Top combination (23.7 %): MKV, H.264, EAC3 5.1 (Atmos), SRT #2 on | 2.3 GB, 6.6 Mbps, 51 min |
| 3 | `ff2240b0477c0f0e53772543e772988d` | Episode | Second combination (18.3 %): MKV, HEVC Main 10 SDR, EAC3 5.1, SRT #2 on | 1.7 GB, 4.2 Mbps, 53 min |
| 4 | `8e272a6eab2388ea32b247333da9794a` | Episode | Third combination (15.1 %): MKV, HEVC Main 10, AAC 5.1, PGS #2 on | 2.4 GB, 5.8 Mbps, 60 min |
| 5 | `91c55b10825a46ea01cdf50ea760a6ea` | Episode | HEVC Main 10 in MP4 with AAC 5.1 (browser HEVC direct play) | 1.2 GB, 2.2 Mbps, 73 min |
| 6 | `2da3a189e2c7f9d7166cb63aeb849b23` | Movie | 2160p Dolby Vision + HDR10 in MP4, EAC3 5.1, two audio tracks, mov_text #3 on | 5.6 GB, 15.6 Mbps, 48 min |
| 7 | `0fc19ee50e310c68987dd14714e824da` | Movie | Worst case: MKV 2160p DV + HDR10, 34 Mbps, DTS-HD MA default, PGS #5 on | 50.6 GB, 34.4 Mbps, 196 min |
| 8 | `fdbb56885c9e44e039ca5c0aa056d2d4` | Episode | DTS 5.1 core, H.264, external SRT #0 on | 3.5 GB, 11.1 Mbps, 42 min |
| 9 | `910c6153145342b775e9fbaa911d11aa` | Movie | VobSub (DVDSUB) #3 on, HEVC Main 10, two AAC tracks | 5.7 GB, 7.5 Mbps, 101 min |
| 10 | `75bd8094149b87b7ea659542df28341f` | Episode | Multi-audio: default track is Italian, study picks English #2 | 0.9 GB, 2.4 Mbps, 59 min |
| 11 | `51a2003ebcbce12e58ae829bf58d7e58` | Movie | AAC 7.1 (8 channels) default | 7.6 GB, 5.7 Mbps, 176 min |
| 12 | `b171da2503dbcb65d7e9aeffee75b9f0` | Movie | Highest bitrate: H.264 45.6 Mbps, DTS-HD MA 7.1, five AC3 tracks, PGS #7 default on | 24.3 GB, 45.6 Mbps, 88 min |

## PC browser PlaybackInfo (scripts/player_study.py playback)
Measured 2026-10-24 12:04 (Melbourne) inside joey-hub with `python scripts/player_study.py playback`: the container's
API key acting for joeytest through `POST /Items/{id}/PlaybackInfo?userId=<joeytest id>` (+ `UserId` in the body;
the id resolved by its prefix `0dd9fd89` from `GET /Users`, only the prefix printed). Jellyfin 12.2 accepts this: all
12 items answered, so the PC table needs no user token. (The bare API key without a user had failed on every item
with HTTP 400, "Guid can't be empty".) Read only: no stream was requested. DeviceProfile: the stated desktop-Chrome
profile in `scripts/player_study.py` (the sitting replaces it with what each browser really decodes).

| # | Item id | Method | Reasons | Out video / audio | Subs |
|---|---|---|---|---|---|
| 1 | `dcd12e5bf6856e60c225472186cd6cb6` | DirectPlay | - | - | - |
| 2 | `d64f611c17a8d1e628dc0baf8625c536` | Remux + audio transcode | ContainerNotSupported, AudioCodecNotSupported | hevc,h264 / aac,mp3,opus,flac | - |
| 3 | `ff2240b0477c0f0e53772543e772988d` | Remux + audio transcode | ContainerNotSupported, AudioCodecNotSupported | hevc,h264 / aac,mp3,opus,flac | Encode |
| 4 | `8e272a6eab2388ea32b247333da9794a` | Remux | ContainerNotSupported | hevc,h264 / aac | - |
| 5 | `91c55b10825a46ea01cdf50ea760a6ea` | DirectPlay | - | - | - |
| 6 | `2da3a189e2c7f9d7166cb63aeb849b23` | Video transcode | AudioCodecNotSupported, VideoRangeTypeNotSupported | hevc,h264 / aac,mp3,opus,flac | - |
| 7 | `0fc19ee50e310c68987dd14714e824da` | Video transcode | AudioCodecNotSupported, ContainerBitrateExceedsLimit | hevc,h264 / aac,mp3,opus,flac | - |
| 8 | `fdbb56885c9e44e039ca5c0aa056d2d4` | Remux + audio transcode | ContainerNotSupported, AudioCodecNotSupported | hevc,h264 / aac,mp3,opus,flac | - |
| 9 | `910c6153145342b775e9fbaa911d11aa` | Remux | ContainerNotSupported | hevc,h264 / aac | - |
| 10 | `75bd8094149b87b7ea659542df28341f` | Remux | ContainerNotSupported | hevc,h264 / aac | - |
| 11 | `51a2003ebcbce12e58ae829bf58d7e58` | Remux + audio transcode | ContainerNotSupported, AudioChannelsNotSupported | hevc,h264 / aac,mp3,opus,flac | Encode |
| 12 | `b171da2503dbcb65d7e9aeffee75b9f0` | Video transcode | AudioCodecNotSupported, ContainerBitrateExceedsLimit | hevc,h264 / aac,mp3,opus,flac | Encode |

Against the prediction below: every method as predicted except rows 4 and 9 (remux, not a video transcode). Open
questions for the sitting:
- Rows 7 and 12 give `ContainerBitrateExceedsLimit` (34 and 45.6 Mbps) although the profile allows 120 Mbps: joeytest's
  friend policy cap (20 Mbps remote) seems to apply to this in-container call, so Jellyfin may see the Docker bridge as
  remote here. On the LAN in the sitting the cap should not apply; the PC rows 7 and 12 show which.
- Rows 4 and 9 (PGS, VobSub selected) remux with no `SubtitleMethod` in the URL instead of burning in, and rows 3 and
  11 say `Encode` for a text subtitle (row 3) and for no chosen subtitle (row 11). The sitting shows what is really on
  screen.

Predicted from the stated profile (before the measurement) (desktop Chrome, hardware HEVC, SDR monitor, no MKV, no AC3/EAC3/DTS decode, no PGS
or VobSub renderer), to be replaced by the measured table:

| # | Predicted | Why |
|---|---|---|
| 1, 5 | Direct play | MP4 with codecs Chrome decodes |
| 2, 3, 8 | Remux + audio transcode | MKV is not direct-play; video copied into HLS; EAC3/DTS to AAC; SRT sent as a sidecar |
| 10 | Remux | MKV only; second AAC track copied |
| 11 | Remux + audio transcode | 8 channels over the 6-channel cap: downmix |
| 4, 9, 12 | Video transcode | PGS / VobSub selected: burned in |
| 6, 7 | Video transcode | Dolby Vision / HDR10 on an SDR display: tone-mapped 2160p HEVC 10-bit, the J4125 worst case |

Library-wide, on these predictions: with subtitles off, 22 items (4.1 %, the SDR MP4s with AAC) direct-play, the two
Dolby Vision MP4s and the one DV MKV transcode, and the rest remuxes
(two thirds of it with audio transcoding, from EAC3/AC3/DTS); every PGS or VobSub subtitle turned on means a video
transcode (165 items carry one).

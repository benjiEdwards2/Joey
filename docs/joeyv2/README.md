# JoeyV2 — how Joey is run

JoeyV2 is the same Joey app, run the way Jack's MediaHub workflow describes: an orchestrator writes specs, builder agents build one item each, a different agent reviews, and B. accepts before anything merges.

| File | What it holds |
| --- | --- |
| [JOEYV2_PLAN.md](JOEYV2_PLAN.md) | The plan: the review of how Joey ran before, the phases and every JY item (§4), the answered questions (§6) |
| [DECISIONS.md](DECISIONS.md) | Dated decisions for JoeyV2, newest at the bottom |
| [MEDIAHUB_WORKFLOW.md](MEDIAHUB_WORKFLOW.md) | A copy of Jack's "The MediaHub Workflow" doc (shared 2026-10-23), the source of the model |
| [research/](research/) | Research items, e.g. JY-049 transcoding box |

The backlog is `HITLIST.md` at the repo root (JY-004), and the rules every agent reads are in `CLAUDE.md` (JY-001).

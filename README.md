# FB Autoposter — PoC

Automated pipeline: **topic research → caption → image → Facebook Page post**, on a schedule, for under ~$2/month.

## Architecture

```
GitHub Actions cron (free)
        │  daily trigger
        ▼
autoposter.py
  1. Load config.yaml (client-editable criteria/prompts)
  2. LLM call (Claude Haiku) → topic + caption + image prompt   [~$0.01/post]
  3. Duplicate guard — checks history.json, skips if too similar
  4. fal.ai FLUX schnell → image URL                            [~$0.003–0.025/post]
  5. POST graph.facebook.com/{page_id}/photos (url + caption)   [free]
  6. Append to history.json (dedupe memory), commit back to repo
```

One LLM call per post produces topic, caption, and image prompt together — no separate "research" and "writing" calls, which keeps cost and failure surface minimal. The Graph API fetches the image directly from fal.ai's hosted URL, so no image storage is needed.

## Client controls (no code)

Two ways to drive the system, no backend editing required:

**1. Web control panel (local).** Run `python control_panel.py` and open `http://localhost:8000`. Form fields for topic criteria, caption style, image style, and optional exact post text; checkboxes for Dry-run (safe preview) and Mock image (no fal.ai spend); a **Save** button (writes `config.yaml`) and **Save & Run now** which runs the pipeline and shows the generated caption, image preview, and log inline. This is the client-facing surface — nothing but the form to interact with.

**2. Cloud schedule (unattended).** The GitHub Actions workflow runs on a cron (free tier) using the same `config.yaml` the panel saves. Workflow: client edits + previews locally in the panel with Dry-run on, commits/pushes `config.yaml`, then the cloud posts on schedule. They can also hit "Run workflow" in the Actions tab for an on-demand run.

Everything either surface changes lives in one `config.yaml`: topic criteria, caption/image style, image model/size, dedupe window, retry policy, and the `dry_run` / `mock_apis` switches.

## Error handling

- **Retries:** every external call retries up to 3× with exponential backoff (5s → 10s → 20s), configurable.
- **Duplicates:** topics are fingerprinted; exact matches and >70% word-overlap matches within the lookback window (default 60 days) are skipped.
- **No orphan posts:** if image generation fails, nothing is published. If publish fails, the topic is *not* recorded, so the next run retries fresh.
- **Skip, don't crash:** any unrecoverable failure logs the reason and exits cleanly; the next scheduled run proceeds normally.
- **Dry-run mode:** full pipeline executes but logs the exact Facebook API call instead of posting.
- **Mock mode:** runs with zero API keys (local topic generator + placeholder image) — used for this demo.

## Setup (live mode)

1. Create a Meta app, add the Page, grant `pages_manage_posts` + `pages_read_engagement`, and generate a **long-lived Page access token**.
2. Get API keys: Anthropic (or any cheap LLM) and fal.ai.
3. Push this folder to a GitHub repo; add the three keys as Actions secrets (see `.env.example`).
4. In `config.yaml`, set `page_id`, and set `dry_run: false`, `mock_apis: false`.
5. Adjust the cron line in `.github/workflows/post.yml` for posting time/frequency.

## Estimated monthly running cost (30 posts/month)

| Item | Cost |
|---|---|
| LLM (Claude Haiku 4.5, ~1.5K tokens/post) | ~$0.30 |
| Image gen (fal.ai FLUX schnell, 1MP) | ~$0.10–0.75 |
| Facebook Graph API | $0 |
| Hosting/scheduler (GitHub Actions free tier) | $0 |
| **Total** | **≈ $0.50–1.10/month** |

Doubling to 2 posts/day roughly doubles the API line items — still ~$2/month. No subscriptions anywhere in the stack.

## Extending (the "nice to haves")

- **Multiple Pages:** make `facebook:` a list in config; loop over pages per run.
- **Multiple languages:** add a `language` field per page; it's passed into the LLM prompt.
- **Better images:** switch `image_model` to `fal-ai/flux/dev` (~$0.025/image) — one config line.

## Known limitations of this PoC

- The near-duplicate check is word-overlap based; embedding-based similarity would be more robust at scale.
- Page access tokens derived from long-lived user tokens generally don't expire, but Meta can invalidate them (password change, permission audit); production version should alert on 401s.
- GitHub Actions cron can drift a few minutes; fine for social posting, use a paid scheduler if exact timing matters.

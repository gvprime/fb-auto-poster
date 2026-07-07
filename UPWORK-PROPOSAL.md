# Upwork Proposal Draft

Hi,

I've already built a working proof-of-concept of exactly this pipeline — happy to demo it on a call.

**Proposed architecture**

A single Python script on a free scheduler (GitHub Actions cron), driven entirely by one config file you edit yourself — no dashboards to pay for, no backend to touch:

1. One cheap LLM call (Claude Haiku) generates the topic, caption, and image prompt in a single step, based on your criteria and a "recently posted" list to prevent repeats.
2. fal.ai FLUX (schnell) generates the image — pay-per-use, ~$0.003–0.025 per image.
3. One Facebook Graph API call (`/{page_id}/photos`) publishes image + caption together; the API pulls the image straight from fal.ai's hosted URL, so there's no storage cost.

Error handling is built in: exponential-backoff retries on every API call, a duplicate-topic guard (exact + fuzzy match over a configurable window), and a rule that nothing is published unless every prior step succeeded — no orphan or half-finished posts. A dry-run mode lets you preview exactly what would be posted before going live.

You adjust topics, tone, image style, and posting frequency in one YAML file (editable in the browser). Multiple Pages or languages later = a few extra config lines, not a rebuild.

**Estimated monthly running cost (1 post/day)**

- LLM: ~$0.30 · Image gen: ~$0.10–0.75 · Facebook API: $0 · Hosting/scheduler: $0
- **Total: roughly $0.50–1/month.** 2 posts/day ≈ $2/month. Zero subscriptions.

**Relevant experience**

[Add: your Facebook Graph API / automation / API-integration track record here — 1–2 concrete examples with outcomes.]

I can have this live on your Page within [X days] of receiving Page access. Deliverables: the working system, setup of your Meta app + long-lived Page token, and a short doc covering how it works, how to change the prompts, and monthly cost.

Regards,
Richard

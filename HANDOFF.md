# FB Autoposter — handoff brief (for Claude Code)

## What this is
End-to-end Facebook Page autoposter PoC: generate topic -> caption -> image -> publish
to a FB Page on a schedule, cheaply. Built and partly validated already.

## Current state (DONE)
- `autoposter.py` — pipeline. Config-driven. Modes: `dry_run` (log instead of post),
  `mock_apis` (local placeholder image, no fal.ai spend), `manual_content` (use exact
  text, skip the LLM). Multipart upload path lets it post a LOCAL image with no hosting.
  Has retry/backoff + duplicate-topic guard (history.json).
- `config.yaml` — the only file the client edits. Currently dry_run: true, mock_apis: true.
- `control_panel.py` — stdlib web UI (password login, sessions) to edit prompts + preview + run.
- `.github/workflows/post.yml` — free daily cron + manual trigger. Reads 4 repo secrets.
- Deploy kit for later: `nginx-panel.conf`, `fb-autoposter-panel.service`, `DEPLOY.md`.
- `README.md` — architecture + cost (~$0.50–2/mo). `UPWORK-PROPOSAL.md` — application text.
- PROVEN: a real post was already published to Page id 1211759088691986 ("GVP Autoposter Test").

## Known environment facts
- Lightsail 54.163.82.23 is PRODUCTION (nginx on 80/443, uvicorn on 8000+8001, gvprime-* services).
  Do NOT co-host without care; panel port set to 8020 if ever deployed there. Decision so far:
  use free GitHub Actions instead of that box.
- fal.ai key exists but billing NOT funded ($10 minimum). Until funded, keep mock_apis: true.
- Anthropic key skipped; captions come from config `manual_content`. Add key + delete that
  block to auto-generate.

## Remaining steps (TODO)
1. Get this folder into WSL (you may already be running inside it).
2. git init, commit, push to github.com/gvprime/fb-auto-poster (repo may already exist, empty).
3. Add 4 GitHub Actions secrets: FB_PAGE_ACCESS_TOKEN, FB_PAGE_ID (=1211759088691986),
   FAL_KEY, ANTHROPIC_API_KEY (optional).
4. Actions tab -> Run workflow with dry_run:true to validate, read the log.
5. To go live: set config dry_run:false (and mock_apis:false once fal is funded), push.

## Guardrails
- Never commit .env or *.pem (see .gitignore).
- The FB token used in the PoC was a short-lived dev token; generate a long-lived Page token
  for production.

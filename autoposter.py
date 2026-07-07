#!/usr/bin/env python3
"""FB Autoposter — end-to-end pipeline PoC."""

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

BASE_DIR = Path(__file__).parent
HISTORY_FILE = BASE_DIR / "history.json"
OUT_DIR = BASE_DIR / "out"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(BASE_DIR / "autoposter.log")],
)
log = logging.getLogger("autoposter")


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> list:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(history: list) -> None:
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


def retry(cfg: dict):
    max_attempts = cfg["retries"]["max_attempts"]
    backoff = cfg["retries"]["backoff_seconds"]

    def decorator(fn):
        def wrapper(*args, **kwargs):
            delay = backoff
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts:
                        log.error("%s failed after %d attempts: %s",
                                  fn.__name__, max_attempts, exc)
                        raise
                    log.warning("%s attempt %d/%d failed (%s) - retry in %ds",
                                fn.__name__, attempt, max_attempts, exc, delay)
                    time.sleep(delay)
                    delay *= 2
        return wrapper
    return decorator


def topic_fingerprint(topic: str) -> str:
    normalised = " ".join(sorted(topic.lower().split()))
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def is_duplicate(topic: str, history: list, lookback_days: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    fp = topic_fingerprint(topic)
    recent = [h for h in history
              if datetime.fromisoformat(h["posted_at"]) > cutoff]
    if any(h["fingerprint"] == fp for h in recent):
        return True
    topic_words = set(topic.lower().split())
    for h in recent:
        past_words = set(h["topic"].lower().split())
        union = topic_words | past_words
        if union and len(topic_words & past_words) / len(union) > 0.7:
            return True
    return False


def generate_post_content(cfg: dict, history: list) -> dict:
    if cfg.get("manual_content"):
        mc = cfg["manual_content"]
        return {"topic": mc["topic"].strip(),
                "caption": " ".join(mc["caption"].split()),
                "image_prompt": " ".join(mc["image_prompt"].split())}
    if cfg.get("mock_apis"):
        return _mock_post_content(history)

    recent_topics = [h["topic"] for h in history[-20:]]
    prompt = (
        "You create Facebook Page posts.\n\nTopic criteria:\n"
        + cfg["topic_criteria"] + "\n\nCaption style:\n" + cfg["caption_style"]
        + "\n\nRecently posted topics (do NOT repeat):\n"
        + json.dumps(recent_topics, indent=2)
        + '\n\nReturn ONLY valid JSON with keys "topic", "caption", "image_prompt".'
    )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": "claude-haiku-4-5", "max_tokens": 600,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json()["content"][0]["text"].strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
    return json.loads(text)


def _mock_post_content(history: list) -> dict:
    samples = [{"topic": "Regrow green onions from kitchen scraps",
                "caption": "Stop buying green onions! Regrow the root ends.",
                "image_prompt": "Green onion roots regrowing in a glass of water"}]
    used = {h["fingerprint"] for h in history}
    for s in samples:
        if topic_fingerprint(s["topic"]) not in used:
            return s
    raise RuntimeError("Mock generator exhausted.")


def generate_image(cfg: dict, image_prompt: str) -> str:
    if cfg.get("mock_apis"):
        return _mock_image(image_prompt)
    full_prompt = f"{image_prompt}. {cfg['image_style']}"
    resp = requests.post(
        f"https://fal.run/{cfg['image_model']}",
        headers={"Authorization": f"Key {os.environ['FAL_KEY']}",
                 "Content-Type": "application/json"},
        json={"prompt": full_prompt, "image_size": cfg["image_size"],
              "num_images": 1},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["images"][0]["url"]


def _mock_image(image_prompt: str) -> str:
    from PIL import Image, ImageDraw
    OUT_DIR.mkdir(exist_ok=True)
    img = Image.new("RGB", (1024, 1024), (46, 125, 50))
    draw = ImageDraw.Draw(img)
    words, lines, line = image_prompt.split(), [], ""
    for w in words:
        if len(line) + len(w) > 38:
            lines.append(line); line = w
        else:
            line = f"{line} {w}".strip()
    lines.append(line)
    draw.text((60, 60), "[DEMO IMAGE - fal.ai swaps in here]", fill="white")
    for i, l in enumerate(lines):
        draw.text((60, 160 + i * 40), l, fill="white")
    path = OUT_DIR / f"mock_{int(time.time())}.png"
    img.save(path)
    return str(path)


def publish_to_facebook(cfg: dict, image_url: str, caption: str) -> str:
    page_id = os.environ.get("FB_PAGE_ID") or cfg["facebook"]["page_id"]
    endpoint = f"https://graph.facebook.com/v25.0/{page_id}/photos"
    is_local = not str(image_url).startswith("http")
    if cfg.get("dry_run"):
        how = "multipart upload" if is_local else f"url={image_url}"
        log.info("DRY RUN - would POST %s | caption=%s | image=%s",
                 endpoint, caption, how)
        return "dry-run-no-post-id"
    token = os.environ["FB_PAGE_ACCESS_TOKEN"]
    if is_local:
        with open(image_url, "rb") as fh:
            resp = requests.post(endpoint,
                                 data={"caption": caption, "access_token": token},
                                 files={"source": fh}, timeout=120)
    else:
        resp = requests.post(endpoint,
                             data={"url": image_url, "caption": caption,
                                   "access_token": token}, timeout=60)
    if resp.status_code >= 400:
        log.error("FB API error %s: %s", resp.status_code, resp.text)
    resp.raise_for_status()
    post_id = resp.json().get("post_id") or resp.json().get("id")
    log.info("Published: post_id=%s", post_id)
    return post_id


def main() -> int:
    cfg = load_config()
    history = load_history()
    log.info("Run start | dry_run=%s mock_apis=%s | %d in history",
             cfg.get("dry_run"), cfg.get("mock_apis"), len(history))
    _generate = retry(cfg)(generate_post_content)
    _image = retry(cfg)(generate_image)
    _publish = retry(cfg)(publish_to_facebook)
    try:
        content = _generate(cfg, history)
    except Exception:
        log.error("Content generation failed - skipping.")
        return 1
    if is_duplicate(content["topic"], history, cfg["dedupe"]["lookback_days"]):
        log.warning("Duplicate topic '%s' - skipping.", content["topic"])
        return 0
    log.info("Topic:   %s", content["topic"])
    log.info("Caption: %s", content["caption"])
    try:
        image_url = _image(cfg, content["image_prompt"])
        log.info("Image:   %s", image_url)
    except Exception:
        log.error("Image generation failed - skipping (no orphan post).")
        return 1
    try:
        post_id = _publish(cfg, image_url, content["caption"])
    except Exception:
        log.error("Publish failed - topic NOT recorded, retried next run.")
        return 1
    history.append({"topic": content["topic"],
                    "fingerprint": topic_fingerprint(content["topic"]),
                    "post_id": post_id,
                    "posted_at": datetime.now(timezone.utc).isoformat()})
    save_history(history)
    log.info("Run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

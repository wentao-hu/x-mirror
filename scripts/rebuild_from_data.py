#!/usr/bin/env python3
"""Rebuild index.html and post pages from data/*.json (assets must already exist)."""
from __future__ import annotations
import json
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build", ROOT / "scripts" / "extract_and_build.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# keep the shared stylesheet in sync with the template CSS
(ROOT / "assets").mkdir(exist_ok=True)
(ROOT / "assets" / "site.css").write_text(mod.CSS, encoding="utf-8")

# link_only 条目（web.cafe 等）不在 data/*.json 里，重建时必须从旧 posts.json 原样保留
link_only = []
posts_path = ROOT / "posts.json"
if posts_path.exists():
    try:
        old = json.loads(posts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        old = {}
    link_only = [p for p in old.get("posts", []) if p.get("entry_type") == "link_only"]

posts_meta = []
for f in sorted((ROOT / "data").glob("*.json")):
    raw = json.loads(f.read_text(encoding="utf-8"))
    meta = raw["meta"]
    blocks = raw["blocks"]
    body_blocks = [b for b in blocks if not (b["type"] == "heading" and b.get("level") == 1)]
    body_html = mod.render_blocks_html(body_blocks, "assets")
    out = ROOT / "posts" / meta["slug"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(mod.post_page(meta, body_html), encoding="utf-8")
    posts_meta.append(meta)
    print("rebuilt", meta["slug"])

# 按 slug 合并回 link_only，不重复、不覆盖镜像条目
seen = {p["slug"] for p in posts_meta}
for item in link_only:
    if item.get("slug") and item["slug"] not in seen:
        posts_meta.append(item)
        seen.add(item["slug"])

# keep category order stable
order = mod.CATEGORY_ORDER
posts_meta.sort(key=lambda p: (order.index(p["category"]) if p["category"] in order else 99, p["published_utc"]), reverse=False)
(ROOT / "posts.json").write_text(json.dumps({"posts": posts_meta}, ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / "index.html").write_text(mod.index_page(posts_meta), encoding="utf-8")
print("index ok", len(posts_meta))

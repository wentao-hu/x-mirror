#!/usr/bin/env python3
"""抓取 GitHub 公开仓库清单，写入根目录 github-repos.json。

优先使用环境变量 GITHUB_TOKEN / GH_TOKEN，其次尝试 `gh auth token`，
都没有时匿名调用（每小时 60 次，本仓库规模足够）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "github-repos.json"
USER = "wentao-hu"
API = "https://api.github.com"


def token() -> str:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def api_get(url: str, token_value: str) -> list[dict]:
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "x-mirror-repos-fetch")
    if token_value:
        req.add_header("Authorization", f"Bearer {token_value}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_repos(token_value: str) -> list[dict]:
    repos: list[dict] = []
    page = 1
    while True:
        batch = api_get(
            f"{API}/users/{USER}/repos?per_page=100&sort=pushed&direction=desc&type=owner&page={page}",
            token_value,
        )
        repos.extend(batch)
        if len(batch) < 100:
            return repos
        page += 1


def main() -> None:
    raw = fetch_repos(token())
    repos = [
        {
            "name": repo["name"],
            "url": repo["html_url"],
            "description": repo.get("description") or "",
            "language": repo.get("language") or "",
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "fork": bool(repo.get("fork")),
            "archived": bool(repo.get("archived")),
            "pushed_at": repo.get("pushed_at") or "",
            "created_at": repo.get("created_at") or "",
        }
        for repo in raw
    ]
    repos.sort(key=lambda item: item["pushed_at"], reverse=True)
    payload = {
        "user": USER,
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repos": repos,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"github repos ok: {len(repos)} -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        print(f"github api error: HTTP {exc.code} {detail}", file=sys.stderr)
        raise SystemExit(1)

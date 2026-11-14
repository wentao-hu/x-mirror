#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# 只发布包含最新远端的主分支；不自动合并或推送其他会话的改动。
git fetch --all --prune
if [[ "$(git branch --show-current)" != "main" ]]; then
  printf '请先将本次改动合回 main，再发布 Cloudflare。\n' >&2
  exit 1
fi
if ! git merge-base --is-ancestor origin/main HEAD; then
  printf '本地主分支尚未包含 origin/main；请先合并并重建，避免覆盖线上文章。\n' >&2
  exit 1
fi

# 删文须点名确认：ALLOW_REMOVE=slug1,slug2 显式放行本次下架的线上文章。
ALLOW_ARGS=()
if [[ -n "${ALLOW_REMOVE:-}" ]]; then
  IFS=',' read -ra REMOVE_SLUGS <<< "$ALLOW_REMOVE"
  for slug in "${REMOVE_SLUGS[@]}"; do
    ALLOW_ARGS+=(--allow-remove "$slug")
  done
fi

# 刷新 GitHub 仓库清单；失败时沿用已提交的数据，不阻塞文章发布。
python3 scripts/fetch_github_repos.py || printf '警告：GitHub 仓库数据刷新失败，沿用 github-repos.json 旧数据。\n' >&2

# 任何 Agent 都经同一条构建与验收路径，漏卡片/漏正文索引直接阻止上传。
python3 scripts/rebuild_from_data.py
python3 scripts/validate_site.py --online https://x-mirror-af7.pages.dev/ ${ALLOW_ARGS[@]+"${ALLOW_ARGS[@]}"}

# 静态资源与 Pages Functions 一起上传，KV 绑定沿用 wrangler.toml。
npx --yes wrangler pages deploy . \
  --project-name x-mirror \
  --branch main \
  --commit-dirty=true
python3 scripts/validate_site.py --verify-online https://x-mirror-af7.pages.dev/ ${ALLOW_ARGS[@]+"${ALLOW_ARGS[@]}"}
printf '主站: https://x-mirror-af7.pages.dev/\n'

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Deploy static assets + Pages Functions; KV binding comes from wrangler.toml
npx --yes wrangler pages deploy . \
  --project-name x-mirror \
  --branch main \
  --commit-dirty=true
echo "Primary: https://x-mirror-af7.pages.dev/"
echo "API:     https://x-mirror-af7.pages.dev/api/meta"

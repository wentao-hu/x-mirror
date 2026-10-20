#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes wrangler pages deploy . \
  --project-name x-mirror \
  --branch main \
  --commit-dirty=true
echo "Primary: https://x-mirror-af7.pages.dev/"

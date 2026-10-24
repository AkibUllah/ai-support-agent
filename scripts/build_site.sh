#!/usr/bin/env bash
# Build the GitHub Pages site:
#   /               chat UI in replay mode, showing transcripts of the offline eval run
#   /api-docs/      Swagger UI over the exported OpenAPI document
# Usage: scripts/build_site.sh [output dir]   (needs agent-eval/support-agent on PATH and npm)
set -euo pipefail
cd "$(dirname "$0")/.."
out="$(realpath -m "${1:-_site}")"
base="${BASE_PATH:-/ai-support-agent/}"

rm -rf "$out"
mkdir -p "$out/api-docs"
(cd ui && BASE_PATH="$base" VITE_DEMO_MODE=replay npm run build -- --outDir "$out" --emptyOutDir)
agent-eval run --transcripts "$out/transcripts.json" > /dev/null
support-agent openapi "$out/api-docs/openapi.json" > /dev/null
cp site/api-docs.html "$out/api-docs/index.html"
cp "$out/index.html" "$out/404.html"
echo "built $out (base $base)"

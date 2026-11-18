#!/usr/bin/env bash
# Syntax-check every runtime module (ES modules) with node; checks that index.js exports resolve to files that exist.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v node >/dev/null || { echo "node not found: skipped"; exit 0; }
rc=0
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
for f in "$ROOT"/runtime/*.js; do
  cp "$f" "$tmp/check.mjs"                                  # .mjs makes node parse it as an ES module
  if node --check "$tmp/check.mjs" 2>/tmp/jscheck.err; then echo "ok   syntax $(basename "$f")"; else echo "FAIL syntax $(basename "$f")"; cat /tmp/jscheck.err; rc=1; fi
done
for m in $(grep -o "from '\./[a-z_]*\.js'" "$ROOT/runtime/index.js" | sed "s/from '\.\///;s/'//"); do
  [[ -f "$ROOT/runtime/$m" ]] && echo "ok   index exports $m" || { echo "FAIL index exports missing file $m"; rc=1; }
done
[[ $rc == 0 ]] && echo "ALL PASSED" || echo "FAILED"
exit $rc

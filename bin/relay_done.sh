#!/bin/sh
# 총괄이 outbox 항목을 전한 뒤 outbox/sent/로 옮겨요.
# 사용: relay_done.sh <outbox 파일> <결과>
#   결과가 delivered(전달됨)가 아니면(실패·보류·대기열 등) 그 대화 파일에 시스템 줄을 남겨 대표가 사이트에서 알 수 있게 해요.
set -eu
command -v jq >/dev/null 2>&1 || { echo "jq가 필요해요. 맥: brew install jq, 리눅스: sudo apt install jq" >&2; exit 1; }
f=$1; r=${2:-delivered}
d=$(dirname "$f")/sent
mkdir -p "$d"
case "$r" in
  *delivered*|전달됨) ;;
  *)
    th=$(jq -r '.thread // empty' "$f")
    lb=$(jq -r '.label // ""' "$f")
    if [ -n "$th" ] && [ -f "$th" ]; then
      jq -nc --arg t "$(date -Iseconds)" --arg text "$lb · 전달 상태: $r" '{t:$t,from:"총괄",kind:"전달",text:$text}' >> "$th"
    fi
    ;;
esac
tmp="$d/$(basename "$f").tmp"
jq --arg r "$r" --arg t "$(date -Iseconds)" '. + {result:$r, done:$t}' "$f" > "$tmp" || { rm -f "$tmp"; echo "정리하지 못했어요: $f" >&2; exit 1; }
mv "$tmp" "$d/$(basename "$f")"
rm -f "$f"
echo "정리: $(basename "$f") → sent ($r)"

#!/bin/sh
# 총괄이 outbox 항목을 전한 뒤 outbox/sent/로 옮겨요.
# 사용: relay_done.sh <outbox 파일> <결과>
#   결과가 delivered(전달됨)가 아니면(실패·보류·대기열 등) 그 대화 파일에 시스템 줄을 남겨 대표가 사이트에서 알 수 있게 해요.
#   그사이 서버가 다시 켜지며 outbox/rejected/로 옮긴 항목(그 대화엔 '못 전했을 수 있어요' 줄이 있어요)이면 거기서 옮기고,
#   전했으면 그 대화에 '총괄이 전했어요' 줄을 이어서 남겨요(대표가 다시 보내지 않게).
set -eu
command -v jq >/dev/null 2>&1 || { echo "jq가 필요해요. 맥: brew install jq, 리눅스: sudo apt install jq" >&2; exit 1; }
f=$1; r=${2:-delivered}
d=$(dirname "$f")/sent
n=$(basename "$f")
late=
if [ ! -f "$f" ]; then
  if [ -f "$d/$n" ]; then echo "이미 정리했어요: $n"; exit 0; fi
  if [ -f "$(dirname "$f")/rejected/$n" ]; then
    f=$(dirname "$f")/rejected/$n; late=1
  else
    echo "outbox에 없는 항목이에요(이미 정리했거나, 총괄이 바뀌어 새 이름으로 넘어갔어요): $n"; exit 0
  fi
fi
mkdir -p "$d"
case "$r" in
  *undelivered*|*"not delivered"*) ok= ;;
  *delivered*|전달됨) ok=1 ;;
  *) ok= ;;
esac
th=$(jq -r '.thread // empty' "$f" 2>/dev/null || true)
if [ -z "$ok" ]; then
  lb=$(jq -r '.label // ""' "$f")
  if [ -n "$th" ] && [ -f "$th" ]; then
    jq -nc --arg t "$(date -Iseconds)" --arg text "$lb · 전달 상태: $r" '{t:$t,from:"총괄",kind:"전달",text:$text}' >> "$th"
  fi
elif [ -n "$late" ] && [ -n "$th" ] && [ -f "$th" ]; then
  hm=$(jq -r '(.t // "") | if test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}") then .[11:16] + "에 " else "" end' "$f" 2>/dev/null || true)
  jq -nc --arg t "$(date -Iseconds)" --arg text "${hm}보낸 말은 총괄이 전했어요. 다시 보내지 않아도 돼요." '{t:$t,from:"총괄",kind:"전달",text:$text}' >> "$th"
fi
tmp="$d/$n.tmp"
jq --arg r "$r" --arg t "$(date -Iseconds)" '. + {result:$r, done:$t}' "$f" > "$tmp" || { rm -f "$tmp"; echo "정리하지 못했어요: $f" >&2; exit 1; }
mv "$tmp" "$d/$n"
rm -f "$f"
echo "정리: $n → sent ($r)"

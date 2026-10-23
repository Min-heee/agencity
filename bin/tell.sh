#!/bin/sh
# 다른 층 팀장에게 보내는 팀 간 대화를 남기고, 보낼 곳을 알려 줘요(팀장만 써요).
# 사용: tell.sh <상대 층 id> --from <내 층 id> --role <내 역할> --file <보낼 글을 쓴 파일> [--topic <짧은 주제> | --re <T-…>]
#       tell.sh --list        층 id와 층 이름 목록(예시 팀은 빼요)
#   --topic: 새 주제로 대화를 시작해요(대화 번호 T-…가 생겨요). --re: 받은 머리말의 대화 번호에 답해요.
#   둘 다 없으면 24시간 안에 같은 두 층이 나눈 마지막 대화를 이어요(없으면 새 대화).
#   한 대화는 왕복 3번(말 6개, 양쪽 다 세요)까지예요. 넘으면 보내지 않고(끝 코드 1) 총괄에게 [보고]하라고 알려요.
#   세기·덧붙이기는 bin/talk_thread.py가 잠금(hq/.teams.lock)을 잡고 해요. 대표가 화면에서 허락하면 3번 더 돼요.
#   보낼 글은 Write 도구로 <에이전시티>/hq/.out/tell-<내 층 id>.txt에 먼저 써요. 본문을 명령 줄에 넣지 않아야
#   팀 안전장치(훅)가 본문 낱말에 걸리지 않아요. 그 파일은 읽은 뒤 지워요.
#   대화는 <에이전시티>/hq/teams.jsonl에 한 줄로 남겨요(사이트의 '팀 간 대화'가 이 파일을 보여 줘요).
#   잘 되면 딱 두 줄을 찍어요:
#     SEND_TO=<상대 층 팀장 세션 id>
#     HEADER=[협업·<내 층 이름>→<상대 층 이름> #<대화 번호> <몇 번째>/<한도>]
#   대화의 마지막 말(n = 한도)이면 표준 오류에 알림 한 줄을 더 찍어요.
#   그다음 내가 SendMessage(to = SEND_TO)로 HEADER 줄과 보낼 글을 보내요. 이 스크립트는 메시지를 보내지 않아요.
#   지금은 팀장만 보낼 수 있어요(대표가 나중에 '누구나'를 켤 수 있게 남겨 둔 자리예요).
set -eu
command -v jq >/dev/null 2>&1 || { echo "jq가 필요해요. 맥: brew install jq, 리눅스: sudo apt install jq" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3가 필요해요(에이전시티 서버와 같은 파이썬)" >&2; exit 1; }
OFFICE=$(cd "$(dirname "$0")/.." && pwd -P)
ORG="$OFFICE/org.json"
MAX=4000
die() { echo "$*" >&2; exit 1; }
usage() { echo "사용: tell.sh <상대 층 id> --from <내 층 id> --role <내 역할> --file <보낼 글 파일> [--topic <주제> | --re <T-…>]   (층 목록: tell.sh --list)" >&2; exit 2; }
[ -f "$ORG" ] || die "org.json이 없어요: $ORG"
# 화면에 보일 이름: 줄바꿈·제어 문자는 빼요(HEADER가 꼭 한 줄이게)
CLEAN='gsub("[\u0000-\u001f\u007f  ‪-‮⁦-⁩]"; "")'

if [ "${1:-}" = "--list" ]; then
  jq -r '.teams[]? | select(type == "object" and (.office | type) == "string" and .office != "" and (.office | startswith("examples/") | not))
         | "\(.id)\t\((.name // .id) | tostring | '"$CLEAN"')"' "$ORG"
  exit 0
fi

[ $# -ge 1 ] || usage
to=$1; shift
from=""; role=""; src=""; how=auto; arg=""
while [ $# -gt 0 ]; do
  [ $# -ge 2 ] || usage
  case "$1" in
    --from) from=$2 ;;
    --role) role=$2 ;;
    --file) src=$2 ;;
    --topic|--re)
      [ "$how" = auto ] || die "--topic과 --re는 하나만 써요(새 주제는 --topic, 받은 말에 답할 때는 --re)"
      how=${1#--}; arg=$2 ;;
    *) usage ;;
  esac
  shift 2
done
[ -n "$from" ] && [ -n "$role" ] && [ -n "$src" ] || usage
# 대화 번호: 받은 머리말의 #T-xxxxxx(# 없이도 돼요). 주제는 talk_thread.py가 한 줄 40자로 다듬어요
if [ "$how" = re ]; then
  arg=${arg#\#}
  jq -en --arg v "$arg" '$v | test("\\AT-[0-9a-f]{6}\\z")' >/dev/null 2>&1 || die "대화 번호가 이상해요: 받은 머리말의 #T-… 번호를 써요"
fi

# 층 id 모양(office_server.py의 SAFE_ID와 같아요, ..는 안 돼요)
for id in "$to" "$from"; do
  case "$id" in *..*) die "층 id가 이상해요: $id" ;; esac
  jq -en --arg v "$id" '$v | test("\\A[0-9A-Za-z가-힣._-]{1,80}\\z")' >/dev/null 2>&1 || die "층 id가 이상해요: $id"
done
[ "$to" != "$from" ] || die "내 층에는 tell.sh로 보내지 않아요. 같은 층 팀원과는 바로 [협업]으로 주고받아요"

# 보내는 사람: 역할 이름 모양(say.sh와 같아요), 대표·총괄은 안 되고, 지금은 팀장만
case "$role" in 대표|총괄|"") die "보내는 사람이 이상해요: $role (대표·총괄은 tell.sh를 쓰지 않아요)" ;; esac
jq -en --arg w "$role" '$w | test("\\A[0-9A-Za-z가-힣][0-9A-Za-z가-힣_·-]{0,11}\\z")' >/dev/null 2>&1 ||
  die "보내는 사람이 이상해요(역할 이름이어야 해요): $role"
[ "$role" = "팀장" ] || die "팀 간 대화는 팀장만 보내요(지금은 ‘${role}’). 다른 층에 할 말이 있으면 내 층 팀장에게 [협업]으로 부탁해요"

# 층 찾기: org.json에서 사무실이 있는 층, 예시 팀은 빼요
floor_of() {
  jq -c --arg id "$1" '[.teams[]? | select(type == "object" and .id == $id and (.office | type) == "string" and .office != "")][0] // empty' "$ORG"
}
office_dir() {   # 층 줄(JSON) → 팀 사무실 실제 경로. 설치 폴더를 품는 곳(링크로 잘못 이어진 사무실)은 안 돼요
  o=$(printf '%s' "$1" | jq -r '.office')
  case "$o" in *..*) return 1 ;; examples/*) return 1 ;; /*) p=$o ;; *) p=$OFFICE/$o ;; esac
  r=$(cd "$p" 2>/dev/null && pwd -P) || return 1
  case "$OFFICE/" in "$r/"*) return 1 ;; esac
  [ -f "$r/team.json" ] || return 1
  printf '%s' "$r"
}
fj=$(floor_of "$from"); [ -n "$fj" ] || die "내 층을 org.json에서 찾지 못했어요: $from (층 목록: tell.sh --list)"
tj=$(floor_of "$to"); [ -n "$tj" ] || die "상대 층을 org.json에서 찾지 못했어요: $to (층 목록: tell.sh --list)"
case "$(printf '%s' "$fj" | jq -r '.office')" in examples/*) die "예시 팀은 팀 간 대화를 하지 않아요" ;; esac
case "$(printf '%s' "$tj" | jq -r '.office')" in examples/*) die "예시 팀에는 보낼 수 없어요" ;; esac
froot=$(office_dir "$fj") || die "내 층의 팀 사무실(team.json)을 읽지 못했어요: $from"
troot=$(office_dir "$tj") || die "상대 층의 팀 사무실(team.json)을 읽지 못했어요: $to"
fname=$(printf '%s' "$fj" | jq -r '(.name // .id) | tostring | '"$CLEAN")
tname=$(printf '%s' "$tj" | jq -r '(.name // .id) | tostring | '"$CLEAN")

SID='test("\\Alocal_[0-9a-f-]{8,64}\\z") and (startswith("local_00000000") | not)'
mine=$(jq -c --arg r "$role" '[.members[]? | select(type == "object" and .role == $r)][0] // empty' "$froot/team.json") ||
  die "내 층의 team.json을 읽지 못했어요"
[ -n "$mine" ] || die "내 층에 ‘${role}’ 자리가 없어요"
printf '%s' "$mine" | jq -e '(.sessionId // "") | '"$SID" >/dev/null 2>&1 || die "내 층 ‘${role}’ 자리에 세션이 앉아 있지 않아요"
msid=$(printf '%s' "$mine" | jq -r '.sessionId')
sname=$(printf '%s' "$mine" | jq -r --arg d "$fname $role" '(if (.name | type) == "string" and .name != "" then .name else $d end) | '"$CLEAN"' | .[0:40]')
tsid=$(jq -r '[.members[]? | select(type == "object" and .role == "팀장")][0].sessionId // ""' "$troot/team.json") ||
  die "상대 층의 team.json을 읽지 못했어요"
jq -en --arg v "$tsid" '$v | '"$SID" >/dev/null 2>&1 || die "‘${tname}’ 층에는 팀장이 없어요. 보내지 말고 총괄에게 [보고]로 올려요"
[ "$tsid" != "$msid" ] || die "상대 층 팀장이 나와 같은 세션이에요. team.json을 확인해 주세요"

# 보낼 글 파일: hq/.out/ 안의 보통 파일만(say.sh처럼 대화 파일 옆 .out/)
case "$src" in *..*) die "보낼 글 파일 경로에 ..를 쓸 수 없어요" ;; esac
outd=$(cd "$OFFICE/hq/.out" 2>/dev/null && pwd -P) || die "보낼 글 파일은 Write 도구로 $OFFICE/hq/.out/ 폴더에 먼저 써요"
sdir=$(cd "$(dirname "$src")" 2>/dev/null && pwd -P) || die "보낼 글 파일이 없어요: $src"
[ "$sdir" = "$outd" ] || die "보낼 글 파일은 $OFFICE/hq/.out/ 폴더에 둬요"
[ -f "$src" ] && [ ! -L "$src" ] || die "보낼 글 파일이 없어요: $src"
text=$(cat "$src")
[ -n "$text" ] || die "보낼 글이 비었어요"
jq -en --arg t "$text" --argjson n "$MAX" '$t | length <= $n' >/dev/null 2>&1 || die "보낼 글이 너무 길어요(${MAX}자까지). 줄여서 다시 써 주세요"

mkdir -p "$OFFICE/hq"
# 이을 대화를 정하고 세고 덧붙이기는 talk_thread.py가 잠금 안에서 한 번에 해요(시각 t·thread·topic·n·cap을 더해요).
# 한도를 넘으면 그 대화에 멈춤 줄을 남기고 끝 코드 1로 막아요(보낼 글 파일은 그대로 둬요)
got=$(jq -nc --arg ff "$from" --arg fr "$role" --arg nm "$sname" --arg fn "$fname" \
  --arg tf "$to" --arg tn "$tname" --arg text "$text" \
  '{from: {floor: $ff, role: $fr, name: $nm, floorName: $fn}, to: {floor: $tf, role: "팀장", floorName: $tn}, text: $text}' |
  python3 -I "$OFFICE/bin/talk_thread.py" send "$OFFICE/hq" "$how" "$arg") || exit 1
set -- $got
[ $# -eq 3 ] || die "팀 간 대화 기록 결과가 이상해요: $got"
th=$1; n=$2; cap=$3
case "$n$cap" in *[!0-9]*) die "팀 간 대화 기록 결과가 이상해요: $got" ;; esac
rm -f "$src"
printf 'SEND_TO=%s\nHEADER=[협업·%s→%s #%s %s/%s]\n' "$tsid" "$fname" "$tname" "$th" "$n" "$cap"
[ "$n" -lt "$cap" ] || echo "이 대화의 마지막 말이에요. 이걸로 끝나지 않으면 총괄에게 [보고]로 올려요" >&2

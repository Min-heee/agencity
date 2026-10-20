# 클로드 오피스 (Claude Office)

Claude Code 세션 여러 개를 **팀(팀장·개발자·디자이너·기획)** 으로 묶어 사무실처럼 보여 주고,
웹 페이지 하나에서 **누구에게나 말 걸기 · 회의 열기 · 결재**를 하는 로컬 대시보드예요.

> English: A local web dashboard that organizes several Claude Code desktop sessions into teams
> (lead, developer, designer, planner) shown as office floors. From one page you can message any
> session, start meetings (attend or delegate), and approve decisions the team leads file. Messages
> are relayed by a coordinator session with Claude Code's own `SendMessage` tool — the page never
> injects input into sessions. UI text is Korean.

![예시 팀 화면](docs/screenshot.jpg)

- 층(팀)마다 책상(세션 상태·하는 일), 회의실, 업무판, 활동 기록, 보고서가 보여요.
- 책상을 누르면 그 세션과 바로 대화해요. 답은 같은 화면에 올라와요.
- 회의는 사람(대표)만 열어요. **참석**(같이 대화)과 **위임**(팀끼리 하고 회의록·결재로 보고)이 있고, 중간에 빠지면 남은 안건은 팀이 이어서 해요.
- 팀장이 올린 **결재**를 결재함에서 고르면 그 팀장에게 바로 전해져요.
- 파일만 읽고 쓰는 단순한 구조예요(Python 표준 라이브러리 + 정적 HTML).

## 앞으로의 계획: 클로드 시티

사람마다 자기 클로드 오피스를 등록하면, **토큰 사용량만큼 높은 빌딩**이 하나씩 서는 도시를 만들려고 해요
([Git City](https://github.com/srizzon/git-city)에서 영감). 건물의 층은 그 사람의 팀이에요.
건물을 누르면 그 사람이 **공개해 둔 층만** 읽기 전용으로 들여다보고 둘러볼 수 있어요.
기본은 비공개이고, 대화·결재·보고서 원문은 공개하지 않아요. 토큰 숫자는
[token-meter](https://github.com/Min-heee/token-meter)가 내 컴퓨터에서 세서 본인이 원할 때만 올려요.
자세한 내용: [docs/VISION.md](docs/VISION.md)

## 어떻게 동작하나요

```
브라우저(127.0.0.1:8765)
   │  POST /api/say · /api/meeting/* · /api/decide   (Host·Origin·열쇠 확인)
   ▼
office_server.py ──► 팀 사무실 파일에 기록 (chat/*.jsonl, meetings/*, approvals/*, log.jsonl)
   │
   └─► outbox/<id>.json  (전달할 메시지, 서버가 만든 것만 등록)
            │
            ▼
총괄(코디네이터) Claude Code 세션 ── Monitor로 bin/relay_watch.py 실행
            │   RELAY <파일> 알림을 받으면
            ▼
      SendMessage(to=세션 id, 내용 그대로)  ──►  팀 세션
                                                   │ 답은 Write로 .out/<역할>.txt에 쓰고
                                                   ▼
                                         bin/say.sh <대화 파일> <역할> --file …
                                                   │
                                                   ▼
                                    대화 파일 → 브라우저가 몇 초마다 다시 읽어 보여 줌
```

왜 세션에 직접 넣지 않나요? 세션의 메시지 소켓에 외부 프로그램이 사용자 입력처럼 글을 넣는 방식은
Claude Code의 자동 모드 안전장치가 막아요. 그래서 공식 도구인 `SendMessage`로만 전해요.
사이트에서 온 말은 다른 세션을 거친 메시지라 **승인(커밋·배포·결제 등)으로 쓰이지 않아요.**
위험한 일은 결재로 "하기로 정함"까지만 하고, 실제 실행은 그 세션 창에서 사람이 마지막으로 확인해요.

## 필요한 것

- macOS 또는 Linux, Python 3.9 이상, `jq`
- Claude Code 데스크톱 앱(세션 간 메시지 `SendMessage`, `Monitor` 도구가 되는 버전)

## 빠르게 써 보기 (예시 팀)

```bash
git clone https://github.com/Min-heee/claude-office.git && cd claude-office
cp examples/org.example.json org.json
python3 build.py              # office.src.html → index.html
python3 office_server.py      # http://127.0.0.1:8765
```

8765 포트가 이미 쓰이면 `OFFICE_PORT=8766 python3 office_server.py`로 켜고 `http://127.0.0.1:8766/#demo`를 열어요(코디네이터의 `relay_watch.py`도 같은 `OFFICE_PORT`로 켜요).

브라우저에서 `http://127.0.0.1:8765/#demo`를 열면 예시 팀 1층이 보여요.
예시 팀의 세션 id는 가짜라서 말을 보내면 `outbox/`에 쌓이기만 해요(코디네이터가 없으니까요).
써 보면 `examples/teams/demo/`에 기록이 남아요. 처음 상태로 돌리려면 `git checkout examples/ && git clean -fd examples/`.

## 내 팀 꾸리기

1. 프로젝트마다 팀 사무실 폴더(예: `<프로젝트>/.office/`)를 만들고 `examples/teams/demo/` 구조를 따라요:
   `team.json`(역할별 세션 id), `status/<역할>.json`, `board.md`, `log.jsonl`, `reports/`, `meetings/`, `approvals/`, `chat/`.
2. `teams/<id>`를 그 폴더로 연결하고(`mkdir -p teams && ln -s <프로젝트>/.office teams/<id>`), `org.json`의 `teams`에 넣어요(`office: "teams/<id>"`, `floor`).
3. 각 세션이 [docs/TEAM_RULES.md](docs/TEAM_RULES.md)를 읽게 해요(예: 프로젝트의 `CLAUDE.local.md`에서 `@/절대경로/TEAM_RULES.md`로 가져오기). 세션 id는 데스크톱 앱의 세션 id(`local_…`)예요.
4. 총괄(코디네이터)로 쓸 세션 하나를 정해 `org.json`의 `boss.sessionId`에 넣고, [docs/COORDINATOR.md](docs/COORDINATOR.md)대로 전달을 켜요.

## 보안 메모

- 서버는 `127.0.0.1`에만 열려요. `Host`·`Origin`·페이지 열쇠(서버를 켤 때마다 새로 만듦)·JSON만 받는 요청만 처리해요.
- 다른 사이트가 이 페이지를 틀(iframe)에 넣지 못하게 `X-Frame-Options: DENY`, `frame-ancestors 'none'`을 보내요.
- 보여 주는 파일은 `index.html`, `org.json`, `hq/`, 등록된 팀 사무실 폴더 안으로 제한해요.
- 전달 항목은 서버가 만든 것만 코디네이터가 보내요(`/api/outbox/check`로 내용 해시 확인). 1분 30개, 대기 40개로 양을 제한해요.
- `bin/say.sh`는 정해진 대화 파일에만, `대표` 이름이 아닌 것만 쓸 수 있어요.
- 남는 위험: 같은 맥의 다른 프로그램(에이전트 포함)은 페이지를 받아 열쇠를 읽을 수 있어요. 그래서 사이트 메시지를 승인으로 쓰지 않는 규칙이 중요해요.
- `python3 build.py --snapshot`은 팀 상태를 페이지 안에 담아 공유용 `artifact.html`을 만들어요. **팀 데이터가 그대로 들어가니** 공개하기 전에 꼭 확인하세요.

## 한계

- 코디네이터 세션이 켜져 있어야 전달돼요(끊기면 화면 위에 "총괄 연결 끊김").
- Claude Code는 한 세션이 사람 입력 없이 다른 세션에 메시지를 많이 보내면 잠깐 막아요. 팀장이 그 한도에 걸리면 그 팀장 창에 사람이 한 번 입력해야 풀려요. 사이트로는 풀 수 없어요.
- 화면 글은 한국어예요.

## 라이선스

[MIT](LICENSE)

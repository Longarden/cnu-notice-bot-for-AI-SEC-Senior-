# CNU 공지 · 공모전 · 인턴십 · 채용 알리미

충남대학교 공지 9개 게시판에 더해 AI/IT 공모전, 인턴십, 신입 채용공고까지 모아서
텔레그램 채널로 보내준다.

GitHub Actions의 무료 cron으로 동작함. -> 따라서 다소 딜레이가 생길 수 있음.

**구독 방법: 아래 채널에 들어오면 끝.**

- 채널: (채널 개설 후 여기에 링크를 적는다)
- 봇: https://t.me/cnu_alarmbot — `/start`를 보내면 채널 링크를 안내해준다

## 수집하는 곳

### 🏫 학교공지 — 등록일 기준 최근 7일

| 게시판 | 출처 |
|--------|------|
| 학사공지 | 컴퓨터인공지능학부 |
| 교내일반소식 | 컴퓨터인공지능학부 |
| 교외활동·인턴·취업 | 컴퓨터인공지능학부 |
| 사업단소식 | 컴퓨터인공지능학부 |
| 국제교류·모집공지 | 국제교류본부 (cnuint) |
| 국제교류·행사공지 | 국제교류본부 (cnuint) |
| 정보보호특성화대학 | 사이버보안연구센터 (csrc) |
| 교육정보(본부) | 본부 포털 (plus) |
| 비교과 프로그램 | CNU With U+ (with) |

### 🏆 공모전 / 🧑‍💻 인턴십 / 💼 채용 — 처음 보는 글만

| 소스 | 카테고리 | 수집 방식 |
|------|----------|-----------|
| 위비티 웹/모바일/IT (cidx=20) | 공모전 | HTML |
| 위비티 게임/소프트웨어 (cidx=21) | 공모전 | HTML |
| 위비티 과학/공학 (cidx=22) | 공모전 | HTML |
| DACON AI 경진대회 | 공모전 | `__NUXT__` 페이로드 |
| 링커리어 인턴 | 인턴십 | `__NEXT_DATA__` JSON |
| 점핏 신입 개발자 (career=0) | 채용 | 공개 JSON API |

이 사이트들은 **등록일을 노출하지 않고 마감 D-day만** 준다. 그래서 "최근 7일" 필터를
쓸 수 없고, 대신 `seen.json`에 이미 발송한 글번호를 적어두고 **처음 보는 글만** 보낸다.
소스를 새로 추가한 첫 실행에서는 수십 건이 한꺼번에 쏟아지지 않도록, 현재 목록을
기준선으로 기록만 하고 발송하지 않는다.

한 공모전이 여러 분야에 동시 등록돼 있으면(위비티에서 흔함) 발송 직전에 중복을 제거한다.

수집 대상 사이트는 모두 robots.txt에서 목록 페이지 크롤링을 허용하고 있음을 확인했다.
캠퍼스픽은 목록이 자바스크립트로만 렌더링돼서, 씽굿은 목록 조회가 POST 기반이라 제외했다.

## 동작 방식

두 개의 워크플로우가 서로 다른 주기로 돈다.

| 워크플로우 | 주기 | 하는 일 |
|-----------|------|---------|
| `notify.yml` | 매일 UTC 00:00 (한국 오전 9시) | 전체 수집 + 채널 발송 |
| `greet.yml` | 3시간마다 | `/start` 보낸 사람에게 채널 링크 안내 + 명부 갱신 |

인사 담당을 따로 뗀 이유: 텔레그램은 **미확인 update를 24시간만 보관**한다.
하루 한 번짜리 워크플로우 하나에만 의존하면 그 사이 들어온 사람을 놓칠 수 있다.
반대로 공지 다이제스트를 3시간마다 보내면 같은 공지가 하루 8번 오게 되므로,
자주 도는 쪽은 발송을 하지 않는다.

- 각 게시판/사이트 첫 페이지(최신 13~21건)를 수집
- 학교공지는 등록일이 7일 이내인 것만. 같은 공지가 7일간 반복 노출되므로 하루 놓쳐도 다음날 다시 보임
- 공모전/인턴십/채용은 `seen.json` 기준 처음 보는 글만. 한 번 보낸 건 다시 안 옴
- 비교과 프로그램은 등록일 대신 **접수 시작일** 기준. 상세 페이지가 로그인 필수라 링크는 with.cnu.ac.kr 메인으로 연결됨
- **발송이 전부 실패하면 워크플로우가 빨간 X로 끝난다.** 예전에는 실패해도 초록 체크로 끝나서, 아무한테도 안 갔는데 정상으로 보였다
- 발송에 실패한 회차는 `seen.json`을 갱신하지 않으므로 다음 실행에서 다시 시도한다

## 처음 설정하는 법

### 1단계: 텔레그램 봇 만들기

1. 텔레그램에서 `@BotFather` 검색해서 대화 시작
2. `/newbot` 입력 → 이름 → username (반드시 `bot`으로 끝나야 함) 순서로 입력
3. BotFather가 보내준 토큰 복사 (예: `7123456789:AAFxxx...`)

### 2단계: 채널 만들고 봇을 관리자로 넣기

여러 명에게 보내려면 채널이 가장 단순하다. 구독자 명단을 코드가 관리할 필요가 없고,
새로 들어온 사람은 채널에 쌓인 지난 공지까지 바로 볼 수 있다.

1. 텔레그램 → 연필 아이콘 → **새 채널** → 이름 입력
2. 채널 종류를 **공개 채널**로 두고 링크 주소를 정한다 (예: `cnu_alarm` → `https://t.me/cnu_alarm`)
3. 채널 → 관리 → **관리자** → 관리자 추가 → `@cnu_alarmbot` 검색해서 추가
4. 관리자 권한 중 **메시지 게시**가 켜져 있어야 한다 (이게 꺼져 있으면 발송이 실패한다)

`TELEGRAM_CHAT_ID`에는 `@` 를 붙인 채널명(`@cnu_alarm`)을 넣는다.
콤마로 여러 개를 넣을 수도 있다 — 전환 기간에 `@cnu_alarm,123456789` 처럼
채널과 본인 개인 chat_id에 동시에 보내다가, 안정되면 채널만 남기면 된다.

개인 chat_id를 알아내려면 `@userinfobot`에게 `/start`를 보내면 된다.

### 3단계: GitHub 저장소 만들기와 push

이미 만들어져 있다면 이 단계 건너뛰기.

1. https://github.com/new 에서 repo 생성 (Private 권장, README 체크 해제)
2. PowerShell에서:
   ```powershell
   cd C:\Users\dmsak\cnu-notice-bot
   git init
   git add .
   git commit -m "init: cnu notice bot"
   git branch -M main
   git remote add origin https://github.com/USERNAME/cnu-notice-bot.git
   git push -u origin main
   ```
   (`USERNAME` 자리에 본인 GitHub 사용자명)

push 시 비밀번호 자리에 Personal Access Token 입력 (https://github.com/settings/tokens/new 에서 `repo` 권한으로 발급).

### 4단계: GitHub Secrets / Variables 등록

repo 페이지 → Settings → Secrets and variables → Actions.

**Secrets** 탭 (New repository secret):

| Name | Value |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | 1단계 토큰 |
| `TELEGRAM_CHAT_ID` | 2단계 채널명 (`@cnu_alarm`). 콤마로 여러 개 가능 |

**Variables** 탭 (New repository variable) — 비밀이 아니라 그냥 링크라서 variable로 둔다:

| Name | Value |
|------|-------|
| `TELEGRAM_CHANNEL_LINK` | `https://t.me/cnu_alarm` (봇이 `/start`에 답장할 때 안내할 링크) |

`TELEGRAM_CHANNEL_LINK`를 비워두면 `/start` 안내를 하지 않는다. 공지 발송에는 영향이 없다.

### 5단계: 첫 실행 테스트

repo 페이지 → Actions 탭 → 좌측 `CNU Notice Notifier` 클릭 → 우측 `Run workflow` → `Run workflow` 초록 버튼

1~2분 후 새로고침해서 결과 확인:
- 초록 체크 = 성공. 채널에 메시지가 도착해 있어야 한다
- 빨간 X = 실패. 워크플로우 클릭 → 실패한 단계 펼치면 로그 확인

**첫 실행에서는 공모전/인턴십/채용이 하나도 오지 않는 게 정상이다.** 첫 수집은
기준선을 잡는 용도라 발송하지 않고 `seen.json`에 기록만 한다. 두 번째 실행부터
새로 올라온 것만 온다. 학교공지는 첫 실행부터 정상 발송된다.

이후 매일 한국시간 오전 9시에 자동 실행.

## 구독자 명부 보기 (소유자 전용)

봇에게 `/start`를 보낸 사람은 `subscribers.enc`에 기록된다. 이 저장소는 공개라서
평문으로 두면 구독자의 텔레그램 chat_id가 그대로 노출되므로, **봇 토큰에서 파생한
키로 암호화해서** 커밋한다. 토큰을 가진 사람만 열 수 있다.

```powershell
cd C:\Users\dmsak\cnu-notice-bot
git pull
$env:TELEGRAM_BOT_TOKEN="7123456789:AAFxxx..."
$env:TELEGRAM_CHAT_ID="@cnu_alarm"
py roster.py
```

chat_id, 이름, username, 최초/최근 접속 시각이 표로 나오고, 마지막에 채널 구독자 수가 붙는다.

텔레그램은 **채널 구독자 명단을 봇에게 제공하지 않는다**(설계상 비공개). 그래서
채널은 인원수만 알 수 있고, 개별 명부는 봇에게 `/start`를 보낸 사람에 한해 만들어진다.
채널 구독자 목록 자체는 텔레그램 앱에서 채널 → 관리 → 구독자로 확인하면 된다.

봇 토큰을 재발급하면 기존 명부를 못 읽는다. 그럴 땐 `ROSTER_KEY` 환경변수(또는 Secret)에
**이전 토큰**을 넣으면 계속 읽을 수 있다.

## 로컬에서 테스트

전송 없이 스크래핑 동작만 확인:

```powershell
cd C:\Users\dmsak\cnu-notice-bot
py -m pip install -r requirements.txt
$env:DRY_RUN="1"
py notify.py
```

실제 전송까지 테스트하려면 환경변수 설정:

```powershell
$env:TELEGRAM_BOT_TOKEN="..."
$env:TELEGRAM_CHAT_ID="..."
py notify.py
```

## 수집처 추가하는 법

`notify.py` 상단의 딕셔너리에 추가하면 된다. 마지막에 `build_sources()`에서
카테고리와 필터 모드를 정해 연결한다.

1. **충남대 학과형 CMS** (글 링크에 `articleNo=`): `BOARDS`에 URL 추가. 끝.
2. **NTT형 CMS** (`selectNttList.do?mi=...&bbsId=...`): `NTT_BOARDS`에 목록 URL 추가.
3. **본부 포털형** (`_prog/_board/?code=...`): `PLUS_BOARDS`에 목록 URL 추가.
4. **위비티 다른 분야**: `WEVITY_BOARDS`에 `"이름": "cidx값"` 추가. 분야 코드는
   위비티 목록 페이지 링크의 `cidx=` 에서 확인 (1=기획/아이디어, 20=웹/모바일/IT,
   21=게임/소프트웨어, 22=과학/공학, 88=취업/창업 …).
5. **그 외 구조**: 새 파서 함수를 만들고 `build_sources()`에 `Source(...)`로 등록.

새 수집처의 필터 모드는 **등록일이 목록에 보이는가**로 정한다. 보이면 `MODE_DATE`,
마감 D-day만 있으면 `MODE_NEW`.

## 스케줄/기간 바꾸기

발송 시각: `.github/workflows/notify.yml`의 `cron` 값 수정. UTC 기준.
- 한국 오전 8시: `0 23 * * *`
- 한국 정오: `0 3 * * *`
- 하루 두 번 (오전 9시, 오후 6시): `0 0,9 * * *`

`greet.yml`의 주기는 3시간마다인데, 24시간보다 넉넉히 짧기만 하면 된다
(텔레그램의 update 보관 기간이 24시간이라 그 안에만 들어오면 놓치지 않는다).

7일 윈도우 변경: `notify.py` 상단의 `WINDOW_DAYS = 7` 값 수정.

수정 후 commit + push 하면 다음 실행부터 적용.

## 잘 안 될 때

- **Actions 실행이 빨간 X**: 워크플로우 클릭 → 실패 단계 펼치면 에러 로그. 대부분 Secrets 오타.
- **채널에 안 옴**: 로그에 `채널을 찾을 수 없음`이 찍혔는지 확인. 봇을 채널 **관리자**로
  넣지 않았거나, 관리자 권한에서 **메시지 게시**가 꺼져 있는 경우가 대부분이다.
  `TELEGRAM_CHAT_ID`의 채널명 앞에 `@`를 빠뜨린 경우도 흔하다.
- **개인 DM으로 안 옴**: 해당 사용자가 봇에게 `/start`를 보낸 적이 있어야 한다.
  텔레그램은 사용자가 먼저 말을 걸지 않은 봇의 메시지를 차단한다.
- **공모전/채용이 계속 안 옴**: 새로 올라온 게 없으면 안 온다(같은 건 두 번 안 보냄).
  `seen.json`을 지우고 다시 돌리면 기준선이 초기화된다.
- **특정 수집처만 0건**: 해당 사이트 구조가 바뀐 것. 한 곳이 실패해도 나머지는 정상 발송된다.
  DACON/링커리어는 페이지 내부 JSON 구조에 의존하므로 사이트 개편에 상대적으로 약하다.

## 파일 구조

```
cnu-notice-bot/
├── notify.py              수집 + 필터 + 텔레그램 발송 로직
├── roster.py              구독자 명부 열람 CLI (소유자 전용)
├── seen.json              이미 발송한 글번호 (공모전/인턴십/채용용, 자동 커밋)
├── subscribers.enc        암호화된 구독자 명부 (자동 커밋)
├── requirements.txt       파이썬 의존성 (requests, beautifulsoup4, cryptography)
├── .env.example           로컬 테스트용 환경변수 템플릿
├── .gitignore
├── README.md              이 파일
└── .github/
    └── workflows/
        ├── notify.yml     매일 1회 수집 + 발송
        └── greet.yml      3시간마다 /start 응대 + 명부 갱신
```

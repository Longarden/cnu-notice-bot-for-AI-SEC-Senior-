# CNU 컴퓨터인공지능학부 공지 알리미

충남대학교 컴퓨터인공지능학부 홈페이지의 4개 게시판(학사공지, 교내일반소식, 교외활동·인턴·취업, 사업단소식)을 매일 한 번씩 확인해서 최근 7일 이내에 올라온 공지를 텔레그램과 네이버 메일로 보내준다.

GitHub Actions의 무료 cron으로 동작하므로 개인 PC가 꺼져 있어도 알림이 온다.

## 동작 방식

- 매일 UTC 00:00 = 한국시간 오전 9시에 자동 실행
- 4개 게시판 각각 첫 페이지(최신 10~21건)를 스크래핑
- 게시물의 등록일이 오늘 기준 7일 이내인 것만 발송
- 같은 공지가 7일 동안 매일 반복해서 알림에 포함되므로, 하루 놓쳐도 다음날 다시 보임
- 텔레그램과 이메일 둘 다로 같은 내용 발송. 둘 중 한 채널의 자격증명만 등록해도 그 채널만 동작

## 처음 설정하는 법

### 1단계: 텔레그램 봇 만들기

1. 텔레그램에서 `@BotFather` 검색해서 대화 시작
2. `/newbot` 입력 → 이름 → username (반드시 `bot`으로 끝나야 함) 순서로 입력
3. BotFather가 보내준 토큰 복사 (예: `7123456789:AAFxxx...`)

### 2단계: chat_id 알아내기

가장 쉬운 방법은 `@userinfobot`에게 `/start` 보내기. 답장에 나오는 `Id:` 뒤의 숫자가 본인의 chat_id.

또는 본인 봇 대화방에서 `/start`를 보낸 뒤 다음 URL을 브라우저에서 열기 (TOKEN 자리에 1단계 토큰 넣기):

```
https://api.telegram.org/botTOKEN/getUpdates
```

응답 JSON의 `"chat":{"id": ...}` 안의 숫자가 chat_id.

### 3단계: 네이버 메일 SMTP 사용 설정 (한 번만)

PC에서 네이버 메일에 로그인 후 다음 URL 직접 열기:

```
https://mail.naver.com/option/imap
```

또는 네이버 메일 → 환경설정 → POP3/IMAP/SMTP 메뉴에서 다음 설정:

- IMAP/SMTP 사용: 사용함

저장 후 마무리. (POP3는 안 켜도 됨)

**중요**: 네이버 계정에 2단계 인증이 켜져 있으면 4단계에 등록할 비밀번호로 일반 비밀번호 대신 별도 발급받은 앱 비밀번호를 써야 한다. 2단계 인증이 꺼져 있으면 네이버 로그인 비밀번호 그대로 사용.

### 4단계: GitHub 저장소 만들기와 push

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

### 5단계: GitHub Secrets에 등록

repo 페이지 → Settings → Secrets and variables → Actions → New repository secret으로 4개 등록:

| Name | Value | 용도 |
|------|-------|------|
| `TELEGRAM_BOT_TOKEN` | 1단계 토큰 | 텔레그램 전송 |
| `TELEGRAM_CHAT_ID` | 2단계 숫자 | 텔레그램 전송 |
| `NAVER_USERNAME` | dmsakapt12@naver.com 같은 본인 네이버 이메일 전체 | 메일 전송 |
| `NAVER_PASSWORD` | 네이버 로그인 비밀번호 (2단계 인증 시 앱 비밀번호) | 메일 전송 |

텔레그램만 쓰고 싶으면 NAVER_* 두 개를 안 등록해도 됨. 반대로 이메일만 쓰고 싶으면 TELEGRAM_* 두 개를 빼도 됨.

수신자를 본인 네이버가 아닌 다른 주소로 받고 싶으면 추가로 `EMAIL_TO` 시크릿을 만들어서 그 주소를 넣으면 된다 (생략 시 NAVER_USERNAME 주소로 자기 자신에게 발송).

### 6단계: 첫 실행 테스트

repo 페이지 → Actions 탭 → 좌측 `CNU Notice Notifier` 클릭 → 우측 `Run workflow` → `Run workflow` 초록 버튼

1~2분 후 새로고침해서 결과 확인:
- 초록 체크 = 성공. 최근 7일 공지가 있으면 텔레그램과 메일로 도착
- 빨간 X = 실패. 워크플로우 클릭 → 실패한 단계 펼치면 로그 확인

이후 매일 한국시간 오전 9시에 자동 실행.

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
$env:NAVER_USERNAME="dmsakapt12@naver.com"
$env:NAVER_PASSWORD="..."
py notify.py
```

## 스케줄/기간 바꾸기

매일 실행 시각: `.github/workflows/notify.yml`의 `cron` 값 수정. UTC 기준.
- 한국 오전 8시: `0 23 * * *`
- 한국 정오: `0 3 * * *`
- 하루 두 번 (오전 9시, 오후 6시): `0 0,9 * * *`

7일 윈도우 변경: `notify.py` 상단의 `WINDOW_DAYS = 7` 값 수정. 14일로 늘리면 2주, 3일로 줄이면 3일.

수정 후 commit + push 하면 다음 실행부터 적용.

## 잘 안 될 때

- **Actions 실행이 빨간 X**: 워크플로우 클릭 → 실패 단계 펼치면 에러 로그. 99% Secrets 오타.
- **텔레그램만 안 옴**: 봇한테 직접 `/start` 보냈는지 확인. chat_id가 본인 개인 chat_id 맞는지 확인.
- **메일만 안 옴**: 네이버 메일 환경설정에서 SMTP 사용이 켜져 있는지 확인. 2단계 인증 사용 중이면 일반 비밀번호 대신 앱 비밀번호 필요.
- **사이트 구조 바뀜**: HTML이 변경되면 `notify.py`의 셀렉터 조정 필요.

## 파일 구조

```
cnu-notice-bot/
├── notify.py              스크래핑 + 텔레그램/메일 전송 로직
├── requirements.txt       파이썬 의존성 (requests, beautifulsoup4)
├── .env.example           로컬 테스트용 환경변수 템플릿
├── .gitignore
├── README.md              이 파일
└── .github/
    └── workflows/
        └── notify.yml     매일 실행하는 GitHub Actions cron
```

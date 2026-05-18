# CNU 컴퓨터인공지능학부 공지 알리미

충남대학교 컴퓨터인공지능학부 홈페이지의 4개 게시판(학사공지, 교내일반소식, 교외활동·인턴·취업, 사업단소식)을 매일 자동으로 확인해서 새 공지를 텔레그램으로 보내준다.

GitHub Actions의 무료 cron으로 동작하므로 개인 PC가 꺼져 있어도 알림이 온다.

---

## 처음 설정하는 법

### 1단계: 텔레그램 봇 만들기

1. 텔레그램에서 `@BotFather` 검색해서 대화 시작
2. `/newbot` 입력
3. 봇 이름 입력 (예: `CNU 공지 알리미`)
4. 봇 username 입력 (예: `cnu_notice_dmsak_bot`, 반드시 `bot`으로 끝나야 함)
5. BotFather가 알려주는 토큰 복사. 다음과 비슷한 형태:
   ```
   7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

### 2단계: chat_id 알아내기

1. 방금 만든 봇을 찾아서 (검색창에 봇 username 입력) 대화방 열고 `/start` 보내기
2. 브라우저에서 다음 URL을 연다 (`<BOT_TOKEN>` 자리에 1단계에서 받은 토큰 넣기):
   ```
   https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
   ```
3. 응답 JSON에서 `"chat":{"id":123456789,...}` 부분을 찾아 그 숫자가 chat_id
   - 예: `123456789`
   - 만약 `result`가 비어 있으면 봇한테 `/start`를 다시 보내고 새로고침

### 3단계: GitHub 저장소 만들기

1. https://github.com 가입 (계정 없으면)
2. https://github.com/new 에서 새 repo 생성
   - Repository name: `cnu-notice-bot` (아무 이름 가능)
   - **Private** 권장 (chat_id가 commit에 노출되면 누구나 봇 메시지 보낼 수 있음 — token만 안전하면 chat_id는 큰 문제는 아니지만 그래도)
   - "Add a README file" 체크 해제
3. 이 폴더(`C:\Users\dmsak\cnu-notice-bot`)에서 git 초기화 후 push:
   ```powershell
   cd C:\Users\dmsak\cnu-notice-bot
   git init
   git add .
   git commit -m "init: cnu notice bot"
   git branch -M main
   git remote add origin https://github.com/<USERNAME>/cnu-notice-bot.git
   git push -u origin main
   ```
   (`<USERNAME>` 자리에 본인 GitHub 사용자명)

### 4단계: GitHub Secrets에 토큰/chat_id 등록

1. 생성한 repo 페이지로 이동
2. 상단 메뉴 `Settings` → 좌측 `Secrets and variables` → `Actions`
3. `New repository secret` 클릭해서 두 개 추가:
   - Name: `TELEGRAM_BOT_TOKEN`, Secret: 1단계의 봇 토큰
   - Name: `TELEGRAM_CHAT_ID`, Secret: 2단계의 chat_id 숫자

### 5단계: 첫 실행 테스트

1. repo 페이지 → `Actions` 탭
2. 좌측 `CNU Notice Notifier` 워크플로우 선택
3. 우측 `Run workflow` 버튼 → `Run workflow` 클릭
4. 1~2분 후 완료. 첫 실행은 "초기화" 단계라 텔레그램 메시지는 안 가고 `seen.json`만 채워진다 (스팸 방지)
5. 다음날 새 공지가 있으면 자동으로 텔레그램에 도착

---

## 동작 방식

- **스케줄**: 매일 UTC 00:00 = 한국시간 오전 9시에 자동 실행
- **수집 범위**: 4개 게시판 각각 첫 페이지(최신 10건)
- **새 글 판정**: `seen.json`에 저장된 게시판별 마지막 articleNo보다 큰 글
- **상태 저장**: 매 실행 후 `seen.json`을 git commit & push로 갱신 (다음 실행에 전달)
- **메시지 형식**: 게시판별로 묶어서 제목 + 작성일 + 링크

## 로컬에서 테스트

스크래핑 동작만 확인하고 싶을 때:

```powershell
cd C:\Users\dmsak\cnu-notice-bot
py -m pip install -r requirements.txt
$env:DRY_RUN="1"
py notify.py
```

`DRY_RUN=1`이면 텔레그램 전송을 건너뛰고 콘솔에만 출력한다.

토큰을 받고 실제 전송까지 테스트하려면 `.env.example`을 `.env`로 복사해서 값을 채운 뒤:

```powershell
$env:TELEGRAM_BOT_TOKEN="여기에토큰"
$env:TELEGRAM_CHAT_ID="여기에chatid"
py notify.py
```

## 스케줄 시간 바꾸기

`.github/workflows/notify.yml`의 cron 값을 수정. cron은 UTC 기준.

- 한국시간 오전 8시 → `0 23 * * *`
- 한국시간 정오 → `0 3 * * *`
- 매일 9시와 18시 두 번 → `0 0,9 * * *`

수정 후 commit + push 하면 다음 실행부터 적용된다.

## 잘 안 될 때

- **Actions 탭의 워크플로우가 빨간 X**: 워크플로우 클릭 → 실패한 단계 펼치면 로그가 보인다. 토큰 오타가 가장 흔한 원인.
- **메시지가 안 옴**: 직접 대화방에서 봇에게 `/start` 했는지 확인. chat_id가 본인 개인 chat_id인지 확인.
- **사이트 구조 바뀜**: HTML 구조가 변경되면 `notify.py`의 셀렉터 (`table tbody tr`, `a[href*='articleNo=']`) 조정 필요.

## 파일 구조

```
cnu-notice-bot/
├── notify.py                    스크래핑 + 텔레그램 전송 로직
├── requirements.txt             파이썬 의존성
├── seen.json                    게시판별 마지막 본 articleNo (자동 갱신)
├── .env.example                 로컬 테스트용 환경변수 템플릿
├── .gitignore
├── README.md                    이 파일
└── .github/
    └── workflows/
        └── notify.yml           매일 실행하는 GitHub Actions cron
```

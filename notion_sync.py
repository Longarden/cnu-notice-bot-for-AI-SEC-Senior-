"""
발송된 공지를 Notion 데이터베이스('인턴 지원 일정')에 일정으로 올린다.

notify.py가 텔레그램 발송과 seen.json 확정을 모두 끝낸 뒤에 부르는 부가 기능이다.
여기서 무슨 일이 생겨도 알림 발송에는 영향이 없어야 하므로:
  - notify를 import하지 않는다(순환 import 방지). 아이콘과 날짜 파서는 인자로 받는다.
  - sync_to_notion()은 절대 예외를 밖으로 던지지 않는다.
  - 기존 일정 조회가 실패하면 중복을 만들 수 있으므로 아무것도 만들지 않는다.
  - 인증 오류·서버 장애·연결 오류가 나면 바로 멈추고, 전체 작업은 시간 예산 안에서 끝낸다.

Notion 캘린더는 DB의 날짜 속성으로 일정을 그린다. 페이지 하나 = 일정 하나.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

NOTION_API = "https://api.notion.com/v1"
# 2025-09-03부터는 data source 개념이 들어왔지만, 이 버전은 /databases/{id}/query를 유지한다.
NOTION_VERSION = "2022-06-28"

KST = ZoneInfo("Asia/Seoul")

# 분류 select 옵션 이름. notify.py의 카테고리 상수와 같은 문자열이다.
# 색(학교공지 초록, 공모전 보라, 인턴십 주황, 채용 분홍)은 Notion DB에 미리 만들어 둔다.
# API는 없는 옵션 이름을 받으면 색을 무작위로 정해 새로 만들기 때문이다.
CATEGORIES = ("학교공지", "공모전", "인턴십", "채용")

REQUEST_TIMEOUT = 10  # 요청 하나당 초
WRITE_INTERVAL = 0.35  # Notion 평균 한도(초당 3회) 아래로 유지
TIME_BUDGET = 90.0  # 동기화 전체 상한(초). 넘으면 새 요청을 시작하지 않는다
LOOKBACK_DAYS = 60  # 중복 확인용으로 읽어 올 기존 페이지 범위. 학교공지 7일 반복을 넉넉히 덮는다

# 링커리어/점핏: "주최사 · ~2026.11.30"
_DEADLINE_RE = re.compile(r"~(\d{4})\.(\d{2})\.(\d{2})")
# 위비티: "주최사 · D-12 ..." . 한글이 바로 붙어도 잡히도록 \b 대신 lookaround를 쓴다.
_DDAY_RE = re.compile(r"(?<![A-Za-z0-9])D-(\d+)(?!\d)")
_TODAY_RE = re.compile(r"(?<![A-Za-z0-9])D-DAY|오늘", re.IGNORECASE)


class _Stop(Exception):
    """더 진행하면 안 되는 오류. 남은 작업을 모두 건너뛴다."""


def today_kst() -> date:
    return datetime.now(KST).date()


def notice_date(n, today: date, parse_date) -> date:
    """캘린더에 찍을 날짜. 마감일 → 등록일 → 실행일 순으로 고른다."""
    extra = n.extra or ""

    m = _DEADLINE_RE.search(extra)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    m = _DDAY_RE.search(extra)
    if m:
        return today + timedelta(days=int(m.group(1)))
    if _TODAY_RE.search(extra):
        return today

    posted = parse_date(n.date)
    if posted:
        return posted

    if extra:
        print(f"[Notion] 날짜를 찾지 못해 실행일로 등록: {extra}", file=sys.stderr)
    return today


def dedupe_key(n) -> str:
    """메모 칸에 넣는 중복 판단 키.

    대부분은 URL에 글번호가 들어 있어 URL만으로 유일하다. 비교과 프로그램은
    모든 글이 같은 메인 주소로 연결되므로 #글번호를 붙여 구분한다(링크는 그대로 열린다).
    """
    if str(n.article_no) in n.url:
        return n.url
    return f"{n.url}#{n.article_no}"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _post(session, url: str, token: str, payload: dict, deadline: float):
    """POST 한 번. 429는 한 번만 재시도하고, 계속할 수 없는 오류는 _Stop으로 올린다."""
    for attempt in range(2):
        if time.monotonic() > deadline:
            raise _Stop("시간 예산 초과")
        try:
            resp = session.post(
                url, headers=_headers(token), json=payload, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise _Stop(f"연결 오류 {type(exc).__name__}") from None

        if resp.status_code == 429 and attempt == 0:
            try:
                wait = float(resp.headers.get("Retry-After", "1"))
            except ValueError:
                wait = 1.0
            time.sleep(min(max(wait, 0.0), 10.0))
            continue
        if resp.status_code in (401, 403, 404, 429) or resp.status_code >= 500:
            raise _Stop(f"HTTP {resp.status_code}")
        return resp
    raise _Stop("재시도 초과")


def load_existing_keys(
    session, token: str, db_id: str, today: date, deadline: float
) -> set[str]:
    """봇이 최근에 만든 페이지들의 메모(중복 키)를 모은다. 실패하면 _Stop."""
    since = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    query = {
        "and": [
            {"or": [{"property": "분류", "select": {"equals": c}} for c in CATEGORIES]},
            {"timestamp": "created_time", "created_time": {"on_or_after": since}},
        ]
    }
    keys: set[str] = set()
    cursor = None
    while True:
        payload: dict = {"filter": query, "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        resp = _post(session, f"{NOTION_API}/databases/{db_id}/query", token, payload, deadline)
        if not resp.ok:
            raise _Stop(f"기존 일정 조회 실패 HTTP {resp.status_code}")
        data = resp.json()
        for page in data.get("results", []):
            memo = page.get("properties", {}).get("메모", {}).get("rich_text", [])
            text = "".join(part.get("plain_text", "") for part in memo).strip()
            if text:
                keys.add(text)
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            return keys


def page_payload(n, db_id: str, icons: dict[str, str], when: date, key: str) -> dict:
    title = f"{icons.get(n.category, '')} {n.title}".strip()
    return {
        "parent": {"database_id": db_id},
        "properties": {
            "이름": {"title": [{"text": {"content": title[:2000]}}]},
            "날짜": {"date": {"start": when.isoformat()}},
            "분류": {"select": {"name": n.category}},
            "메모": {"rich_text": [{"text": {"content": key[:2000]}}]},
        },
    }


def sync_to_notion(
    notices,
    token: str,
    db_id: str,
    icons: dict[str, str],
    parse_date,
    *,
    session=None,
    today: date | None = None,
) -> dict:
    """공지들을 Notion에 올리고 결과 건수를 돌려준다. 예외를 던지지 않는다."""
    result: dict = {"created": 0, "skipped": 0, "failed": 0, "aborted": None}
    try:
        session = session or requests.Session()
        today = today or today_kst()
        deadline = time.monotonic() + TIME_BUDGET

        existing = load_existing_keys(session, token, db_id, today, deadline)

        for n in notices:
            key = dedupe_key(n)
            if key in existing:
                result["skipped"] += 1
                continue
            when = notice_date(n, today, parse_date)
            resp = _post(
                session,
                f"{NOTION_API}/pages",
                token,
                page_payload(n, db_id, icons, when, key),
                deadline,
            )
            if resp.ok:
                existing.add(key)  # 같은 실행 안의 중복도 막는다
                result["created"] += 1
            else:
                result["failed"] += 1
                print(
                    f"[Notion] 일정 생성 실패 HTTP {resp.status_code}: {n.title[:40]}",
                    file=sys.stderr,
                )
            time.sleep(WRITE_INTERVAL)
    except _Stop as exc:
        result["aborted"] = str(exc)
    except Exception as exc:  # 어떤 경우에도 호출자(텔레그램 경로)로 새지 않게
        result["aborted"] = type(exc).__name__
    return result

"""
CNU 공지 · 공모전 · 인턴십 · 채용 알리미.

수집 대상은 네 갈래다.
  - 학교공지: 충남대 9개 게시판 (등록일이 있으므로 '최근 N일' 윈도우로 거른다)
  - 공모전  : 위비티 IT/SW/공학 분야, DACON AI 경진대회
  - 인턴십  : 링커리어 인턴 공고
  - 채용    : 점핏 신입 개발자 포지션

공모전/인턴십/채용 사이트는 '등록일'을 노출하지 않고 마감 D-day만 주기 때문에
날짜 윈도우로 거를 수 없다. 그래서 이 카테고리는 seen.json에 이미 본 글번호를
기록해두고 '처음 보는 글'만 발송한다. 두 가지 필터 모드가 공존하는 이유다.

발송 대상은 두 갈래를 합친 것이다.
  - 봇에게 /start를 보낸 구독자 전원 (subscribers.enc에 암호화 저장)
  - TELEGRAM_CHAT_ID에 명시한 대상. 채널(@이름)과 개인 chat_id를 콤마로 여러 개 가능

즉 설정을 바꾸지 않아도 /start만 하면 알림을 받는다. 채널은 선택 사항이다.
차단·탈퇴한 대상은 발송 실패 사유를 보고 명부에서 자동으로 빠진다.

GitHub Actions cron으로 매일 실행되도록 설계됐다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import smtplib
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ── 카테고리 ────────────────────────────────────────────────────────────
CAT_SCHOOL = "학교공지"
CAT_CONTEST = "공모전"
CAT_INTERN = "인턴십"
CAT_JOB = "채용"

# 발송 메시지에서 카테고리를 노출하는 순서와 아이콘
CATEGORY_ORDER = [CAT_SCHOOL, CAT_CONTEST, CAT_INTERN, CAT_JOB]
CATEGORY_ICON = {
    CAT_SCHOOL: "🏫",
    CAT_CONTEST: "🏆",
    CAT_INTERN: "🧑‍💻",
    CAT_JOB: "💼",
}

# 필터 모드
MODE_DATE = "date"  # 등록일이 있는 게시판: 최근 WINDOW_DAYS일 이내만
MODE_NEW = "new"    # 등록일이 없는 사이트: seen.json에 없는 글번호만

STATE_DIR = Path(__file__).resolve().parent
SEEN_PATH = STATE_DIR / "seen.json"
ROSTER_PATH = STATE_DIR / "subscribers.enc"

# 한 게시판당 seen에 유지할 최대 글번호 수(무한 증가 방지)
SEEN_KEEP = 400

BASE = "https://computer.cnu.ac.kr"

BOARDS: dict[str, str] = {
    "학사공지": "/computer/notice/bachelor.do",
    "교내일반소식": "/computer/notice/notice.do",
    "교외활동·인턴·취업": "/computer/notice/job.do",
    "사업단소식": "/computer/notice/project.do",
    # 국제교류본부는 학과 사이트와 같은 CMS(articleNo=)라 전체 URL로 재사용
    "국제교류·모집공지": "https://cnuint.cnu.ac.kr/cnuint/notice/recruit.do",
    "국제교류·행사공지": "https://cnuint.cnu.ac.kr/cnuint/notice/event.do",
}

# NTT 계열 CMS 게시판(selectNttList.do 패턴). 학과 사이트와 HTML 구조가 달라
# fetch_ntt_board()로 파싱한다. 값은 목록 페이지 전체 URL.
NTT_BOARDS: dict[str, str] = {
    "정보보호특성화대학": (
        "https://csrc.cnu.ac.kr/csrc/na/ntt/selectNttList.do?mi=1027&bbsId=1005"
    ),
}

# 본부 포털(plus.cnu.ac.kr) _prog/_board 게시판. td.title a 링크의 no= 가 글번호.
PLUS_BOARDS: dict[str, str] = {
    "교육정보(본부)": (
        "https://plus.cnu.ac.kr/_prog/_board/"
        "?code=sub07_0704&site_dvs_cd=kr&menu_dvs_cd=0704"
    ),
}

# CNU With U+(비교과 통합관리). 목록이 AJAX(addDiv.do POST)로 로드되어
# 엔드포인트를 직접 호출한다. 값은 addType 코드(0029=교내비교과).
WITH_BOARDS: dict[str, str] = {
    "비교과 프로그램": "0029",
}

WITH_ADDDIV_URL = "https://with.cnu.ac.kr/non/htmlAdd/addDiv.do"
WITH_LIST_PAGE = "https://with.cnu.ac.kr/"

# ── 공모전 ──────────────────────────────────────────────────────────────
# 위비티(wevity.com) 분야별 목록. 값은 cidx(분야 코드).
# robots.txt는 목록 페이지 크롤을 허용한다(User-agent: * / Allow: /).
WEVITY_BASE = "https://www.wevity.com/"
WEVITY_BOARDS: dict[str, str] = {
    "위비티·웹/모바일/IT": "20",
    "위비티·게임/소프트웨어": "21",
    "위비티·과학/공학": "22",
}

# DACON은 Nuxt SPA라 목록 데이터가 window.__NUXT__ 페이로드 안에 인라인으로 들어온다.
DACON_LIST_URL = "https://dacon.io/competitions"
DACON_DETAIL = "https://dacon.io/competitions/official/{cpt_id}/overview/description"

# ── 인턴십 ──────────────────────────────────────────────────────────────
# 링커리어는 Next.js라 __NEXT_DATA__ script 태그의 JSON을 그대로 읽는다.
LINKAREER_LIST_URL = "https://linkareer.com/list/intern"
LINKAREER_DETAIL = "https://linkareer.com/activity/{activity_id}"

# ── 채용 ────────────────────────────────────────────────────────────────
# 점핏(사람인)은 공개 JSON API를 제공한다. career=0 이 신입 필터.
JUMPIT_API = "https://api.jumpit.co.kr/api/positions"
JUMPIT_DETAIL = "https://jumpit.saramin.co.kr/position/{position_id}"
JUMPIT_BOARDS: dict[str, dict[str, str]] = {
    "점핏·신입 개발자": {"sort": "reg_dt", "career": "0", "page": "1"},
}

WINDOW_DAYS = 7

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

TIMEOUT = 20

NAVER_SMTP_HOST = "smtp.naver.com"
NAVER_SMTP_PORT = 587


@dataclass
class Notice:
    board: str
    article_no: int
    title: str
    date: str
    url: str
    # 공모전/채용은 카테고리와 부가정보(주최사·회사명·마감 D-day)가 본문만큼 중요하다.
    category: str = CAT_SCHOOL
    extra: str = ""


@dataclass
class Source:
    """수집 대상 하나. fetch(board, target)을 호출하면 Notice 목록이 나온다."""

    board: str
    category: str
    target: object
    fetch: object
    mode: str = MODE_DATE


def parse_date(s: str) -> date | None:
    if not s:
        return None
    for fmt in (
        "%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d",
        "%y.%m.%d", "%y-%m-%d", "%y/%m/%d",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fetch_board(board: str, path: str) -> list[Notice]:
    url = urljoin(BASE, path)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    notices: list[Notice] = []

    rows = soup.select("table tbody tr")
    for row in rows:
        link = row.select_one("a[href*='articleNo=']")
        if not link:
            continue

        href = link.get("href", "")
        m = re.search(r"articleNo=(\d+)", href)
        if not m:
            continue
        article_no = int(m.group(1))

        title = link.get_text(strip=True)
        if not title:
            continue

        date_str = ""
        b_date = row.select_one("span.b-date")
        if b_date:
            date_str = b_date.get_text(strip=True)
        if not date_str:
            for td in row.select("td"):
                txt = td.get_text(strip=True)
                if re.fullmatch(r"\d{2,4}[./-]\d{2}[./-]\d{2}", txt):
                    date_str = txt
                    break

        full_url = urljoin(url, href)
        notices.append(
            Notice(
                board=board,
                article_no=article_no,
                title=title,
                date=date_str,
                url=full_url,
            )
        )

    return notices


def fetch_ntt_board(board: str, list_url: str) -> list[Notice]:
    """NTT 계열 CMS 게시판 파싱.

    제목 링크가 href="javascript:"라 URL이 없고, data-id 속성의 글번호(nttSn)로
    상세 URL(selectNttInfo.do?...&nttSn=)을 직접 조립한다.
    """
    resp = requests.get(list_url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    notices: list[Notice] = []

    for row in soup.select("table tbody tr"):
        link = row.select_one("a.nttInfoBtn[data-id]")
        if not link:
            continue

        ntt_sn_raw = link.get("data-id", "")
        if not str(ntt_sn_raw).isdigit():
            continue
        ntt_sn = int(ntt_sn_raw)

        title = link.get_text(strip=True)
        if not title:
            continue

        date_str = ""
        for td in row.select("td"):
            txt = td.get_text(strip=True)
            if re.fullmatch(r"\d{2,4}[./-]\d{2}[./-]\d{2}", txt):
                date_str = txt
                break

        detail_url = (
            list_url.replace("selectNttList.do", "selectNttInfo.do")
            + f"&nttSn={ntt_sn}"
        )
        notices.append(
            Notice(
                board=board,
                article_no=ntt_sn,
                title=title,
                date=date_str,
                url=detail_url,
            )
        )

    return notices


def fetch_plus_board(board: str, list_url: str) -> list[Notice]:
    """본부 포털(_prog/_board) 게시판 파싱. 글번호는 링크의 no= 파라미터."""
    resp = requests.get(list_url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    notices: list[Notice] = []

    for row in soup.select("table tbody tr"):
        link = row.select_one("td.title a")
        if not link:
            continue

        href = link.get("href", "")
        m = re.search(r"[?&]no=(\d+)", href)
        if not m:
            continue

        title = link.get_text(strip=True)
        if not title:
            continue

        date_str = ""
        date_td = row.select_one("td.date")
        if date_td:
            date_str = date_td.get_text(strip=True)

        notices.append(
            Notice(
                board=board,
                article_no=int(m.group(1)),
                title=title,
                date=date_str,
                url=urljoin(list_url, href),
            )
        )

    return notices


def fetch_with_programs(board: str, add_type: str) -> list[Notice]:
    """CNU With U+ 비교과 프로그램 파싱.

    목록은 addDiv.do에 AJAX POST로만 내려온다. 상세는 로그인 다이얼로그라
    직링크가 없어 메인 페이지를 링크한다. 날짜는 접수 시작일을 쓴다
    (접수 시작 후 WINDOW_DAYS 동안 알림에 잡힘). 글번호가 해시 문자열이라
    앞 8자리 16진수를 정수로 변환해 쓴다.
    """
    resp = requests.post(
        WITH_ADDDIV_URL,
        data={"addType": add_type},
        headers={**HEADERS, "ajax": "true"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    notices: list[Notice] = []
    seen_ids: set[int] = set()

    for a in soup.select("li a[onclick*='nonLogin']"):
        tit = a.select_one("p.cprom_tit")
        if not tit:
            continue
        title = tit.get_text(strip=True)
        if not title:
            continue

        m = re.search(r"nonLogin\('([0-9a-f]+)'\)", a.get("onclick", ""))
        if not m:
            continue
        article_no = int(m.group(1)[:8], 16)
        if article_no in seen_ids:
            continue
        seen_ids.add(article_no)

        date_str = ""
        date_dd = a.select_one("dl.date dd")
        if date_dd:
            period = date_dd.get_text(strip=True)
            date_str = period.split("~")[0].strip()

        notices.append(
            Notice(
                board=board,
                article_no=article_no,
                title=title,
                date=date_str,
                url=WITH_LIST_PAGE,
            )
        )

    return notices


def fetch_wevity(board: str, cidx: str) -> list[Notice]:
    """위비티 분야별 공모전 목록 파싱.

    목록에 등록일이 없고 마감 D-day만 있어서 날짜 필터를 못 쓴다(MODE_NEW 사용).
    글번호는 상세 링크의 ix= 파라미터.
    """
    url = f"{WEVITY_BASE}?c=find&s=1&gub=1&cidx={cidx}&gbn=list"
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    notices: list[Notice] = []

    for li in soup.select("ul.list li"):
        # 첫 li는 '공모전명/주최사/현재현황' 헤더 행이라 건너뛴다
        if "top" in (li.get("class") or []):
            continue

        link = li.select_one("div.tit a[href*='ix=']")
        if not link:
            continue
        m = re.search(r"ix=(\d+)", link.get("href", ""))
        if not m:
            continue

        # 제목 옆 'SPECIAL' 같은 배지 span은 제목이 아니므로 떼어낸다
        for span in link.select("span"):
            span.decompose()
        title = link.get_text(strip=True)
        if not title:
            continue

        bits: list[str] = []
        organ = li.select_one("div.organ")
        if organ and organ.get_text(strip=True):
            bits.append(organ.get_text(strip=True))
        day = li.select_one("div.day")
        if day:
            status = " ".join(day.get_text(" ", strip=True).split())
            if status:
                bits.append(status)

        notices.append(
            Notice(
                board=board,
                article_no=int(m.group(1)),
                title=title,
                date="",
                url=urljoin(WEVITY_BASE, link.get("href", "")),
                category=CAT_CONTEST,
                extra=" · ".join(bits),
            )
        )

    return notices


def fetch_dacon(board: str, list_url: str) -> list[Notice]:
    """DACON AI 경진대회 목록 파싱.

    Nuxt SPA라 HTML에 목록 DOM이 없고, window.__NUXT__ 자바스크립트 페이로드
    안에 cpt_id/name 형태로 인라인돼 있다. JSON이 아니라 최소화된 JS 표현식이라
    정규식으로 (대회번호, 이름) 쌍만 뽑아낸다.
    """
    resp = requests.get(list_url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    start = resp.text.find("__NUXT__")
    if start < 0:
        raise RuntimeError("__NUXT__ 페이로드 없음 (DACON 페이지 구조 변경 가능성)")
    payload = resp.text[start:]

    notices: list[Notice] = []
    seen_ids: set[int] = set()

    for m in re.finditer(r'cpt_id:(\d+),.{0,300}?name:"((?:[^"\\]|\\.)*)"', payload, re.S):
        cpt_id = int(m.group(1))
        if cpt_id in seen_ids:
            continue
        seen_ids.add(cpt_id)

        title = m.group(2).replace('\\"', '"').replace("\\/", "/").strip()
        if not title:
            continue

        notices.append(
            Notice(
                board=board,
                article_no=cpt_id,
                title=title,
                date="",
                url=DACON_DETAIL.format(cpt_id=cpt_id),
                category=CAT_CONTEST,
                extra="DACON",
            )
        )

    return notices


def fetch_linkareer(board: str, list_url: str) -> list[Notice]:
    """링커리어 인턴 공고 파싱.

    Next.js라 __NEXT_DATA__ script의 JSON을 읽는다. 목록 배열(activityItems)은
    url/name만 주고, 주최사와 마감일은 같은 JSON의 아폴로 캐시에 들어 있어서
    있으면 붙이고 없으면 조용히 생략한다.
    """
    resp = requests.get(list_url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    tag = soup.select_one("script#__NEXT_DATA__")
    if not tag:
        raise RuntimeError("__NEXT_DATA__ 없음 (링커리어 페이지 구조 변경 가능성)")

    data = json.loads(tag.string or tag.get_text())
    page_props = data.get("props", {}).get("pageProps", {})
    apollo = page_props.get("__APOLLO_STATE__", {}) or {}

    notices: list[Notice] = []
    for item in page_props.get("activityItems") or []:
        url = item.get("url") or ""
        m = re.search(r"/activity/(\d+)", url)
        if not m:
            continue
        activity_id = int(m.group(1))

        title = (item.get("name") or "").strip()
        if not title:
            continue

        bits: list[str] = []
        cached = apollo.get(f"Activity:{activity_id}") or {}
        org = (cached.get("organizationName") or "").strip()
        if org:
            bits.append(org)
        close_ms = cached.get("recruitCloseAt")
        if isinstance(close_ms, (int, float)) and close_ms > 0:
            try:
                bits.append(
                    "~" + datetime.fromtimestamp(close_ms / 1000).strftime("%Y.%m.%d")
                )
            except (OverflowError, OSError, ValueError):
                pass

        notices.append(
            Notice(
                board=board,
                article_no=activity_id,
                title=title,
                date="",
                url=LINKAREER_DETAIL.format(activity_id=activity_id),
                category=CAT_INTERN,
                extra=" · ".join(bits),
            )
        )

    return notices


def fetch_jumpit(board: str, params: dict[str, str]) -> list[Notice]:
    """점핏 신입 개발자 채용공고 파싱. 공개 JSON API라 HTML 파싱이 필요 없다."""
    resp = requests.get(
        JUMPIT_API,
        params=params,
        headers={**HEADERS, "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()

    notices: list[Notice] = []
    for pos in body.get("result", {}).get("positions", []) or []:
        position_id = pos.get("id")
        title = (pos.get("title") or "").strip()
        if not position_id or not title:
            continue

        bits: list[str] = []
        company = (pos.get("companyName") or "").strip()
        if company:
            bits.append(company)
        closed_at = (pos.get("closedAt") or "")[:10]
        if closed_at:
            bits.append("~" + closed_at.replace("-", "."))
        elif pos.get("alwaysOpen"):
            bits.append("상시채용")

        notices.append(
            Notice(
                board=board,
                article_no=int(position_id),
                title=title,
                date="",
                url=JUMPIT_DETAIL.format(position_id=position_id),
                category=CAT_JOB,
                extra=" · ".join(bits),
            )
        )

    return notices


def load_seen() -> dict[str, list[int]]:
    """이미 발송한 글번호 저장소를 읽는다. 없거나 깨졌으면 빈 상태로 시작한다."""
    if not SEEN_PATH.exists():
        return {}
    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"seen.json 읽기 실패, 빈 상태로 시작: {exc}", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: [int(i) for i in v] for k, v in data.items() if isinstance(v, list)}


def save_seen(seen: dict[str, list[int]]) -> None:
    trimmed = {k: sorted(set(v), reverse=True)[:SEEN_KEEP] for k, v in seen.items()}
    SEEN_PATH.write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )


def filter_new(
    board: str, notices: list[Notice], seen: dict[str, list[int]]
) -> list[Notice]:
    """seen에 없는 글만 남기고, 본 것으로 표시한다.

    해당 게시판을 처음 수집하는 경우(seen에 키 자체가 없음)에는 아무것도 발송하지
    않고 현재 목록 전체를 '본 것'으로 기록만 한다. 소스를 새로 추가할 때마다
    수십 건이 한꺼번에 쏟아지는 걸 막기 위한 장치다.
    """
    known = seen.get(board)
    ids = [n.article_no for n in notices]

    if known is None:
        seen[board] = ids
        print(f"[{board}] 최초 수집 {len(ids)}건 - 기준선으로 기록만 하고 발송 생략")
        return []

    known_set = set(known)
    fresh = [n for n in notices if n.article_no not in known_set]
    seen[board] = known + [n.article_no for n in fresh]
    return fresh


def filter_recent(notices: list[Notice], days: int = WINDOW_DAYS) -> list[Notice]:
    today = date.today()
    result: list[Notice] = []
    for n in notices:
        d = parse_date(n.date)
        if d is None:
            continue
        delta = (today - d).days
        if 0 <= delta <= days:
            result.append(n)
    result.sort(key=lambda x: (x.board, -x.article_no))
    return result


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def roster_key(token: str) -> bytes:
    """구독자 명부 암호화 키를 만든다.

    저장소가 공개(public)라서 chat_id를 평문으로 커밋하면 구독자의 텔레그램
    식별자가 그대로 노출된다. 그래서 명부는 암호문(subscribers.enc)으로만
    커밋하고, 키는 이미 소유자만 갖고 있는 봇 토큰에서 파생시킨다. 이러면
    새 GitHub Secret을 추가하지 않아도 사실상 소유자 전용이 된다.

    봇 토큰을 재발급하면 기존 명부를 못 읽으므로, 그럴 땐 ROSTER_KEY 환경변수에
    옛 토큰을 넣어 고정할 수 있다.
    """
    material = os.environ.get("ROSTER_KEY", "").strip() or token
    digest = hashlib.sha256(f"cnu-notice-bot-roster:{material}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def load_roster(token: str) -> dict[str, dict]:
    """암호화된 명부를 복호화해서 읽는다. 못 읽으면 빈 명부로 시작한다."""
    if not ROSTER_PATH.exists():
        return {}
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        print("cryptography 미설치 - 명부 기능 건너뜀", file=sys.stderr)
        return {}

    try:
        raw = Fernet(roster_key(token)).decrypt(ROSTER_PATH.read_bytes())
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, json.JSONDecodeError, OSError, ValueError) as exc:
        print(
            f"명부 복호화 실패({type(exc).__name__}). 봇 토큰이 바뀌었다면 "
            f"ROSTER_KEY에 이전 토큰을 넣으세요. 이번 실행은 빈 명부로 진행합니다.",
            file=sys.stderr,
        )
        return {}
    return data if isinstance(data, dict) else {}


def save_roster(token: str, roster: dict[str, dict]) -> bool:
    """명부를 암호화해서 저장한다. 성공하면 True."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        print("cryptography 미설치 - 명부 저장 건너뜀", file=sys.stderr)
        return False

    payload = json.dumps(roster, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ROSTER_PATH.write_bytes(Fernet(roster_key(token)).encrypt(payload))
    return True


def parse_chat_ids(raw: str) -> list[str]:
    """TELEGRAM_CHAT_ID를 콤마/줄바꿈으로 나눠 수신 대상 목록으로 만든다.

    개인 chat_id(숫자)와 채널(@채널명)을 섞어 넣을 수 있고, 중복은 순서를
    유지한 채 제거한다. 채널 전환 기간에 개인 DM과 채널로 동시에 보내다가,
    안정되면 채널만 남기는 식으로 쓴다.
    """
    targets: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        cid = part.strip()
        if cid and cid not in targets:
            targets.append(cid)
    return targets


def telegram_api(token: str, method: str, **params) -> dict:
    """봇 API 호출 후 JSON을 돌려준다. ok=false면 description을 담아 예외."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    resp = requests.post(url, data=params, timeout=TIMEOUT)
    try:
        body = resp.json()
    except ValueError:
        raise RuntimeError(f"{method} HTTP {resp.status_code}: {resp.text[:200]}")
    if not body.get("ok"):
        raise RuntimeError(
            f"{method} 실패 (code={body.get('error_code')}): "
            f"{body.get('description', resp.text[:200])}"
        )
    return body.get("result", {})


def send_telegram(token: str, chat_id: str, text: str) -> None:
    telegram_api(
        token,
        "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# 다시 시도해도 소용없는 실패들. 명부에서 그 사람을 빼는 기준이 된다.
# 한국어 문구는 diagnose_target()이 직접 쓴 것이고, 영문은 텔레그램 원문이다.
PERMANENT_FAILURE_MARKERS = (
    "차단",
    "대화방을 찾을 수 없음",
    "탈퇴한 계정",
    "bot was blocked",
    "user is deactivated",
    "chat not found",
    "bot was kicked",
)


def is_permanent_failure(reason: str) -> bool:
    return any(marker in reason for marker in PERMANENT_FAILURE_MARKERS)


def diagnose_target(token: str, chat_id: str) -> str:
    """발송 전에 대상이 실제로 보낼 수 있는 곳인지 확인한다.

    문제 없으면 빈 문자열, 있으면 사람이 읽고 바로 고칠 수 있는 한국어 사유를
    돌려준다. 채널 방식에서 가장 흔한 사고(봇을 관리자로 안 넣음, 채널명 오타)를
    발송 실패가 아니라 명시적 진단으로 잡아내는 게 목적이다.
    """
    try:
        telegram_api(token, "getChat", chat_id=chat_id)
    except RuntimeError as exc:
        msg = str(exc)
        if "chat not found" in msg:
            if chat_id.startswith("@"):
                return (
                    "채널을 찾을 수 없음. 채널명 오타이거나, "
                    "봇(@cnu_alarmbot)을 아직 채널 관리자로 추가하지 않았습니다."
                )
            return "대화방을 찾을 수 없음. 봇에게 /start를 보낸 적이 있는지 확인하세요."
        if "bot was blocked" in msg:
            return "사용자가 봇을 차단했습니다."
        if "user is deactivated" in msg:
            return "탈퇴한 계정입니다."
        return msg
    return ""


def handle_commands(
    token: str, channel_link: str, roster: dict[str, dict]
) -> tuple[int, int]:
    """봇에게 온 /start·/stop을 처리하고 (구독 수, 해지 수)를 돌려준다.

    /start를 보낸 사람은 그 자리에서 명부에 올라가고, 다음 발송부터 알림을 받는다.
    사용자가 링크를 타고 들어와 /start를 눌렀는데 아무 일도 안 일어나던 게 원래
    버그였으므로, 여기서 반드시 확인 메시지를 돌려준다.

    처리한 update는 offset으로 확인 응답해 서버에서 지운다(중복 처리 방지).
    주의: 텔레그램은 미확인 update를 24시간만 보관하므로, 이 함수를 도는
    워크플로우 주기가 24시간을 넘으면 그 사이 온 /start를 놓친다.
    """
    try:
        updates = telegram_api(
            token, "getUpdates", timeout=0, allowed_updates='["message"]'
        )
    except RuntimeError as exc:
        print(f"getUpdates 실패(무시하고 진행): {exc}", file=sys.stderr)
        return 0, 0

    if not updates:
        return 0, 0

    channel_line = (
        f'\n\n채널로도 보고 싶으면: <a href="{escape_html(channel_link)}">'
        f"{escape_html(channel_link)}</a>"
        if channel_link
        else ""
    )

    subscribed: set[str] = set()
    unsubscribed: set[str] = set()
    last_update_id = 0

    for upd in updates:
        last_update_id = max(last_update_id, int(upd.get("update_id", 0)))
        message = upd.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        cid = str(chat.get("id", ""))
        if not cid or chat.get("type") != "private":
            continue

        if text.startswith("/stop"):
            roster.pop(cid, None)
            unsubscribed.add(cid)
            reply = (
                "구독을 해지했습니다. 더 이상 알림을 보내지 않습니다.\n"
                "다시 받으시려면 /start 를 보내주세요."
            )
        elif text.startswith("/start"):
            # 최초 유입 시각은 보존하고 이름·최근 접속만 갱신한다
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = roster.get(cid) or {"first_seen": stamp}
            entry["name"] = " ".join(
                p for p in (chat.get("first_name"), chat.get("last_name")) if p
            ).strip()
            entry["username"] = chat.get("username") or ""
            entry["last_start"] = stamp
            roster[cid] = entry
            subscribed.add(cid)
            reply = (
                "<b>📢 CNU 알리미 구독 완료</b>\n\n"
                "이제 매일 아침 9시에 이 대화방으로 알림이 옵니다.\n\n"
                "🏫 충남대 공지 9개 게시판 (최근 7일)\n"
                "🏆 AI·IT 공모전 (위비티, DACON)\n"
                "🧑‍💻 인턴십 (링커리어)\n"
                "💼 신입 채용 (점핏)\n\n"
                "그만 받으시려면 /stop 을 보내주세요." + channel_line
            )
        else:
            continue

        try:
            send_telegram(token, cid, reply)
        except RuntimeError as exc:
            print(f"응답 실패 chat_id={cid}: {exc}", file=sys.stderr)

    # 처리한 update를 확인 응답해 서버에서 제거(다음 실행 때 중복 처리 방지)
    if last_update_id:
        try:
            telegram_api(token, "getUpdates", offset=last_update_id + 1, timeout=0)
        except RuntimeError as exc:
            print(f"getUpdates offset 확인 실패: {exc}", file=sys.stderr)

    return len(subscribed), len(unsubscribed)


def broadcast(
    token: str, chat_ids: list[str], chunks: list[str], header: str
) -> tuple[list[str], list[tuple[str, str]]]:
    """모든 대상에게 발송하고 (성공한 chat_id 목록, (chat_id, 실패사유) 목록)을 돌려준다.

    한 대상이 실패해도 나머지는 계속 보낸다. 구독자 한 명이 봇을 차단했다고
    나머지 전원의 알림이 죽으면 안 되기 때문.
    """
    delivered: list[str] = []
    failures: list[tuple[str, str]] = []

    for cid in chat_ids:
        problem = diagnose_target(token, cid)
        if problem:
            failures.append((cid, problem))
            continue
        try:
            for i, chunk in enumerate(chunks):
                send_telegram(token, cid, (header + chunk) if i == 0 else chunk)
                time.sleep(0.3)
            delivered.append(cid)
        except RuntimeError as exc:
            failures.append((cid, str(exc)))

    return delivered, failures


def prune_roster(
    roster: dict[str, dict], failures: list[tuple[str, str]]
) -> list[str]:
    """차단·탈퇴처럼 재시도가 무의미한 대상을 명부에서 뺀다.

    이걸 안 하면 봇을 차단한 사람에게 매일 발송을 시도하면서 실패 로그가 계속
    쌓이고, 텔레그램 쪽 요청 낭비도 누적된다. 사용자가 다시 /start를 보내면
    자연히 명부에 다시 들어온다.
    """
    removed: list[str] = []
    for cid, reason in failures:
        if cid.startswith("@"):
            continue  # 채널은 명부 대상이 아니다
        if cid in roster and is_permanent_failure(reason):
            roster.pop(cid)
            removed.append(cid)
    return removed


def delivery_exit_code(
    delivered: list[str], failures: list[tuple[str, str]]
) -> int:
    """발송 결과를 GitHub Actions 종료 코드로 바꾼다.

    0을 돌려주면 Actions가 초록 체크, 0이 아니면 빨간 X + 실패 알림 메일.
    원래 코드는 전송이 다 실패해도 무조건 0을 돌려줘서, 아무한테도 안 갔는데
    성공으로 보이는 게 이번 사건의 발견이 늦어진 이유였다.
    """
    if not delivered and not failures:
        return 0  # 보낼 대상 자체가 없었던 경우는 실패가 아니다

    # 아무한테도 못 갔다 = 조용한 전면 장애. 반드시 빨간 X로 드러내야 한다.
    if not delivered:
        return 1

    # 채널을 지정해뒀다면 그게 주 발송 경로다. 채널이 죽었으면 개인 DM 몇 개가
    # 살아 있어도 실패로 본다.
    if any(cid.startswith("@") for cid, _ in failures):
        return 1

    # 개인 구독자 일부 실패는 초록으로 넘긴다. 누군가 봇을 차단하면 영구 실패가
    # 되는데, 이걸 빨간 X로 취급하면 매일 실패 메일이 오고 seen.json이 계속
    # 보류돼 같은 공모전이 매일 다시 발송된다. 사유는 로그와 명부 정리로 남는다.
    return 0


def group_by_category(notices: list[Notice]) -> dict[str, dict[str, list[Notice]]]:
    """카테고리 → 게시판 → 공지 목록으로 묶는다. 카테고리 순서는 CATEGORY_ORDER."""
    grouped: dict[str, dict[str, list[Notice]]] = {}
    for n in notices:
        grouped.setdefault(n.category, {}).setdefault(n.board, []).append(n)

    ordered: dict[str, dict[str, list[Notice]]] = {}
    for cat in CATEGORY_ORDER:
        if cat in grouped:
            ordered[cat] = grouped.pop(cat)
    ordered.update(grouped)  # CATEGORY_ORDER에 없는 카테고리는 뒤에 붙인다
    return ordered


def render_line(n: Notice) -> str:
    """공지 한 줄. 날짜(학교공지)나 주최사·마감일(공모전/채용)을 꼬리에 붙인다."""
    tail = n.date or n.extra
    suffix = f" <i>({escape_html(tail)})</i>" if tail else ""
    return f'• <a href="{escape_html(n.url)}">{escape_html(n.title)}</a>{suffix}\n'


def chunk_messages(notices: list[Notice], limit: int = 3500) -> list[str]:
    """텔레그램은 한 메시지 4096자 제한이라 안전하게 3500자로 분할한다.

    카테고리(공모전/채용 등) 제목 아래에 게시판 소제목을 두는 2단 구조라,
    분할이 일어나도 다음 메시지에 소속 게시판 소제목을 다시 찍어 맥락을 잃지 않게 한다.
    """
    chunks: list[str] = []
    current = ""

    for cat, boards in group_by_category(notices).items():
        cat_header = f"\n<b>{CATEGORY_ICON.get(cat, '•')} {escape_html(cat)}</b>\n"
        if len(current) + len(cat_header) > limit and current.strip():
            chunks.append(current.strip())
            current = ""
        current += cat_header

        for board, items in boards.items():
            board_header = f"<b>[{escape_html(board)}]</b>\n"
            if len(current) + len(board_header) > limit and current.strip():
                chunks.append(current.strip())
                current = cat_header
            current += board_header

            for n in items:
                line = render_line(n)
                if len(current) + len(line) > limit:
                    chunks.append(current.strip())
                    current = cat_header + board_header + line
                else:
                    current += line

    if current.strip():
        chunks.append(current.strip())

    return chunks


def render_email_html(notices: list[Notice]) -> tuple[str, str]:
    grouped = group_by_category(notices)
    subject = f"[CNU 알리미] {' · '.join(grouped)} {len(notices)}건"

    parts = [
        "<html><body style=\"font-family: -apple-system, sans-serif;\">",
        "<h2>CNU 공지 · 공모전 · 인턴십 · 채용 알리미</h2>",
        f"<p>총 {len(notices)}건</p>",
    ]
    for cat, boards in grouped.items():
        parts.append(f"<h2>{CATEGORY_ICON.get(cat, '')} {escape_html(cat)}</h2>")
        for board, items in boards.items():
            parts.append(f"<h3>[{escape_html(board)}]</h3><ul>")
            for n in items:
                tail = n.date or n.extra
                tail_html = (
                    f' <span style="color:#888">({escape_html(tail)})</span>'
                    if tail
                    else ""
                )
                parts.append(
                    f'<li><a href="{escape_html(n.url)}">{escape_html(n.title)}</a>{tail_html}</li>'
                )
            parts.append("</ul>")
    parts.append("</body></html>")
    return subject, "\n".join(parts)


def send_email(username: str, password: str, to_addr: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(NAVER_SMTP_HOST, NAVER_SMTP_PORT, timeout=TIMEOUT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(username, password)
        server.send_message(msg)


def build_sources() -> list[Source]:
    """수집 대상 전체. 카테고리와 필터 모드를 여기서 한 번에 정한다."""
    sources: list[Source] = []

    for board, target in BOARDS.items():
        sources.append(Source(board, CAT_SCHOOL, target, fetch_board, MODE_DATE))
    for board, target in NTT_BOARDS.items():
        sources.append(Source(board, CAT_SCHOOL, target, fetch_ntt_board, MODE_DATE))
    for board, target in PLUS_BOARDS.items():
        sources.append(Source(board, CAT_SCHOOL, target, fetch_plus_board, MODE_DATE))
    for board, target in WITH_BOARDS.items():
        sources.append(
            Source(board, CAT_SCHOOL, target, fetch_with_programs, MODE_DATE)
        )

    # 아래 소스들은 등록일을 노출하지 않으므로 '처음 보는 글'만 발송한다
    for board, cidx in WEVITY_BOARDS.items():
        sources.append(Source(board, CAT_CONTEST, cidx, fetch_wevity, MODE_NEW))
    sources.append(
        Source("DACON·AI 경진대회", CAT_CONTEST, DACON_LIST_URL, fetch_dacon, MODE_NEW)
    )
    sources.append(
        Source(
            "링커리어·인턴", CAT_INTERN, LINKAREER_LIST_URL, fetch_linkareer, MODE_NEW
        )
    )
    for board, params in JUMPIT_BOARDS.items():
        sources.append(Source(board, CAT_JOB, params, fetch_jumpit, MODE_NEW))

    return sources


def collect(sources: list[Source], seen: dict[str, list[int]]) -> list[Notice]:
    """모든 소스를 수집하고 각 모드에 맞는 필터를 적용한 결과를 합친다.

    한 소스가 실패해도 나머지는 계속 수집한다. 사이트 하나가 개편됐다고
    그날 알림 전체가 날아가면 안 되기 때문.
    """
    date_mode: list[Notice] = []
    picked: list[Notice] = []

    for src in sources:
        try:
            items = src.fetch(src.board, src.target)
        except Exception as exc:
            print(f"[{src.board}] 수집 실패: {exc}", file=sys.stderr)
            time.sleep(0.5)
            continue

        print(f"[{src.board}] 수집 {len(items)}건")
        if src.mode == MODE_NEW:
            fresh = filter_new(src.board, items, seen)
            if fresh:
                print(f"[{src.board}] 신규 {len(fresh)}건")
            picked.extend(fresh)
        else:
            date_mode.extend(items)
        time.sleep(0.5)

    recent = filter_recent(date_mode, WINDOW_DAYS)
    print(f"학교공지 최근 {WINDOW_DAYS}일 이내 {len(recent)}건")

    # 하나의 공모전이 여러 분야에 동시 등록되는 경우(위비티 게임/SW와 과학/공학에
    # 같은 ix가 함께 뜬다) 같은 글이 두 번 발송된다. 발송 직전에 걸러낸다.
    # seen 기록은 게시판별로 이미 끝났으므로 다음 실행에는 어차피 안 잡힌다.
    deduped: list[Notice] = []
    sent_keys: set[tuple[str, int]] = set()
    for n in recent + picked:
        key = (n.category, n.article_no)
        if key in sent_keys:
            print(f"[{n.board}] 중복 제외: {n.title[:40]}")
            continue
        sent_keys.add(key)
        deduped.append(n)

    return deduped


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = parse_chat_ids(os.environ.get("TELEGRAM_CHAT_ID", ""))
    channel_link = os.environ.get("TELEGRAM_CHANNEL_LINK", "").strip()
    naver_user = os.environ.get("NAVER_USERNAME", "").strip()
    naver_pass = os.environ.get("NAVER_PASSWORD", "").strip()
    email_to = os.environ.get("EMAIL_TO", "").strip() or naver_user
    dry_run = os.environ.get("DRY_RUN", "").strip() == "1"

    email_enabled = bool(naver_user and naver_pass)

    # 구독자 명부를 먼저 처리한다. /start 한 사람이 그 자리에서 발송 대상이 되도록.
    roster: dict[str, dict] = {}
    if token and not dry_run:
        roster = load_roster(token)
        before = dict(roster)
        joined, left = handle_commands(token, channel_link, roster)
        if roster != before:
            if save_roster(token, roster):
                print(
                    f"구독자 명부 갱신: 총 {len(roster)}명 "
                    f"(신규 {joined}명, 해지 {left}명)"
                )

    # 발송 대상 = 명시적으로 지정한 대상(채널/개인) + 봇에 /start 한 구독자 전원.
    # TELEGRAM_CHAT_ID를 손대지 않아도 구독자에게 알림이 가게 하는 게 핵심이다.
    for cid in roster:
        if cid not in chat_ids:
            chat_ids.append(cid)

    telegram_enabled = bool(token and chat_ids)

    if not dry_run and not telegram_enabled and not email_enabled:
        print(
            "ERROR: 발송 대상이 없습니다. TELEGRAM_CHAT_ID를 설정하거나, "
            "봇에게 /start를 보내 구독자를 만들거나, "
            "네이버 이메일(NAVER_USERNAME+NAVER_PASSWORD)을 설정하세요.",
            file=sys.stderr,
        )
        return 2

    # 인사 전용 모드. 텔레그램은 미확인 update를 24시간만 보관하므로 이 경로만
    # 짧은 주기(greet.yml)로 자주 돌린다. 공지 다이제스트는 하루 한 번 그대로.
    if os.environ.get("GREET_ONLY", "").strip() == "1":
        print("GREET_ONLY: /start·/stop 응대만 수행하고 종료")
        return 0

    seen = load_seen()
    picked = collect(build_sources(), seen)

    if dry_run:
        print(f"DRY_RUN: 전송 생략. 발송 대상 {len(picked)}건 미리보기:")
        for n in picked:
            tail = n.date or n.extra
            print(f"  [{n.category}/{n.board}] {n.title} ({tail})")
        return 0

    if not picked:
        print("발송할 항목이 없습니다.")
        save_seen(seen)  # 최초 수집 기준선은 발송이 없어도 기록해야 한다
        return 0

    exit_code = 0

    if telegram_enabled:
        chunks = chunk_messages(picked)
        header = f"<b>📢 CNU 알리미 · 새 소식 {len(picked)}건</b>\n"
        delivered, failures = broadcast(token, chat_ids, chunks, header)

        for cid, reason in failures:
            print(f"텔레그램 전송 실패 [{cid}]: {reason}", file=sys.stderr)
        if delivered:
            print(
                f"텔레그램 전송 완료: {len(delivered)}개 대상 × {len(chunks)} 메시지"
            )

        # 차단·탈퇴한 사람은 명부에서 빼서 매일 헛발송하지 않게 한다
        removed = prune_roster(roster, failures)
        if removed:
            print(f"명부에서 제외(차단/탈퇴): {len(removed)}명")
            save_roster(token, roster)

        exit_code = delivery_exit_code(delivered, failures)
    else:
        print("텔레그램 자격증명 없음 - 텔레그램 전송 스킵")

    if email_enabled:
        try:
            subject, html = render_email_html(picked)
            send_email(naver_user, naver_pass, email_to, subject, html)
            print(f"이메일 전송 완료: {email_to}")
        except Exception as exc:
            print(f"이메일 전송 실패: {exc}", file=sys.stderr)
    else:
        print("네이버 이메일 자격증명 없음 - 이메일 전송 스킵")

    # 발송에 성공했을 때만 seen을 확정한다. 전부 실패했는데 기록해버리면
    # 그 공지들은 영영 다시 발송되지 않고 조용히 사라진다.
    if exit_code == 0:
        save_seen(seen)
    else:
        print("발송 실패로 seen.json 갱신 보류 - 다음 실행에서 재시도", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

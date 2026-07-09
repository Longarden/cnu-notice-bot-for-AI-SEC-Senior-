"""
CNU 컴퓨터인공지능학부 공지 알리미.

4개 게시판(학사공지/교내일반소식/교외활동인턴/사업단소식)에서 오늘 기준 7일 이내에
올라온 모든 공지를 매일 텔레그램과 네이버 메일로 전송한다. 자격증명이 없는 채널은
자동 스킵된다.

GitHub Actions cron으로 매일 실행되도록 설계됐다.
"""

from __future__ import annotations

import os
import re
import smtplib
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

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


def send_telegram(token: str, chat_id: str, text: str) -> None:
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(api, data=payload, timeout=TIMEOUT)
    if not resp.ok:
        raise RuntimeError(
            f"Telegram API error {resp.status_code}: {resp.text}"
        )


def chunk_messages(notices: list[Notice], limit: int = 3500) -> list[str]:
    """텔레그램은 한 메시지 4096자 제한이라 안전하게 3500자로 분할한다."""
    chunks: list[str] = []
    current = ""
    by_board: dict[str, list[Notice]] = {}
    for n in notices:
        by_board.setdefault(n.board, []).append(n)

    for board, items in by_board.items():
        header = f"\n<b>[{escape_html(board)}]</b>\n"
        if len(current) + len(header) > limit and current:
            chunks.append(current.strip())
            current = ""
        current += header

        for n in items:
            date_str = f" ({escape_html(n.date)})" if n.date else ""
            line = f"• <a href=\"{escape_html(n.url)}\">{escape_html(n.title)}</a>{date_str}\n"
            if len(current) + len(line) > limit:
                chunks.append(current.strip())
                current = header + line
            else:
                current += line

    if current.strip():
        chunks.append(current.strip())

    return chunks


def render_email_html(notices: list[Notice]) -> tuple[str, str]:
    subject = f"[CNU 공지] 최근 {WINDOW_DAYS}일 공지 {len(notices)}건"

    by_board: dict[str, list[Notice]] = {}
    for n in notices:
        by_board.setdefault(n.board, []).append(n)

    parts = [
        "<html><body style=\"font-family: -apple-system, sans-serif;\">",
        f"<h2>CNU 컴퓨터인공지능학부 최근 {WINDOW_DAYS}일 공지</h2>",
        f"<p>총 {len(notices)}건</p>",
    ]
    for board, items in by_board.items():
        parts.append(f"<h3>[{escape_html(board)}]</h3><ul>")
        for n in items:
            date_str = (
                f' <span style="color:#888">({escape_html(n.date)})</span>'
                if n.date
                else ""
            )
            parts.append(
                f'<li><a href="{escape_html(n.url)}">{escape_html(n.title)}</a>{date_str}</li>'
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


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    naver_user = os.environ.get("NAVER_USERNAME", "").strip()
    naver_pass = os.environ.get("NAVER_PASSWORD", "").strip()
    email_to = os.environ.get("EMAIL_TO", "").strip() or naver_user
    dry_run = os.environ.get("DRY_RUN", "").strip() == "1"

    telegram_enabled = bool(token and chat_id)
    email_enabled = bool(naver_user and naver_pass)

    if not dry_run and not telegram_enabled and not email_enabled:
        print(
            "ERROR: 텔레그램(TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID) 또는 "
            "네이버 이메일(NAVER_USERNAME+NAVER_PASSWORD) 자격증명이 하나도 없습니다.",
            file=sys.stderr,
        )
        return 2

    sources = (
        [(b, t, fetch_board) for b, t in BOARDS.items()]
        + [(b, t, fetch_ntt_board) for b, t in NTT_BOARDS.items()]
        + [(b, t, fetch_plus_board) for b, t in PLUS_BOARDS.items()]
        + [(b, t, fetch_with_programs) for b, t in WITH_BOARDS.items()]
    )

    all_notices: list[Notice] = []
    for board, target, fetch in sources:
        try:
            items = fetch(board, target)
            print(f"[{board}] 수집 {len(items)}건")
            all_notices.extend(items)
        except Exception as exc:
            print(f"[{board}] 스크래핑 실패: {exc}", file=sys.stderr)
        time.sleep(0.5)

    recent = filter_recent(all_notices, WINDOW_DAYS)
    print(f"최근 {WINDOW_DAYS}일 이내 공지 {len(recent)}건")

    if not recent:
        print("발송할 공지가 없습니다.")
        return 0

    if dry_run:
        print("DRY_RUN: 전송 생략. 미리보기:")
        for n in recent:
            print(f"  [{n.board}] {n.title} ({n.date})")
        return 0

    if telegram_enabled:
        try:
            chunks = chunk_messages(recent)
            header = f"<b>CNU 컴퓨터인공지능학부 최근 {WINDOW_DAYS}일 공지 ({len(recent)}건)</b>\n"
            for i, chunk in enumerate(chunks):
                text = (header + chunk) if i == 0 else chunk
                send_telegram(token, chat_id, text)
                time.sleep(0.3)
            print(f"텔레그램 전송 완료: {len(chunks)} 메시지")
        except Exception as exc:
            print(f"텔레그램 전송 실패: {exc}", file=sys.stderr)
    else:
        print("텔레그램 자격증명 없음 - 텔레그램 전송 스킵")

    if email_enabled:
        try:
            subject, html = render_email_html(recent)
            send_email(naver_user, naver_pass, email_to, subject, html)
            print(f"이메일 전송 완료: {email_to}")
        except Exception as exc:
            print(f"이메일 전송 실패: {exc}", file=sys.stderr)
    else:
        print("네이버 이메일 자격증명 없음 - 이메일 전송 스킵")

    return 0


if __name__ == "__main__":
    sys.exit(main())

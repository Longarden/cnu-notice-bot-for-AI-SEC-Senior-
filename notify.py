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

    all_notices: list[Notice] = []
    for board, path in BOARDS.items():
        try:
            items = fetch_board(board, path)
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

"""
CNU 컴퓨터인공지능학부 공지 알리미.

4개 게시판(학사공지/교내일반소식/교외활동인턴/사업단소식)을 순회하며
seen.json에 저장된 마지막 articleNo 이후의 새 글을 텔레그램으로 전송한다.

GitHub Actions cron으로 매일 실행되도록 설계됐다.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
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

SEEN_PATH = Path(__file__).parent / "seen.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

TIMEOUT = 20


@dataclass
class Notice:
    board: str
    article_no: int
    title: str
    date: str
    url: str


def load_seen() -> dict[str, int]:
    if not SEEN_PATH.exists():
        return {}
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_seen(seen: dict[str, int]) -> None:
    SEEN_PATH.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


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

        date = ""
        for td in row.select("td"):
            txt = td.get_text(strip=True)
            if re.fullmatch(r"\d{4}[./-]\d{2}[./-]\d{2}", txt):
                date = txt
                break

        full_url = urljoin(url, href)
        notices.append(
            Notice(
                board=board,
                article_no=article_no,
                title=title,
                date=date,
                url=full_url,
            )
        )

    return notices


def find_new(all_notices: list[Notice], seen: dict[str, int]) -> list[Notice]:
    new: list[Notice] = []
    for n in all_notices:
        last = seen.get(n.board, 0)
        if n.article_no > last:
            new.append(n)
    new.sort(key=lambda x: (x.board, x.article_no))
    return new


def update_seen(all_notices: list[Notice], seen: dict[str, int]) -> dict[str, int]:
    updated = dict(seen)
    for n in all_notices:
        prev = updated.get(n.board, 0)
        if n.article_no > prev:
            updated[n.board] = n.article_no
    return updated


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


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    dry_run = os.environ.get("DRY_RUN", "").strip() == "1"

    if not dry_run and (not token or not chat_id):
        print(
            "ERROR: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 없습니다.",
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

    seen = load_seen()
    first_run = not seen

    if first_run:
        new = []
        print("초기 실행 - seen.json을 만들기만 하고 메시지는 보내지 않습니다.")
    else:
        new = find_new(all_notices, seen)
        print(f"새 글 {len(new)}건")

    if new and not dry_run:
        chunks = chunk_messages(new)
        header = "<b>CNU 컴퓨터인공지능학부 새 공지</b>\n"
        for i, chunk in enumerate(chunks):
            text = (header + chunk) if i == 0 else chunk
            send_telegram(token, chat_id, text)
            time.sleep(0.3)
        print(f"텔레그램 전송 완료: {len(chunks)} 메시지")
    elif new and dry_run:
        print("DRY_RUN: 텔레그램 전송 생략. 미리보기:")
        for n in new:
            print(f"  [{n.board}] #{n.article_no} {n.title} ({n.date})")

    updated = update_seen(all_notices, seen)
    save_seen(updated)
    print(f"seen.json 갱신: {updated}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

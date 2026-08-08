"""구독자 명부 열람 도구 (소유자 전용).

subscribers.enc는 공개 저장소에 커밋되지만 봇 토큰에서 파생한 키로 암호화돼
있어서, 토큰을 가진 사람만 내용을 볼 수 있다. 이 스크립트는 그 복호화를 로컬에서
수행한다. 복호화 결과는 화면에만 출력하고 절대 파일로 남기지 않는다.

사용법 (PowerShell):
    $env:TELEGRAM_BOT_TOKEN="123456:ABC..."
    py roster.py

채널 구독자 수까지 같이 보려면:
    $env:TELEGRAM_CHAT_ID="@cnu_alarm"
    py roster.py
"""

from __future__ import annotations

import os
import sys

import requests

from notify import ROSTER_PATH, load_roster, parse_chat_ids


def channel_member_count(token: str, chat_id: str) -> str:
    """채널 구독자 수를 조회한다.

    텔레그램 봇 API는 채널 '구독자 명단'을 제공하지 않는다(설계상 비공개).
    그래서 채널은 인원수만 알 수 있고, 개별 명부는 봇에게 /start를 보낸
    사람에 한해서만 만들어진다. 이 차이를 출력에서 분명히 구분한다.
    """
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getChatMemberCount",
            params={"chat_id": chat_id},
            timeout=20,
        )
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return f"조회 실패({exc})"
    if not body.get("ok"):
        return f"조회 실패({body.get('description')})"
    return f"{body.get('result')}명"


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print(
            "TELEGRAM_BOT_TOKEN 환경변수가 필요합니다. "
            "(명부는 이 토큰에서 파생한 키로만 열립니다)",
            file=sys.stderr,
        )
        return 2

    if not ROSTER_PATH.exists():
        print(f"명부 파일이 없습니다: {ROSTER_PATH}")
        print("아직 아무도 봇에게 /start를 보내지 않았거나, 최신 커밋을 pull 하지 않았습니다.")
        return 0

    roster = load_roster(token)
    if not roster:
        print("명부가 비어 있거나 복호화에 실패했습니다. (위 오류 메시지 확인)")
        return 1

    print(f"봇 /start 구독자 {len(roster)}명")
    print("─" * 72)
    print(f"{'chat_id':>14}  {'이름':<16} {'username':<18} {'최초':<11} {'최근'}")
    print("─" * 72)

    for chat_id, info in sorted(
        roster.items(), key=lambda kv: kv[1].get("first_seen", "")
    ):
        name = (info.get("name") or "-")[:16]
        username = ("@" + info["username"]) if info.get("username") else "-"
        print(
            f"{chat_id:>14}  {name:<16} {username:<18} "
            f"{(info.get('first_seen') or '-')[:10]:<11} {info.get('last_start') or '-'}"
        )

    channels = [c for c in parse_chat_ids(os.environ.get("TELEGRAM_CHAT_ID", "")) if c.startswith("@")]
    if channels:
        print("─" * 72)
        for channel in channels:
            print(f"채널 {channel} 구독자: {channel_member_count(token, channel)}")
        print("(텔레그램은 채널 구독자 '명단'을 봇에게 제공하지 않습니다. 인원수만 조회 가능)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

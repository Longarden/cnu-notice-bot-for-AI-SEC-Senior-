import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import requests

import notion_sync
from notion_sync import dedupe_key, notice_date, sync_to_notion

TODAY = date(2026, 11, 8)
ICONS = {"학교공지": "🏫", "공모전": "🏆", "인턴십": "🧑‍💻", "채용": "💼"}
TOKEN = "secret_TOKEN_SHOULD_NOT_LEAK"
DB = "db123"


@dataclass
class N:
    board: str
    article_no: int
    title: str
    date: str
    url: str
    category: str = "학교공지"
    extra: str = ""


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y.%m.%d").date() if s else None
    except ValueError:
        return None


class Resp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data or {}
        self.headers = headers or {}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._data


def query_resp(keys=(), has_more=False, cursor=None):
    results = [
        {"properties": {"메모": {"rich_text": [{"plain_text": k}]}}} for k in keys
    ]
    return Resp(200, {"results": results, "has_more": has_more, "next_cursor": cursor})


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def creates(session):
    return [c for c in session.calls if c["url"].endswith("/pages")]


def run(notices, responses):
    session = FakeSession(responses)
    with mock.patch.object(notion_sync.time, "sleep"):
        result = sync_to_notion(
            notices, TOKEN, DB, ICONS, parse_date, session=session, today=TODAY
        )
    return result, session


class NoticeDateTest(unittest.TestCase):
    def d(self, extra="", posted=""):
        return notice_date(N("b", 1, "t", posted, "u", extra=extra), TODAY, parse_date)

    def test_deadline(self):
        self.assertEqual(self.d("카카오 · ~2026.11.30"), date(2026, 11, 30))

    def test_dday(self):
        self.assertEqual(self.d("한국정보화진흥원 · D-12"), date(2026, 11, 20))

    def test_dday_followed_by_korean(self):
        self.assertEqual(self.d("주최 · D-3접수중"), date(2026, 11, 11))

    def test_dday_zero_and_today(self):
        self.assertEqual(self.d("주최 · D-0"), TODAY)
        self.assertEqual(self.d("주최 · D-DAY"), TODAY)
        self.assertEqual(self.d("주최 · 오늘마감"), TODAY)

    def test_organizer_with_letters_before_d_is_not_dday(self):
        self.assertEqual(self.d("ABD-5 컴퍼니", posted="2026.11.01"), date(2026, 11, 1))

    def test_posting_date(self):
        self.assertEqual(self.d(posted="2026.11.05"), date(2026, 11, 5))

    def test_fallback_to_today(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.d("점핏 · 상시채용"), TODAY)
            self.assertEqual(self.d("DACON"), TODAY)
        self.assertEqual(self.d(), TODAY)


class DedupeKeyTest(unittest.TestCase):
    def test_url_with_id(self):
        n = N("b", 123, "t", "", "https://x/view.do?articleNo=123")
        self.assertEqual(dedupe_key(n), "https://x/view.do?articleNo=123")

    def test_shared_url_gets_fragment(self):
        a = N("비교과", 11, "a", "", "https://with.cnu.ac.kr/")
        b = N("비교과", 22, "b", "", "https://with.cnu.ac.kr/")
        self.assertNotEqual(dedupe_key(a), dedupe_key(b))
        self.assertEqual(dedupe_key(a), "https://with.cnu.ac.kr/#11")


class SyncTest(unittest.TestCase):
    def test_creates_pages_with_title_date_category_memo(self):
        n = N("링커리어", 77, "삼성 인턴", "", "https://linkareer.com/activity/77",
              category="인턴십", extra="삼성 · ~2026.12.01")
        result, s = run([n], [query_resp(), Resp(200)])
        self.assertEqual(result, {"created": 1, "skipped": 0, "failed": 0, "aborted": None})
        props = creates(s)[0]["json"]["properties"]
        self.assertEqual(props["이름"]["title"][0]["text"]["content"], "🧑‍💻 삼성 인턴")
        self.assertEqual(props["날짜"]["date"]["start"], "2026-12-01")
        self.assertEqual(props["분류"]["select"]["name"], "인턴십")
        self.assertEqual(props["메모"]["rich_text"][0]["text"]["content"],
                         "https://linkareer.com/activity/77")
        self.assertEqual(creates(s)[0]["json"]["parent"]["database_id"], DB)

    def test_two_with_programs_both_created(self):
        a = N("비교과", 11, "a", "2026.11.01", "https://with.cnu.ac.kr/")
        b = N("비교과", 22, "b", "2026.11.02", "https://with.cnu.ac.kr/")
        result, s = run([a, b], [query_resp(), Resp(200), Resp(200)])
        self.assertEqual(result["created"], 2)
        self.assertEqual(len(creates(s)), 2)

    def test_rerun_creates_nothing(self):
        a = N("학사공지", 5, "a", "2026.11.03", "https://c/x?articleNo=5")
        b = N("비교과", 22, "b", "2026.11.02", "https://with.cnu.ac.kr/")
        existing = [dedupe_key(a), dedupe_key(b)]
        result, s = run([a, b], [query_resp(existing)])
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(creates(s), [])

    def test_same_notice_twice_in_one_run_created_once(self):
        a = N("학사공지", 5, "a", "2026.11.03", "https://c/x?articleNo=5")
        result, s = run([a, a], [query_resp(), Resp(200)])
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 1)

    def test_query_is_paginated_and_bounded(self):
        a = N("학사공지", 5, "a", "2026.11.03", "https://c/x?articleNo=5")
        result, s = run([a], [
            query_resp(["k1"], has_more=True, cursor="c2"),
            query_resp([dedupe_key(a)]),
        ])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(s.calls[1]["json"]["start_cursor"], "c2")
        filt = s.calls[0]["json"]["filter"]["and"]
        names = {f["select"]["equals"] for f in filt[0]["or"]}
        self.assertEqual(names, {"학교공지", "공모전", "인턴십", "채용"})
        self.assertEqual(filt[1]["created_time"]["on_or_after"], "2026-09-09")

    def test_query_failure_aborts_without_creating(self):
        a = N("학사공지", 5, "a", "2026.11.03", "https://c/x?articleNo=5")
        for bad in (Resp(400), Resp(500), requests.ConnectionError("down")):
            result, s = run([a], [bad])
            self.assertIsNotNone(result["aborted"])
            self.assertEqual(result["created"], 0)
            self.assertEqual(creates(s), [])

    def test_auth_error_stops_after_first_create(self):
        notices = [N("학사공지", i, f"t{i}", "2026.11.03", f"https://c/x?articleNo={i}")
                   for i in range(1, 6)]
        for status in (401, 403, 404, 503):
            result, s = run(notices, [query_resp(), Resp(status)])
            self.assertEqual(len(creates(s)), 1, status)
            self.assertEqual(result["aborted"], f"HTTP {status}")

    def test_connection_error_on_create_stops(self):
        notices = [N("학사공지", i, f"t{i}", "2026.11.03", f"https://c/x?articleNo={i}")
                   for i in range(1, 4)]
        result, s = run(notices, [query_resp(), requests.Timeout("slow")])
        self.assertEqual(len(creates(s)), 1)
        self.assertIn("연결 오류", result["aborted"])

    def test_single_validation_error_does_not_stop(self):
        notices = [N("학사공지", i, f"t{i}", "2026.11.03", f"https://c/x?articleNo={i}")
                   for i in range(1, 3)]
        with redirect_stderr(io.StringIO()):
            result, s = run(notices, [query_resp(), Resp(400), Resp(200)])
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["created"], 1)
        self.assertIsNone(result["aborted"])

    def test_429_retried_once(self):
        a = N("학사공지", 5, "a", "2026.11.03", "https://c/x?articleNo=5")
        result, s = run([a], [query_resp(), Resp(429, headers={"Retry-After": "1"}), Resp(200)])
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(creates(s)), 2)

    def test_time_budget_stops_new_requests(self):
        a = N("학사공지", 5, "a", "2026.11.03", "https://c/x?articleNo=5")
        session = FakeSession([query_resp(), Resp(200)])
        clock = iter([0.0, 1.0, 1000.0])
        with mock.patch.object(notion_sync.time, "sleep"), \
             mock.patch.object(notion_sync.time, "monotonic", lambda: next(clock)):
            result = sync_to_notion([a], TOKEN, DB, ICONS, parse_date,
                                    session=session, today=TODAY)
        self.assertEqual(result["aborted"], "시간 예산 초과")
        self.assertEqual(creates(session), [])

    def test_never_raises_and_never_prints_token(self):
        out, err = io.StringIO(), io.StringIO()
        broken = object()  # has no attributes -> unexpected error inside
        with redirect_stdout(out), redirect_stderr(err):
            result, _ = run([broken], [query_resp()])
        self.assertEqual(result["aborted"], "AttributeError")
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue() + str(result))

    def test_leaf_module_does_not_import_notify(self):
        src = Path(notion_sync.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(src, r"(?m)^\s*(from\s+notify\b|import\s+notify\b)")


if __name__ == "__main__":
    unittest.main()

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import notify
import notion_sync

NOTICE = notify.Notice(
    board="학사공지",
    article_no=1,
    title="수강신청 안내",
    date="2026.11.05",
    url="https://computer.cnu.ac.kr/x?articleNo=1",
)

BASE_ENV = {
    "TELEGRAM_BOT_TOKEN": "bot-token",
    "TELEGRAM_CHAT_ID": "@cnu_alarm",
    "NOTION_TOKEN": "notion-token",
    "NOTION_DATABASE_ID": "db123",
}


class MainNotionHookTest(unittest.TestCase):
    def run_main(self, env, broadcast_result=(["@cnu_alarm"], []), sync=None):
        order = []
        save_seen = mock.Mock(side_effect=lambda seen: order.append("save_seen"))
        sync = sync or mock.Mock(return_value={"created": 1})

        def record_sync(*args, **kwargs):
            order.append("sync")
            return sync(*args, **kwargs)

        wrapped = mock.Mock(side_effect=record_sync)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(notify, "load_roster", return_value={}), \
             mock.patch.object(notify, "handle_commands", return_value=(0, 0)), \
             mock.patch.object(notify, "load_seen", return_value={}), \
             mock.patch.object(notify, "build_sources", return_value=[]), \
             mock.patch.object(notify, "collect", return_value=[NOTICE]), \
             mock.patch.object(notify, "broadcast", return_value=broadcast_result), \
             mock.patch.object(notify, "save_seen", save_seen), \
             mock.patch.object(notion_sync, "sync_to_notion", wrapped), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = notify.main()
        return code, order, wrapped, save_seen

    def test_sync_runs_after_seen_is_saved(self):
        code, order, wrapped, _ = self.run_main(BASE_ENV)
        self.assertEqual(code, 0)
        self.assertEqual(order, ["save_seen", "sync"])
        args = wrapped.call_args.args
        self.assertEqual(args[0], [NOTICE])
        self.assertEqual(args[1:3], ("notion-token", "db123"))
        self.assertIs(args[3], notify.CATEGORY_ICON)
        self.assertIs(args[4], notify.parse_date)

    def test_sync_exception_does_not_change_exit_code_or_seen(self):
        boom = mock.Mock(side_effect=RuntimeError("notion down"))
        code, order, _, save_seen = self.run_main(BASE_ENV, sync=boom)
        self.assertEqual(code, 0)
        save_seen.assert_called_once()

    def test_import_error_does_not_change_exit_code(self):
        # sys.modules에 None을 넣으면 main() 안의 지연 import가 ImportError를 낸다
        with mock.patch.dict("sys.modules", {"notion_sync": None}):
            code, order, wrapped, save_seen = self.run_main(BASE_ENV)
        self.assertEqual(code, 0)
        save_seen.assert_called_once()
        wrapped.assert_not_called()

    def test_no_sync_when_delivery_failed(self):
        code, order, wrapped, _ = self.run_main(
            BASE_ENV, broadcast_result=([], [("@cnu_alarm", "forbidden")])
        )
        self.assertEqual(code, 1)
        wrapped.assert_not_called()

    def test_no_sync_without_notion_settings(self):
        env = {k: v for k, v in BASE_ENV.items() if not k.startswith("NOTION")}
        code, order, wrapped, _ = self.run_main(env)
        self.assertEqual(code, 0)
        wrapped.assert_not_called()

    def test_dry_run_makes_no_notion_calls(self):
        env = dict(BASE_ENV, DRY_RUN="1")
        with mock.patch("requests.Session.post") as session_post, \
             mock.patch("requests.post") as plain_post:
            code, order, wrapped, _ = self.run_main(env)
        self.assertEqual(code, 0)
        wrapped.assert_not_called()
        session_post.assert_not_called()
        plain_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()

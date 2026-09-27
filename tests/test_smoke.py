"""冒烟测试：不联网、不需要真实凭证，纯标准库 unittest。

跑法：

    python3 -m unittest discover -s tests -v

覆盖的是那些"改坏了很晚才会发现"的地方：

  * 应用能正常导入、数据库能初始化
  * 没有凭证时 / 和 /authorize 的行为（首启体验）
  * /healthz 自检端点
  * OAuth 回调服务的三条路径：成功、state 不符、超时后释放端口
  * scripts/setup.py 的凭证校验逻辑（桌面应用 / Web 应用 / 坏 JSON）
"""

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── 关键：先隔离状态文件，再导入 app ──
# app.py 在导入时就会读这些环境变量并初始化数据库，
# 指到临时目录才能保证测试绝不碰仓库里的真实数据 / 凭证。
_TMP = tempfile.mkdtemp(prefix="ytsm-test-")
os.environ["CONFIG_DIR"] = os.path.join(_TMP, "config")
os.environ["OUTPUT_DIR"] = os.path.join(_TMP, "output")
os.environ["DB_PATH"] = os.path.join(_TMP, "data.db")
os.environ["THUMB_DIR"] = os.path.join(_TMP, "thumbs")
os.environ["OAUTH_PORT"] = "0"          # 让回调服务绑随机端口
os.environ["OAUTH_TIMEOUT_SECONDS"] = "600"
os.environ.pop("ACCESS_PASSWORD", None)  # 免得本机导出的口令把测试变成 401

import app  # noqa: E402  必须在设置好环境变量之后导入


class AppBootTests(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()

    def test_healthz_ok(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        # authorized 必须是布尔值（具体真假取决于是否已有 token，
        # 不要写死，否则测试结果会依赖执行顺序）
        self.assertIsInstance(data["authorized"], bool)
        self.assertIn("features", data)

    def test_index_redirects_to_authorize_when_no_credentials(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/authorize", resp.headers["Location"])

    def test_authorize_without_client_secrets_shows_helpful_error(self):
        """首次运行（还没放凭证）必须是给人看的提示页，而不是 500。"""
        resp = self.client.get("/authorize")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("client_secrets.json", body)
        self.assertIn("桌面应用", body)

    def test_authorize_status_shape(self):
        resp = self.client.get("/authorize/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        for key in ("done", "pending", "error"):
            self.assertIn(key, data)

    def test_favicon_no_content(self):
        self.assertEqual(self.client.get("/favicon.ico").status_code, 204)


class SaveTokenTests(unittest.TestCase):
    def test_atomic_write(self):
        class FakeCreds:
            def to_json(self):
                return json.dumps({"token": "T", "refresh_token": "R"})

        app._save_token(FakeCreds())
        with open(app.TOKEN_PATH, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["refresh_token"], "R")
        # 不应该留下临时文件
        self.assertFalse(os.path.exists(app.TOKEN_PATH + ".tmp"))


class OAuthCallbackTests(unittest.TestCase):
    """回调服务的核心行为。用假的 flow 对象，不联网。"""

    class _FakeFlow:
        def __init__(self):
            self.seen_code = None
            self.credentials = None

        def fetch_token(self, code=None):
            self.seen_code = code
            self.credentials = _Creds()

    def _start(self, flow, state):
        import http.server
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                app._OAuthCallbackHandler)
        httpd.timeout = 1
        httpd.oauth_event = threading.Event()
        httpd.oauth_finished = threading.Event()
        httpd.oauth_result = None
        httpd.oauth_error = None
        thread = threading.Thread(target=app._oauth_worker,
                                  args=(flow, httpd, state), daemon=True)
        thread.start()
        return httpd, thread

    def _get(self, port, query):
        url = f"http://127.0.0.1:{port}/?{query}"
        return urllib.request.urlopen(url, timeout=15).read().decode("utf-8")

    def test_success_writes_token_and_releases_port(self):
        flow = self._FakeFlow()
        httpd, thread = self._start(flow, "GOOD")
        port = httpd.server_port

        page = self._get(port, "code=ABC&state=GOOD")
        thread.join(15)

        self.assertIn("授权成功", page)
        self.assertEqual(flow.seen_code, "ABC")
        self.assertIsNone(httpd.oauth_error)
        self.assertTrue(os.path.exists(app.TOKEN_PATH))
        # 端口必须已经释放（这是之前 [Errno 98] 的根因）
        self._assert_port_free(port)

    def test_state_mismatch_is_rejected_and_port_released(self):
        flow = self._FakeFlow()
        httpd, thread = self._start(flow, "EXPECTED")
        port = httpd.server_port

        self._get(port, "code=ABC&state=WRONG")
        thread.join(15)

        self.assertIsNone(flow.seen_code)          # 不该拿错误的 state 去换 token
        self.assertIn("state", httpd.oauth_error or "")
        self._assert_port_free(port)

    def test_denied_authorization_is_reported(self):
        flow = self._FakeFlow()
        httpd, thread = self._start(flow, "S")
        port = httpd.server_port

        self._get(port, "error=access_denied")
        thread.join(15)

        self.assertIn("access_denied", httpd.oauth_error or "")
        self._assert_port_free(port)

    def test_timeout_releases_port(self):
        """没人来授权时必须自己超时释放端口，而不是永久占住。"""
        original = app.OAUTH_TIMEOUT_SECONDS
        app.OAUTH_TIMEOUT_SECONDS = 1
        try:
            flow = self._FakeFlow()
            httpd, thread = self._start(flow, "S")
            port = httpd.server_port
            thread.join(15)
            self.assertFalse(thread.is_alive())
            self.assertIn("超时", httpd.oauth_error or "")
            self._assert_port_free(port)
        finally:
            app.OAUTH_TIMEOUT_SECONDS = original

    def _assert_port_free(self, port):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError as e:               # pragma: no cover
                self.fail(f"端口 {port} 没有被释放: {e}")


class _Creds:
    """假的 Credentials，只需要能 to_json()。"""

    def to_json(self):
        return json.dumps({"token": "ACCESS", "refresh_token": "REFRESH"})


class SetupWizardTests(unittest.TestCase):
    """scripts/setup.py 的凭证校验：这几种情况必须被正确区分。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ytsm_setup", os.path.join(ROOT, "scripts", "setup.py"))
        cls.setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.setup)

    def _write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if isinstance(obj, str):
                f.write(obj)
            else:
                json.dump(obj, f)
        self.addCleanup(os.remove, path)
        return path

    def test_accepts_desktop_client(self):
        path = self._write({"installed": {"client_id": "a", "client_secret": "b"}})
        data, err = self.setup.load_and_validate(path)
        self.assertIsNone(err)
        self.assertIn("installed", data)

    def test_rejects_web_client_with_actionable_message(self):
        path = self._write({"web": {"client_id": "a", "client_secret": "b"}})
        _, err = self.setup.load_and_validate(path)
        self.assertIsNotNone(err)
        self.assertIn("桌面应用", err)

    def test_rejects_malformed_json(self):
        path = self._write('{"installed": {')
        _, err = self.setup.load_and_validate(path)
        self.assertIsNotNone(err)
        self.assertIn("JSON", err)

    def test_rejects_missing_fields(self):
        path = self._write({"installed": {"client_id": "a"}})
        _, err = self.setup.load_and_validate(path)
        self.assertIsNotNone(err)
        self.assertIn("client_secret", err)

    def test_rejects_unknown_shape(self):
        path = self._write({"something_else": 1})
        _, err = self.setup.load_and_validate(path)
        self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main(verbosity=2)

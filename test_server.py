import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import server


class ServerSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.temp_dir.name) / "kaizen.db"
        server.init_db()
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.KaizenHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join()
        cls.temp_dir.cleanup()

    def client(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, client, path, method="GET", body=None, csrf=None):
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            response = client.open(request)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
        return response.status, json.load(response)

    def test_accounts_are_isolated_and_queries_are_parameterized(self):
        first = self.client()
        status, account = self.request(first, "/api/register", "POST", {
            "email": "o'reilly@example.com",
            "password": "correct-horse",
        })
        self.assertEqual(status, 200)

        data = {
            "habits": [{"id": "habit-1", "name": "Read ' safely", "createdAt": "2026-09-23"}],
            "days": {"2026-09-23": {"completed": ["habit-1"], "reflection": "It's working", "total": 1}},
            "settings": {"theme": "light"},
        }
        status, _ = self.request(first, "/api/data", "PUT", {"data": data})
        self.assertEqual(status, 403, "writes without CSRF must fail")
        status, _ = self.request(first, "/api/data", "PUT", {"data": data}, account["csrfToken"])
        self.assertEqual(status, 200)

        second = self.client()
        status, second_account = self.request(second, "/api/register", "POST", {
            "email": "second@example.com",
            "password": "another-password",
        })
        self.assertEqual(status, 200)
        status, result = self.request(second, "/api/data")
        self.assertEqual(result["data"], server.empty_data())

        status, result = self.request(first, "/api/data")
        self.assertEqual(result["data"], data)
        with server.connect() as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)

        status, _ = self.request(first, "/server.py")
        self.assertEqual(status, 404, "server source must not be public")


if __name__ == "__main__":
    unittest.main()

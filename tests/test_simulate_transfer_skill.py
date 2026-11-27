"""Automated evals for the simulate-transfer skill (SK-6, SK-8, TQ-7).

The real FastAPI routes are the API owner's work. Until they land, this
runs the skill's script against a small stand-in HTTP server that calls
LedgerService exactly as the API layer is meant to (docs/design/ledger-core.md).
It tests the skill, not the API.
"""

import importlib.util
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.db.connection import connect, init_db
from app.errors import LedgerError
from app.ledger.hashing import request_fingerprint
from app.ledger.reconciliation import reconcile
from app.ledger.service import IdempotencyRequest, LedgerService

ADMIN_KEY = "test-admin-key-0123456789abcdef0123456789"
SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "simulate-transfer" / "scripts" / "simulate_transfer.py"


def load_script():
    spec = importlib.util.spec_from_file_location("simulate_transfer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_handler(db_path, broken_race=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep test output quiet
            pass

        def _send(self, status, body, replayed=False):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if replayed:
                self.send_header("Idempotent-Replayed", "true")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            conn = connect(db_path)
            svc = LedgerService(conn)
            try:
                idem = IdempotencyRequest(self.headers.get("Idempotency-Key"),
                                          request_fingerprint(method, self.path, body))
                p = self.path
                if method == "POST" and p == "/accounts":
                    return self._send(201, svc.create_account(body.get("name")))
                if m := re.fullmatch(r"/accounts/([^/]+)/wallets", p):
                    return self._send(201, svc.create_wallet(m[1], body.get("currency")))
                if m := re.fullmatch(r"/wallets/([^/]+)/deposits", p):
                    out = svc.deposit(m[1], body.get("amount_minor"), idem)
                    return self._send(out.status, out.body, out.replayed)
                if m := re.fullmatch(r"/wallets/([^/]+)", p):
                    return self._send(200, svc.get_wallet(m[1]))
                if p == "/transfers":
                    if broken_race and body.get("amount_minor") == 30000:
                        return self._send(201, {"broken": True})  # pretends both race transfers worked
                    out = svc.transfer(body.get("source_wallet_id"), body.get("destination_wallet_id"),
                                       body.get("amount_minor"), idem)
                    return self._send(out.status, out.body, out.replayed)
                if p == "/admin/reconciliation":
                    if self.headers.get("X-Admin-Key") != ADMIN_KEY:
                        return self._send(401, LedgerError("UNAUTHORIZED", "bad key").body())
                    return self._send(200, reconcile(conn))
                return self._send(404, {"error": {"code": "NOT_FOUND", "message": p}})
            except LedgerError as err:
                return self._send(err.status, err.body())
            finally:
                conn.close()

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    return Handler


@pytest.fixture
def server(tmp_path, request):
    db = tmp_path / "api.db"
    init_db(db).close()
    broken = getattr(request, "param", False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db, broken_race=broken))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def run_skill(module, base_url, key, monkeypatch, capsys):
    if key is None:
        monkeypatch.delenv("LEDGER_ADMIN_KEY", raising=False)
    else:
        monkeypatch.setenv("LEDGER_ADMIN_KEY", key)
    code = module.main(["--base-url", base_url])
    out = capsys.readouterr().out
    return code, json.loads(out), out


def test_case1_healthy_ledger_passes(server, monkeypatch, capsys):
    code, report, out = run_skill(load_script(), server, ADMIN_KEY, monkeypatch, capsys)
    assert code == 0 and report["result"] == "PASS", report
    assert report["final_balances_minor"] == {"sender": 10000, "receiver": 40000}
    assert ADMIN_KEY not in out


@pytest.mark.parametrize("server", [True], indirect=True)
def test_case2_broken_race_safety_fails(server, monkeypatch, capsys):
    code, report, _ = run_skill(load_script(), server, ADMIN_KEY, monkeypatch, capsys)
    assert code == 1 and "race: exactly one of two succeeds" in report["problems"]


def test_case3_wrong_admin_key_fails_without_leaking(server, monkeypatch, capsys):
    wrong = "wrong-key-should-never-be-printed-1234567890"
    code, report, out = run_skill(load_script(), server, wrong, monkeypatch, capsys)
    assert code == 1 and "reconciliation passes" in report["problems"]
    assert wrong not in out


def test_case4_no_server_fails(monkeypatch, capsys):
    code, report, _ = run_skill(load_script(), "http://127.0.0.1:9", ADMIN_KEY, monkeypatch, capsys)
    assert code == 1 and report["result"] == "FAIL"


def test_missing_admin_key_fails(server, monkeypatch, capsys):
    code, report, _ = run_skill(load_script(), server, None, monkeypatch, capsys)
    assert code == 1 and "LEDGER_ADMIN_KEY is not set" in report["problems"]

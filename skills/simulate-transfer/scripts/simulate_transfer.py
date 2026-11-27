#!/usr/bin/env python3
"""simulate-transfer: drive the running Ledger API through the SK-6 workflow.

Usage
    LEDGER_ADMIN_KEY=<key> python skills/simulate-transfer/scripts/simulate_transfer.py \
        [--base-url http://127.0.0.1:8000]

Steps (SRS v1.1 SK-6)
    1. Create two accounts with INR wallets and fund the first with ₹500.00.
    2. Record both balances.
    3. Transfer ₹100.00 with an Idempotency-Key, then retry with the same key.
    4. Race two transfers of ₹300.00 that together exceed the ₹400.00 left.
    5. Reconcile and summarise the final balances.

Fails (exit code 1) when reconciliation is FAIL, both racing transfers
succeed, or any balance differs from what is expected. Uses only the
Python standard library. Never prints LEDGER_ADMIN_KEY (C-6).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import uuid

DEPOSIT = 50000
TRANSFER = 10000
RACE = 30000


class Api:
    def __init__(self, base_url: str, admin_key: str | None):
        self.base = base_url.rstrip("/")
        self._admin_key = admin_key

    def call(self, method: str, path: str, body: dict | None = None, *, key: str | None = None,
             admin: bool = False) -> tuple[int, dict, dict]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        if admin:
            headers["X-Admin-Key"] = self._admin_key or ""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read() or b"{}"), dict(resp.headers)
        except urllib.error.HTTPError as err:
            raw = err.read() or b"{}"
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"raw": raw.decode("utf-8", "replace")[:200]}
            return err.code, payload, dict(err.headers)


def new_key(label: str) -> str:
    return f"sim-{label}-{uuid.uuid4().hex[:16]}"


def run(api: Api) -> dict:
    steps, problems = [], []

    def step(name: str, ok: bool, detail: dict):
        steps.append({"step": name, "ok": ok, **detail})
        if not ok:
            problems.append(name)
        return ok

    def balance(wallet_id: str) -> int | None:
        status, body, _ = api.call("GET", f"/wallets/{wallet_id}")
        return body.get("balance_minor") if status == 200 else None

    # 1. two wallets, fund the first
    wallets = []
    for name in ("Sim Sender", "Sim Receiver"):
        s1, acc, _ = api.call("POST", "/accounts", {"name": name})
        s2, wal, _ = api.call("POST", f"/accounts/{acc.get('id')}/wallets", {"currency": "INR"}) if s1 == 201 else (s1, {}, {})
        if not step(f"create wallet for {name}", s1 == 201 and s2 == 201, {"status": [s1, s2]}):
            return {"result": "FAIL", "steps": steps, "problems": problems}
        wallets.append(wal["id"])
    a, b = wallets
    s, dep, _ = api.call("POST", f"/wallets/{a}/deposits", {"amount_minor": DEPOSIT}, key=new_key("deposit"))
    step("fund sender with 50000", s == 201, {"status": s})

    # 2. record balances
    start = {"sender": balance(a), "receiver": balance(b)}
    step("record balances", start == {"sender": DEPOSIT, "receiver": 0}, {"balances": start})

    # 3. transfer, then retry with the same key
    body = {"source_wallet_id": a, "destination_wallet_id": b, "amount_minor": TRANSFER}
    k = new_key("transfer")
    s1, first, _ = api.call("POST", "/transfers", body, key=k)
    s2, again, headers = api.call("POST", "/transfers", body, key=k)
    replayed = str(headers.get("Idempotent-Replayed", headers.get("idempotent-replayed", ""))).lower() == "true"
    after = {"sender": balance(a), "receiver": balance(b)}
    step("transfer 10000 once", s1 == 201, {"status": s1})
    step("retry with same key is a replay",
         s2 == s1 and again == first and replayed and after == {"sender": DEPOSIT - TRANSFER, "receiver": TRANSFER},
         {"status": s2, "replayed_header": replayed, "balances": after})

    # 4. race two transfers that together exceed the balance
    race_body = {"source_wallet_id": a, "destination_wallet_id": b, "amount_minor": RACE}
    results: list = [None, None]
    barrier = threading.Barrier(2)

    def racer(i: int):
        barrier.wait()
        results[i] = api.call("POST", "/transfers", race_body, key=new_key(f"race{i}"))[:2]

    threads = [threading.Thread(target=racer, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    statuses = sorted(r[0] for r in results if r)
    codes = [r[1].get("error", {}).get("code") for r in results if r and r[0] != 201]
    race_balances = {"sender": balance(a), "receiver": balance(b)}
    expected_race = {"sender": DEPOSIT - TRANSFER - RACE, "receiver": TRANSFER + RACE}
    step("race: exactly one of two succeeds",
         statuses == [201, 422] and codes == ["INSUFFICIENT_FUNDS"] and race_balances == expected_race,
         {"statuses": statuses, "rejection_codes": codes, "balances": race_balances})

    # 5. reconcile
    s, report, _ = api.call("GET", "/admin/reconciliation", admin=True)
    status = report.get("status") if s == 200 else f"HTTP {s}"
    step("reconciliation passes", s == 200 and status == "PASS",
         {"status": status, "failed_checks": [n for n, c in report.get("checks", {}).items() if not c.get("passed")]})

    return {
        "result": "PASS" if not problems else "FAIL",
        "steps": steps,
        "problems": problems,
        "final_balances_minor": {"sender": race_balances["sender"], "receiver": race_balances["receiver"]},
        "wallets": {"sender": a, "receiver": b},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SK-6 simulate-transfer workflow.")
    parser.add_argument("--base-url", default=os.environ.get("LEDGER_BASE_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args(argv)
    admin_key = os.environ.get("LEDGER_ADMIN_KEY")
    if not admin_key:
        print(json.dumps({"result": "FAIL", "problems": ["LEDGER_ADMIN_KEY is not set"]}))
        return 1
    try:
        report = run(Api(args.base_url, admin_key))
    except urllib.error.URLError as err:
        report = {"result": "FAIL", "problems": [f"cannot reach {args.base_url}: {err.reason}"]}
    text = json.dumps(report, indent=2)
    print(text.replace(admin_key, "[redacted]"))  # belt and braces: the key is never printed
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

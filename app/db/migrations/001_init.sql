-- 001_init.sql: initial ledger schema (SRS v1.1, DB-1 to DB-4)
-- Seven tables (Figure 2): accounts, wallets, admin_keys, fx_rates,
-- transactions, ledger_entries, idempotency_keys.
-- Money is always INTEGER minor units (C-3, NFR-8, DB-2).
-- Timestamps are UTC ISO 8601 text; entity IDs are UUID v4 text (DB-4).

-- ---------------------------------------------------------------
-- accounts: one per user (FR-1.1). Never deleted (BR-7).
-- ---------------------------------------------------------------
CREATE TABLE accounts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------
-- wallets: one per account per currency (FR-1.2), plus one SYSTEM and
-- one FX_CLEARING wallet per currency with no account (FR-1.3).
-- balance_minor is a cached value; FR-5.2(c) checks it against entries.
-- ---------------------------------------------------------------
CREATE TABLE wallets (
    id             TEXT PRIMARY KEY,
    account_id     TEXT REFERENCES accounts(id),
    currency       TEXT NOT NULL CHECK (currency IN ('INR', 'USD', 'EUR')),          -- BR-3
    kind           TEXT NOT NULL CHECK (kind IN ('USER', 'SYSTEM', 'FX_CLEARING')),
    balance_minor  INTEGER NOT NULL DEFAULT 0 CHECK (typeof(balance_minor) = 'integer'),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- user wallets belong to an account; system and FX wallets do not
    CHECK ((kind = 'USER') = (account_id IS NOT NULL)),
    -- only SYSTEM and FX_CLEARING may go negative (BR-2, FR-3.5)
    CHECK (kind <> 'USER' OR balance_minor >= 0),
    -- one wallet per account per currency (FR-1.2)
    UNIQUE (account_id, currency)
);
-- exactly one SYSTEM and one FX_CLEARING wallet per currency (FR-1.3)
CREATE UNIQUE INDEX ux_wallets_one_internal_per_currency
    ON wallets (kind, currency) WHERE kind <> 'USER';

-- ---------------------------------------------------------------
-- admin_keys: per-administrator keys, stored only as SHA-256 hashes
-- (NFR-9). Revocation sets revoked_at, so this table is NOT append-only.
-- ---------------------------------------------------------------
CREATE TABLE admin_keys (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
    key_hash    TEXT NOT NULL UNIQUE CHECK (length(key_hash) = 64),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revoked_at  TEXT
);

-- ---------------------------------------------------------------
-- fx_rates: append-only rate history; newest per pair is active (FR-6.1).
-- rate_scaled = rate x 1,000,000, from 1 to 10^12.
-- ---------------------------------------------------------------
CREATE TABLE fx_rates (
    id              TEXT PRIMARY KEY,
    base_currency   TEXT NOT NULL CHECK (base_currency IN ('INR', 'USD', 'EUR')),
    quote_currency  TEXT NOT NULL CHECK (quote_currency IN ('INR', 'USD', 'EUR')),
    rate_scaled     INTEGER NOT NULL CHECK (typeof(rate_scaled) = 'integer'
                                            AND rate_scaled BETWEEN 1 AND 1000000000000),
    admin_id        TEXT NOT NULL REFERENCES admin_keys(id),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (base_currency <> quote_currency)
);
CREATE INDEX ix_fx_rates_pair ON fx_rates (base_currency, quote_currency, created_at);

-- ---------------------------------------------------------------
-- transactions: one money movement (DEPOSIT, TRANSFER, REVERSAL).
-- seq is consecutive from 1 (FR-4.4); hash chains to prev_hash.
-- ---------------------------------------------------------------
CREATE TABLE transactions (
    id           TEXT PRIMARY KEY,
    seq          INTEGER NOT NULL UNIQUE CHECK (typeof(seq) = 'integer' AND seq >= 1),
    type         TEXT NOT NULL CHECK (type IN ('DEPOSIT', 'TRANSFER', 'REVERSAL')),
    reverses_id  TEXT UNIQUE REFERENCES transactions(id),   -- UNIQUE: reversed at most once (FR-4.3, BR-8)
    fx_rate_id   TEXT REFERENCES fx_rates(id),              -- set only for cross-currency transfers (FR-6.3)
    admin_id     TEXT REFERENCES admin_keys(id),            -- who made a reversal (FR-4.2)
    reason       TEXT CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 200),
    prev_hash    TEXT NOT NULL CHECK (length(prev_hash) = 64),
    hash         TEXT NOT NULL UNIQUE CHECK (length(hash) = 64),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- a REVERSAL, and only a REVERSAL, points at the transaction it reverses
    CHECK ((type = 'REVERSAL') = (reverses_id IS NOT NULL)),
    -- a REVERSAL records the administrator and a reason (FR-4.2)
    CHECK (type <> 'REVERSAL' OR (admin_id IS NOT NULL AND reason IS NOT NULL)),
    -- only transfers use an FX rate
    CHECK (fx_rate_id IS NULL OR type = 'TRANSFER')
);

-- ---------------------------------------------------------------
-- ledger_entries: the debit and credit lines of each transaction.
-- ---------------------------------------------------------------
CREATE TABLE ledger_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  TEXT NOT NULL REFERENCES transactions(id),
    wallet_id       TEXT NOT NULL REFERENCES wallets(id),
    direction       TEXT NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    amount_minor    INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer' AND amount_minor > 0),
    balance_after   INTEGER NOT NULL CHECK (typeof(balance_after) = 'integer')
);
CREATE INDEX ix_entries_wallet ON ledger_entries (wallet_id, id);
CREATE INDEX ix_entries_transaction ON ledger_entries (transaction_id);

-- ---------------------------------------------------------------
-- idempotency_keys: stored results for retries (FR-2.3 to FR-2.6).
-- transaction_id is NULL for stored business rejections (404/409/422).
-- ---------------------------------------------------------------
CREATE TABLE idempotency_keys (
    key             TEXT PRIMARY KEY CHECK (length(key) BETWEEN 8 AND 128),
    fingerprint     TEXT NOT NULL CHECK (length(fingerprint) = 64),
    status_code     INTEGER NOT NULL CHECK (status_code BETWEEN 200 AND 599),
    response_body   TEXT NOT NULL,
    transaction_id  TEXT REFERENCES transactions(id),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------
-- Immutability (FR-4.1): history tables reject UPDATE and DELETE.
-- ---------------------------------------------------------------
CREATE TRIGGER trg_transactions_no_update BEFORE UPDATE ON transactions
BEGIN SELECT RAISE(ABORT, 'transactions are immutable'); END;
CREATE TRIGGER trg_transactions_no_delete BEFORE DELETE ON transactions
BEGIN SELECT RAISE(ABORT, 'transactions are immutable'); END;

CREATE TRIGGER trg_entries_no_update BEFORE UPDATE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger_entries are immutable'); END;
CREATE TRIGGER trg_entries_no_delete BEFORE DELETE ON ledger_entries
BEGIN SELECT RAISE(ABORT, 'ledger_entries are immutable'); END;

CREATE TRIGGER trg_idem_no_update BEFORE UPDATE ON idempotency_keys
BEGIN SELECT RAISE(ABORT, 'idempotency_keys are immutable'); END;
CREATE TRIGGER trg_idem_no_delete BEFORE DELETE ON idempotency_keys
BEGIN SELECT RAISE(ABORT, 'idempotency_keys are immutable'); END;

CREATE TRIGGER trg_fx_no_update BEFORE UPDATE ON fx_rates
BEGIN SELECT RAISE(ABORT, 'fx_rates are immutable'); END;
CREATE TRIGGER trg_fx_no_delete BEFORE DELETE ON fx_rates
BEGIN SELECT RAISE(ABORT, 'fx_rates are immutable'); END;

-- Accounts and wallets are never deleted (BR-7).
CREATE TRIGGER trg_accounts_no_delete BEFORE DELETE ON accounts
BEGIN SELECT RAISE(ABORT, 'accounts are never deleted'); END;
CREATE TRIGGER trg_wallets_no_delete BEFORE DELETE ON wallets
BEGIN SELECT RAISE(ABORT, 'wallets are never deleted'); END;

# Brain Index

Entry point for the Financial Ledger & Wallet API knowledge base.
Start here. Read AGENTS.md at the repo root for how agents and humans should use this vault.

## Structure (PARA)
- [[inbox]]: unsorted new notes, waiting for brain-refine
- projects/: active work with deadlines
- areas/: ongoing responsibilities (requirements, reviews, ai-sessions)
- resources/: distilled reference notes and templates
- archive/: inactive notes

## Requirements
- [[FR-1]] Wallet initialization
- [[FR-2]] Idempotent transfers
- [[FR-3]] Concurrent balance changes
- [[FR-4]] Immutable audit trail
- [[FR-5]] Reconciliation

## Research notes
<!-- brain-refine keeps this list current -->
- [[double-entry-ledger]]: debits, credits, the SYSTEM wallet (FR-1, FR-4, FR-5)
- [[money-minor-units]]: why money is an integer (NFR-8, ADR 0001)
- [[sqlite-transactions-and-locking]]: BEGIN IMMEDIATE, WAL, busy timeout (FR-3)
- [[hash-chains]]: tamper evidence (FR-4.4, FR-5.2)

## Decisions (ADRs)
- docs/adr/0001-money-representation.md
- docs/adr/0002-ledger-schema.md

## Stage review notes
<!-- one link per stage, added at the end of each stage (SB-2) -->

## Run log
See [[log]].
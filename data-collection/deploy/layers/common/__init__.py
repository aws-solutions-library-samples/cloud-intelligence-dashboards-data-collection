"""
CID Common Lambda Layer

Shared utilities for CID data collection modules. This layer is deployed
as a Lambda Layer and made available to any module that needs it.

Usage in Lambda (when layer is attached):
    from common import assume_session, write_jsonl, enrich_record
"""

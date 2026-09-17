# Media Services Module - Claude Steering

This directory contains the spec-driven development guidance for the CID Media Services data collection module. These documents were ported from a Kiro spec-driven development session and provide the full context needed to continue implementation in Claude.

## How to Use These Documents

When working on this module, read these files in order:

1. **requirements.md** — The authoritative source of truth for what the module must do. Contains 20 requirements with formal acceptance criteria. When in doubt about behavior, this document is the final arbiter.

2. **design.md** — The technical design showing how the requirements are satisfied. Contains architecture, data models, component interfaces, correctness properties, error handling strategy, and testing approach. Use this to understand the "how" and to validate that implementation satisfies the formal properties.

3. **tasks.md** — The ordered implementation plan with progress tracking. Tasks are structured for incremental delivery with checkpoints. Pick up from the first incomplete task. Tasks marked `*` are optional property tests that can be deferred for MVP.

## Current State

- **Task 1 is complete.** The common layer (`local-test/lambdas/common/utils.py`) is
  class-based and working, and `local-test/lambdas/module-media-services.py` implements all
  11 collectors against it. Both pass pylint at 9.97/10 and have been exercised end to end
  against stubbed AWS responses shaped like `local-test/resource-deploy-scripts/baseline-media.yml`.
- **Not yet started:** the CloudFormation template. `data-collection/deploy/module-media-services.yaml`
  does not exist yet, and neither does the deployed layer at `data-collection/deploy/layers/common/`.
  Tasks 8 (Glue tables), 9 (IAM + promote code into `Code.ZipFile`), and 10 (wiring) are open.
- **Not yet written:** `local-test/tests/test_module_media_services.py`.

## Key Implementation Constraints

1. **Follow CID coding standards** — See `../../coding-standards.md` for CloudFormation template structure, inline Lambda conventions, naming patterns, and pylint configuration.

2. **Use the common layer** — Import from `common.utils` (not inline helpers). The layer is
   developed at `local-test/lambdas/common/` and will be published from
   `data-collection/deploy/layers/common/`. Declare collectors on a `DataCollectionModule`
   subclass rather than writing a region loop; see the Common Lambda Layer section of
   `design.md` for the class contract.

3. **Inline Lambda (ZipFile)** — The final Lambda code goes in the CloudFormation template's `Code.ZipFile` property with 10-space indentation. Develop in `local-test/lambdas/module-media-services.py` first, then promote.

4. **No Glue Crawler** — Use partition projection on all Glue tables. The Crawler resource
   should be removed if present. `projection.month.digits` and `projection.day.digits` must
   both be `'2'`, because the S3 keys are zero-padded; see `design.md`.

5. **Per-service output** — Each of the 11 collectors writes to its own S3 prefix and Glue table. Do not combine services into a single output file.

6. **Error resilience** — Each API sweep is guarded independently and returns the records it
   did collect; report contained failures with `ctx.note_failure()` so they appear in the
   Data Collection Monitor entry. Never let one service failure block others.

7. **Partition-aware ARNs** — Use `boto3.session.Session().get_partition_for_region()` for all ARN construction.

## Cross-References

Paths are relative to the repository root, `cloud-intelligence-dashboards-data-collection/`.

- Coding standards: `.ai/specs/coding-standards.md`
- Implementation patterns: `.ai/specs/implementation.md` (currently a stub)
- Lambda source: `local-test/lambdas/module-media-services.py`
- Common layer (local test): `local-test/lambdas/common/utils.py`
- Local runner and config: `local-test/run_lambda_local.py`, `local-test/config.json`
- Test fixture stack: `local-test/resource-deploy-scripts/baseline-media.yml`
- Runtime contracts (event payload, log entry schema): `data-collection/deploy/source/step-functions/main-state-machine.json`
- Module classification rules: `data-collection/MODULE_GUIDELINES.md`
- CFN template (to be created): `data-collection/deploy/module-media-services.yaml`
- Common layer (to be created): `data-collection/deploy/layers/common/`
- Test file (to be created): `local-test/tests/test_module_media_services.py`

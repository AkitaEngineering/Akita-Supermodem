# Release Runbook

Use this checklist when preparing a production or field-trial release.

## Pre-Release

1. Update `CHANGELOG.md`.
2. Confirm version in `pyproject.toml` and `akita_supermodem/__init__.py`.
3. Run tests:

   ```bash
   python -m pytest tests/ -q
   ```

4. Run compile check:

   ```bash
   python -m compileall -q akita_supermodem tests
   ```

5. Run lint:

   ```bash
   python -m flake8 akita_supermodem/ examples/ tests/ --max-line-length=120 --jobs=1
   ```

6. Regenerate protobuf only if `akita_supermodem/proto/akita.proto` changed:

   ```bash
   protoc --python_out=./akita_supermodem/generated --proto_path=./akita_supermodem/proto ./akita_supermodem/proto/akita.proto
   ```

7. Confirm generated protobuf runtime compatibility with the pinned dependency.

## Field-Trial Package

Include:

- Source or wheel/sdist artifact.
- Version and commit SHA.
- `README.md`.
- `docs/usage.md`.
- `docs/production_readiness.md`.
- `docs/key_management.md`.
- `docs/hardware_test_plan.md`.
- Known-good sample transfer artifact and expected hash/signature.

## Rollback

Keep the previous known-good package and PSK procedure available. If a release
fails in the field:

1. Stop transfers.
2. Collect logs from both endpoints.
3. Reinstall the previous known-good package.
4. Run a 1 KB transfer smoke test.
5. Document the failure before resuming larger transfers.

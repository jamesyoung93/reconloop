# Cluster setup and shared target storage

The package includes setup assets and diagnostics. A local passing test does not
establish that a remote cluster has the required runtime, mount or permissions.
Run the checks below on the actual driver before scheduling reconciliation.

## Python and OCR dependencies

Use Python 3.11 or newer. Build this checkout with `python -m build`, then install
its wheel plus the `ocr` extra in the notebook/job's Python environment. Install
Python dependencies through the platform's library/environment settings. Classic
cluster system packages can use `deploy/install-ocr.sh`; it requires explicit
`RECONLOOP_TESSERACT_VERSION` and `RECONLOOP_TESSERACT_ENG_VERSION` values matching
approved apt package versions for that runtime OS. Resolve those versions with
`apt-cache policy tesseract-ocr tesseract-ocr-eng` in the matching environment.
The script fails if version pins are absent. It does not install Python libraries.

Databricks recommends platform-managed Python libraries and pinned OS packages
in cluster-scoped init scripts when needed. Standard access mode requires init
script allowlisting; serverless compute does not support init scripts.
See [official init-script guidance](https://docs.databricks.com/aws/en/init-scripts)
and [library installation](https://docs.databricks.com/aws/en/libraries/).

Attach the script to classic compute using your normal cluster policy and restart
that cluster to apply it. For serverless, use a supported environment with the OCR
binary already available, or extract on appropriately configured classic compute
and publish reviewed targets for downstream reconciliation. The package does not
create clusters, change policies, install software remotely or supply credentials.

## Diagnose the actual process

```sh
reconloop doctor --ocr
reconloop doctor --ocr --path /Volumes/catalog/schema/volume/reconloop --write-probe
```

The diagnostic checks Python, PDF/image imports and versions, the Tesseract
binary and English language data, then renders a tiny PDF and reads known digits
through the actual OCR engine. Exit status 1 indicates a failed check and JSON
includes a remedy. `--path` checks an existing directory; `--write-probe` explicitly
creates, reads and removes one uniquely named probe file. It never installs
packages or changes permissions. `notebooks/cluster_readiness.py` runs the same
check in a notebook process. Driver success does not test executor environments;
this package's extraction and volume I/O are driver-side Python operations.

## Mounted volume paths

Use `/Volumes/catalog/schema/volume/path`. Source loaders and bundle operations
also normalize `dbfs:/Volumes/...` to the Python filesystem path. Legacy DBFS paths,
misspellings and traversal are rejected. Mounted volume I/O requires Linux, an
accessible existing volume root and `DATABRICKS_RUNTIME_VERSION` indicating at
least 13.3. Python >=3.11 remains a separate package requirement. Unknown runtimes
fail instead of creating directories that could be mistaken for persistent storage.
Local paths continue to work without any platform dependencies.

Volumes require compatible Unity Catalog-enabled compute. Grant the runtime
identity `USE CATALOG`, `USE SCHEMA`, `READ VOLUME` and, for publishers, `WRITE VOLUME`.
Provision the catalog/schema/volume through the platform, not filesystem calls.
See [volume requirements and paths](https://docs.databricks.com/aws/en/volumes/)
and [volume privileges](https://docs.databricks.com/aws/en/volumes/privileges).

## Publish a reviewed extraction

Start with an extraction directory produced by `ExtractionResult.write`, including
`targets.csv`, `extraction.json`, and optional `crops/*.png`. Every issue must be
resolved and the JSON target rows must agree with the CSV.

```sh
reconloop publish-targets private/extraction /Volumes/catalog/schema/volume/reconloop/targets --id reviewed-2026-01
```

Or use `publish_targets(extraction_dir, store_root, bundle_id=...)` from
`reconloop.storage`. A fresh bundle directory contains the reviewed CSV, extraction
evidence, available crop/page images and `READY.json`. The manifest contains a
schema version, UTC creation time, target count and SHA-256 for every copied file.
Publication never overwrites an existing bundle. Omit `--id` for a timestamp/UUID.

Readers require the ready marker and verify hashes and CSV/JSON consistency.
Incomplete copies and later modifications fail closed; a scheduler must handle
the failure, not fall back to an unverified CSV. The marker is written after copies
finish, avoiding reliance on atomic directory rename. Publish from a stable source
directory and use a single writer for any explicit bundle ID. Hashes detect damage;
they are not signatures or protection from an authorized writer replacing every
file and manifest. Use volume privileges and immutable operational practices.

```toml
[[targets.sources]]
type = "bundle"
file = "/Volumes/catalog/schema/volume/reconloop/targets/reviewed-2026-01"
```

Existing raw CSV/PDF sources can also use mounted paths, but only `type = "bundle"`
performs bundle integrity verification. Pin a specific reviewed bundle for each
run; there is no mutable `latest` alias. Use a separate volume directory for
`reconloop job` outputs. Keep all real inputs, credentials, crops and records in
that private environment. The repository contains only fictional generators.

Tests exercise publication, corruption, missing markers, path validation and
read/write probes locally. A live volume mount, access grants and classic cluster
init installation still require validation in your environment.

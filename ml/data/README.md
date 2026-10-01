# ML-owned data layout

This tree is intentionally separate from `data/`, which contains backend demo
and runtime data.

```text
ml/data/
  external/urbanev/
    source_manifest.json     # tracked provenance and checksum
    source_manifest.md       # tracked human-readable provenance
    raw/UrbanEVDataset.zip   # ignored immutable download
  vietnam/                   # ignored future operator/app exports
  contracts/                 # tracked schemas and mapping decisions
```

Never put a downloaded source archive, unredacted operator telemetry, user GPS,
SoC records or credentials in Git. Preserve raw observations append-only and
store only their manifest/checksum, schema version, source, timezone and access
policy in tracked files.

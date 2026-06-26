"""Run ledger and manifest store for the calibration pipeline.

Implements conflict-free, content-addressed run storage:
- Each run writes a self-describing manifest.json in its own S3 key
- A separate build_ledger() step lists manifests and assembles the
  global ledger (runs.jsonl) + the browsable site, avoiding S3-append races

RUN MANIFEST SCHEMA
-------------------

  {
    "kind": "sobol" | "mcmc" | "cv" | "hysplit",
    "tag": "2026-03-13_2026-03-16_N8192_seed42_2026-06-24T20:31Z",
    "window": ["2026-03-13", "2026-03-16"],
    "n_base_samples": 8192,
    "seed": 42,
    "git_sha": "1f241f6",
    "image_digest": "sha256:abc123...",
    "status": "complete" | "running" | "failed",
    "created": "2026-06-24T20:31:00Z",
    "duration_seconds": 3600,
    "skill": {
      "validation": 0.42,
      "test": null
    },
    "headline": {
      "top_param": "diel_phase_hours",
      "top_ST": 0.77
    },
    "artifacts": {
      "indices": "runs/sobol/<tag>/sobol_indices.parquet",
      "analysis": "runs/sobol/<tag>/analysis.json",
      "summary": "runs/sobol/<tag>/summary.md",
      "plots": "runs/sobol/<tag>/plots/"
    }
  }

S3 LAYOUT
---------

  s3://tj-calibration/
    runs/sobol/{tag}/
      manifest.json           ← written by sobol_post_analysis
      sobol_indices.parquet   ← indices table
      analysis.json           ← diagnostics dict
      summary.md              ← human-readable summary
      plots/                  ← PNG visualizations
    runs/mcmc/{tag}/
      manifest.json
      ...
    ledger/
      runs.jsonl              ← BUILT by build_ledger(): one manifest per line
    site/
      index.html              ← BUILT: sortable run list
      runs/
        sobol_{tag}.html      ← BUILT: per-run detail page
        mcmc_{tag}.html
        ...

USAGE
-----

In sobol_post_analysis (or any post-analysis asset):
  from nrp.runstore import write_manifest, RunManifest

  manifest = RunManifest(
    kind="sobol",
    tag=tag,
    window=[config.window_start, config.window_end],
    n_base_samples=config.n_base_samples,
    seed=config.seed,
    git_sha=...,
    image_digest=...,
    status="complete",
    created=datetime.now(tz=timezone.utc).isoformat(),
    duration_seconds=elapsed,
    headline={"top_param": top["parameter"], "top_ST": top["ST"]},
    artifacts={
      "indices": f"runs/sobol/{tag}/sobol_indices.parquet",
      "analysis": f"runs/sobol/{tag}/analysis.json",
      "summary": f"runs/sobol/{tag}/summary.md",
    }
  )
  write_manifest(s3_client, bucket, manifest)

In build_index asset:
  from nrp.runstore import build_ledger, build_site

  ledger = build_ledger(s3_client, bucket)  # dict: tag → Manifest
  html = build_site(ledger)
  s3_client.put_object(Bucket=bucket, Key="site/index.html", Body=html.encode())
"""

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import boto3


@dataclass
class RunManifest:
    """Self-describing run metadata and artifact pointers."""

    kind: str  # sobol | mcmc | cv | hysplit
    tag: str  # e.g., "2026-03-13_2026-03-16_N8192_seed42_2026-06-24T20:31Z"
    window: list[str]  # [start_date, end_date]
    n_base_samples: int | None = None  # Sobol-specific
    seed: int | None = None
    git_sha: str | None = None
    image_digest: str | None = None
    status: str = "complete"  # complete | running | failed
    created: str | None = None  # ISO 8601 timestamp
    duration_seconds: int | None = None
    skill: dict[str, float | None] = field(default_factory=dict)  # {validation: X, test: Y}
    headline: dict[str, Any] = field(default_factory=dict)  # {top_param, top_ST, ...}
    artifacts: dict[str, str] = field(default_factory=dict)  # {indices, analysis, summary, plots}


def write_manifest(
    s3_client: boto3.client,
    bucket: str,
    manifest: RunManifest,
) -> None:
    """Write a manifest to S3 at runs/{kind}/{tag}/manifest.json."""
    prefix = f"runs/{manifest.kind}/{manifest.tag}"
    key = f"{prefix}/manifest.json"
    body = json.dumps(asdict(manifest), indent=2).encode()
    s3_client.put_object(Bucket=bucket, Key=key, Body=body)


def build_ledger(
    s3_client: boto3.client,
    bucket: str,
) -> dict[str, RunManifest]:
    """List all manifests in S3 and return as a dict {tag → Manifest}."""
    ledger = {}
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="runs/"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/manifest.json"):
                try:
                    resp = s3_client.get_object(Bucket=bucket, Key=obj["Key"])
                    data = json.loads(resp["Body"].read())
                    manifest = RunManifest(**data)
                    ledger[manifest.tag] = manifest
                except Exception as e:
                    # Skip malformed manifests; log for review.
                    print(f"Warning: failed to parse {obj['Key']}: {e}")
    return ledger


def build_site(ledger: dict[str, RunManifest]) -> str:
    """Generate a sortable index.html from the ledger.

    Returns HTML as a string; caller writes to S3.
    """
    # Sort by created (newest first)
    sorted_runs = sorted(
        ledger.values(),
        key=lambda m: m.created or "",
        reverse=True,
    )

    rows = []
    for m in sorted_runs:
        skill_val = m.skill.get("validation") or m.skill.get("test") or "—"
        if isinstance(skill_val, (int, float)):
            skill_str = f"{skill_val:.3f}"
        else:
            skill_str = str(skill_val)

        rows.append(
            f"<tr>"
            f"<td>{m.kind}</td>"
            f"<td>{m.window[0]}</td>"
            f"<td>{m.window[1]}</td>"
            f"<td>{m.n_base_samples or '—'}</td>"
            f"<td>{skill_str}</td>"
            f"<td>{m.git_sha or '—'}</td>"
            f"<td><a href='runs/{m.kind}_{m.tag}.html'>view</a></td>"
            f"</tr>"
        )

    table = "\n".join(rows)
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Calibration Runs</title>
  <style>
    body {{ font-family: monospace; margin: 20px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
    th {{ background: #f0f0f0; }}
    a {{ color: #0066cc; }}
  </style>
</head>
<body>
  <h1>Calibration Runs</h1>
  <table>
    <thead>
      <tr>
        <th>kind</th>
        <th>start</th>
        <th>end</th>
        <th>N</th>
        <th>skill</th>
        <th>git_sha</th>
        <th>link</th>
      </tr>
    </thead>
    <tbody>
      {table}
    </tbody>
  </table>
</body>
</html>"""
    return html

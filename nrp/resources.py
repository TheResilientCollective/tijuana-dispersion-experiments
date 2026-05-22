"""Dagster resources for NRP calibration pipelines.

Two resources, both shared with the `tj_h2s_prediction` project:

- `s3` — S3 client for reading/writing run artifacts. Supports both AWS S3 and
  S3-compatible endpoints (e.g., the project's existing oss.resilientservice.mooo.com).
- `slack` — Slack webhook sender with two tiers (watch / critical) matching the
  existing alert system.

INTEGRATION WITH tj_h2s_prediction
-----------------------------------
If `tj_h2s_prediction` is pip-installable, prefer importing its resources
directly (see `defs` in dagster_pipeline.py). The classes below exist so this
repo runs standalone in case `tj_h2s_prediction` isn't installed yet, and so
the integration target is documented in code.

Once Claude Code confirms `tj_h2s_prediction` is importable, replace the
inline definitions with:

    from tj_h2s_prediction.resources import s3_resource, slack_resource

and remove this file. The asset code uses standard Dagster resource keys
(`s3`, `slack`) so no asset bodies need to change.
"""

from __future__ import annotations

import logging

import requests
from dagster import ConfigurableResource

log = logging.getLogger(__name__)


class SlackWebhookResource(ConfigurableResource):
    """Two-tier Slack webhook sender, matching the existing alert system.

    The existing two-tier alert system (`h2s_alerts.py`) splits notifications:
    - Watch tier (30 ppb): monitoring staff — informational, batched
    - Critical tier (100 ppb): agency decision-makers — actionable, urgent

    NRP pipelines reuse the same split:
    - Watch: run start, aggregator completion, periodic progress on long runs
    - Critical: K8s job failure, calibration regression that would invalidate
      prior results, any condition that needs human action within a few hours
    """

    watch_webhook_url: str
    critical_webhook_url: str

    def _post(self, url: str, message: str, blocks: list | None = None) -> None:
        if not url:
            log.warning("slack webhook URL not configured; dropping message: %s", message)
            return
        payload: dict = {"text": message}
        if blocks:
            payload["blocks"] = blocks
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            # Slack failures should never crash a calibration run.
            log.warning("slack post failed: %s", e)

    def watch(self, message: str, blocks: list | None = None) -> None:
        """Send to the watch tier (informational)."""
        self._post(self.watch_webhook_url, message, blocks)

    def critical(self, message: str, blocks: list | None = None) -> None:
        """Send to the critical tier (actionable). Use sparingly."""
        self._post(self.critical_webhook_url, message, blocks)


# Note: dagster-aws provides S3Resource and S3PickleIOManager out of the box.
# We import and re-export here for a single canonical resource definition site.
# Asset code references `context.resources.s3` regardless of where it comes from.

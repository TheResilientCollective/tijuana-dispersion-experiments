#!/bin/sh
# Install the `service` extra (private tijuana-dispersion git dep) using
# a BuildKit-mounted GitHub token. The token is read from the mounted
# secret file, used only for this `uv sync`, and the git rewrite rule is
# removed in the same layer — it is never persisted in the image.
set -e

if [ -f /run/secrets/gh_token ]; then
  git config --global url."https://$(cat /run/secrets/gh_token)@github.com/".insteadOf "https://github.com/"  # pragma: allowlist secret
fi

uv sync --frozen --no-dev --no-install-project --extra service

git config --global --unset-all url."https://github.com/".insteadOf 2>/dev/null || true

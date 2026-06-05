#!/usr/bin/env bash
# Provision the dev environment: uv + the MS ODBC Driver 18, then sync all deps.
# Runs once when the dev container is created. Docker (for the stack) comes from the
# docker-outside-of-docker feature, so `make up-*` talks to the host daemon.
set -euo pipefail

# uv (Python package/env manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Microsoft ODBC Driver 18 (Debian 12 / bookworm) for pyodbc -> SQL Server
curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update && sudo ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18

# Python deps (all extras so every phase works out of the box)
export PATH="$HOME/.local/bin:$PATH"
uv sync --all-extras
echo "Dev container ready. Try: make up-serve"

#!/usr/bin/env bash
#
# Provision a tenant workspace.
#
# SMOKE TEST FIXTURE — clean counterpart to bad_04_provision.sh.
# Expected: PASS with no critical or high findings.

set -euo pipefail

readonly TENANT_ROOT="/srv/tenants"

usage() {
  echo "usage: $(basename "$0") <tenant-slug> <aws-region>" >&2
  exit 64
}

[ "$#" -eq 2 ] || usage

tenant="$1"
region="$2"

# Whitelist the tenant slug: it becomes a path component and a database name.
if ! [[ "$tenant" =~ ^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$ ]]; then
  echo "error: tenant slug must be 3-40 chars of [a-z0-9-]" >&2
  exit 65
fi

if ! [[ "$region" =~ ^[a-z]{2}-[a-z]+-[0-9]$ ]]; then
  echo "error: '$region' is not a valid AWS region" >&2
  exit 65
fi

: "${TENANT_DB_PASSWORD:?TENANT_DB_PASSWORD must be set in the environment}"

workdir="${TENANT_ROOT}/${tenant}"

# Refuse to touch anything outside the tenant root, even if the guards above
# are ever loosened.
case "$workdir" in
  "${TENANT_ROOT}/"?*) ;;
  *) echo "error: refusing to operate on '$workdir'" >&2; exit 70 ;;
esac

if [ -d "$workdir" ]; then
  echo "error: $workdir already exists; remove it deliberately first" >&2
  exit 73
fi

mkdir -p "$workdir"

aws s3 sync "s3://tenant-assets/${tenant}" "$workdir" --region "$region"

# Password comes from the environment, never the argv visible in `ps`.
MYSQL_PWD="$TENANT_DB_PASSWORD" mysql \
  --user=admin \
  --execute="CREATE DATABASE \`tenant_${tenant}\`;"

curl --fail --silent --show-error --max-time 30 \
  "https://api.internal/tenants/${tenant}/activate"

echo "provisioned ${tenant} in ${region}"

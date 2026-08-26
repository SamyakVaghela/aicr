#!/bin/bash
#
# Provision a tenant workspace.
#
# SMOKE TEST FIXTURE — deliberately broken. Do not copy this code.
# Expected: BLOCKED (command injection, unquoted expansion into rm -rf,
# no error handling, credentials on the command line).

TENANT=$1
REGION=$2
DB_PASSWORD="Pr0dTenant!2024"

WORKDIR=/srv/tenants/$TENANT

# $TENANT is attacker-controlled; an empty or crafted value deletes the wrong tree.
rm -rf $WORKDIR
mkdir -p $WORKDIR

# Unvalidated input interpolated straight into a shell command.
eval "aws s3 sync s3://tenant-assets/$TENANT $WORKDIR --region $REGION"

# Password visible in `ps` output and shell history.
mysql -u admin -p$DB_PASSWORD -e "CREATE DATABASE tenant_$TENANT;"

curl -s "https://api.internal/tenants/$TENANT/activate"

echo "provisioned $TENANT"
exit 0

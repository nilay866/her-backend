#!/usr/bin/env bash
set -euo pipefail

REGION="${1:-ap-south-1}"
EC2_ID="${2:-i-01e9b3c211aaca94b}"
RDS_ID="${3:-hercare-dbb}"
CF_FRONTEND_ID="${4:-E214DC5NC7861G}"
CF_BACKEND_ID="${5:-E3FLYSZVJQREQZ}"
RULE_NAME="${6:-hercare-cost-guard-every-1h}"
LAMBDA_NAME="${7:-hercare-cost-guard}"

echo "Restore services started..."
echo "Region: ${REGION}"

echo "Starting EC2: ${EC2_ID}"
aws ec2 start-instances --instance-ids "${EC2_ID}" --region "${REGION}" >/dev/null 2>&1 || true

echo "Starting RDS: ${RDS_ID}"
aws rds start-db-instance --db-instance-identifier "${RDS_ID}" --region "${REGION}" >/dev/null 2>&1 || true

enable_distribution() {
  local dist_id="$1"
  local raw etag cfg_file
  raw="$(aws cloudfront get-distribution-config --id "${dist_id}" --output json)"
  etag="$(echo "${raw}" | jq -r '.ETag')"
  cfg_file="$(mktemp)"
  echo "${raw}" | jq '.DistributionConfig | .Enabled=true' > "${cfg_file}"
  aws cloudfront update-distribution \
    --id "${dist_id}" \
    --if-match "${etag}" \
    --distribution-config "file://${cfg_file}" >/dev/null
  rm -f "${cfg_file}"
}

echo "Enabling CloudFront: ${CF_FRONTEND_ID}"
enable_distribution "${CF_FRONTEND_ID}" || true
echo "Enabling CloudFront: ${CF_BACKEND_ID}"
enable_distribution "${CF_BACKEND_ID}" || true

echo "Enabling EventBridge rule: ${RULE_NAME}"
aws events enable-rule --name "${RULE_NAME}" --region "${REGION}" >/dev/null 2>&1 || true

echo "Removing Lambda concurrency cap: ${LAMBDA_NAME}"
aws lambda delete-function-concurrency \
  --function-name "${LAMBDA_NAME}" \
  --region "${REGION}" >/dev/null 2>&1 || true

echo "Restore request submitted."

#!/usr/bin/env bash
set -euo pipefail

REGION="${1:-ap-south-1}"
EC2_ID="${2:-i-01e9b3c211aaca94b}"
RDS_ID="${3:-hercare-dbb}"
CF_FRONTEND_ID="${4:-E214DC5NC7861G}"
CF_BACKEND_ID="${5:-E3FLYSZVJQREQZ}"
RULE_NAME="${6:-hercare-cost-guard-every-1h}"
LAMBDA_NAME="${7:-hercare-cost-guard}"

echo "Emergency shutdown started..."
echo "Region: ${REGION}"

echo "Stopping EC2: ${EC2_ID}"
aws ec2 stop-instances --instance-ids "${EC2_ID}" --region "${REGION}" >/dev/null 2>&1 || true

echo "Stopping RDS: ${RDS_ID}"
aws rds stop-db-instance --db-instance-identifier "${RDS_ID}" --region "${REGION}" >/dev/null 2>&1 || true

disable_distribution() {
  local dist_id="$1"
  local raw etag cfg_file
  raw="$(aws cloudfront get-distribution-config --id "${dist_id}" --output json)"
  etag="$(echo "${raw}" | jq -r '.ETag')"
  cfg_file="$(mktemp)"
  echo "${raw}" | jq '.DistributionConfig | .Enabled=false' > "${cfg_file}"
  aws cloudfront update-distribution \
    --id "${dist_id}" \
    --if-match "${etag}" \
    --distribution-config "file://${cfg_file}" >/dev/null
  rm -f "${cfg_file}"
}

echo "Disabling CloudFront: ${CF_FRONTEND_ID}"
disable_distribution "${CF_FRONTEND_ID}" || true
echo "Disabling CloudFront: ${CF_BACKEND_ID}"
disable_distribution "${CF_BACKEND_ID}" || true

echo "Disabling EventBridge rule: ${RULE_NAME}"
aws events disable-rule --name "${RULE_NAME}" --region "${REGION}" >/dev/null 2>&1 || true

echo "Setting Lambda concurrency to 0: ${LAMBDA_NAME}"
aws lambda put-function-concurrency \
  --function-name "${LAMBDA_NAME}" \
  --reserved-concurrent-executions 0 \
  --region "${REGION}" >/dev/null 2>&1 || true

echo "Emergency shutdown request submitted."

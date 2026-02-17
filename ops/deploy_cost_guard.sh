#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./ops/deploy_cost_guard.sh <AWS_REGION> <EC2_INSTANCE_ID> <RDS_DB_ID> <CF_FRONTEND_ID> <CF_BACKEND_ID>
#
# Example:
#   ./ops/deploy_cost_guard.sh ap-south-1 i-01e9b3c211aaca94b hercare-dbb E214DC5NC7861G E3FLYSZVJQREQZ

REGION="${1:-ap-south-1}"
EC2_ID="${2:-}"
RDS_ID="${3:-}"
CF_FRONTEND_ID="${4:-}"
CF_BACKEND_ID="${5:-}"

if [[ -z "${EC2_ID}" || -z "${RDS_ID}" || -z "${CF_FRONTEND_ID}" || -z "${CF_BACKEND_ID}" ]]; then
  echo "Missing args."
  echo "Usage: ./ops/deploy_cost_guard.sh <region> <ec2_id> <rds_id> <cf_frontend_id> <cf_backend_id>"
  exit 1
fi

ROLE_NAME="hercare-cost-guard-lambda-role"
LAMBDA_NAME="hercare-cost-guard"
RULE_NAME="hercare-cost-guard-every-1h"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

cp ops/cost_guard_lambda.py "${WORKDIR}/lambda_function.py"
(cd "${WORKDIR}" && zip -q function.zip lambda_function.py)

cat > "${WORKDIR}/trust-policy.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

if ! aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${WORKDIR}/trust-policy.json" >/dev/null
fi

aws iam attach-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole >/dev/null

cat > "${WORKDIR}/inline-policy.json" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostExplorerRead",
      "Effect": "Allow",
      "Action": ["ce:GetCostAndUsage"],
      "Resource": "*"
    },
    {
      "Sid": "Ec2Control",
      "Effect": "Allow",
      "Action": ["ec2:DescribeInstances", "ec2:StopInstances"],
      "Resource": "*"
    },
    {
      "Sid": "RdsControl",
      "Effect": "Allow",
      "Action": ["rds:DescribeDBInstances", "rds:StopDBInstance"],
      "Resource": "*"
    },
    {
      "Sid": "CloudFrontControl",
      "Effect": "Allow",
      "Action": [
        "cloudfront:GetDistributionConfig",
        "cloudfront:UpdateDistribution"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EventBridgeSelfDisable",
      "Effect": "Allow",
      "Action": [
        "events:DisableRule",
        "events:ListTargetsByRule",
        "events:RemoveTargets"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaSelfDisable",
      "Effect": "Allow",
      "Action": [
        "lambda:PutFunctionConcurrency"
      ],
      "Resource": "*"
    }
  ]
}
JSON

aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${ROLE_NAME}-inline" \
  --policy-document "file://${WORKDIR}/inline-policy.json" >/dev/null

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# IAM propagation buffer
sleep 10

if aws lambda get-function --function-name "${LAMBDA_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  aws lambda update-function-code \
    --function-name "${LAMBDA_NAME}" \
    --zip-file "fileb://${WORKDIR}/function.zip" \
    --region "${REGION}" >/dev/null
  aws lambda wait function-updated \
    --function-name "${LAMBDA_NAME}" \
    --region "${REGION}"
else
  aws lambda create-function \
    --function-name "${LAMBDA_NAME}" \
    --runtime python3.12 \
    --role "${ROLE_ARN}" \
    --handler lambda_function.handler \
    --zip-file "fileb://${WORKDIR}/function.zip" \
    --timeout 60 \
    --memory-size 256 \
    --region "${REGION}" >/dev/null
  aws lambda wait function-active-v2 \
    --function-name "${LAMBDA_NAME}" \
    --region "${REGION}"
fi

aws lambda update-function-configuration \
  --function-name "${LAMBDA_NAME}" \
  --environment "$(jq -nc \
    --arg threshold "0.01" \
    --arg dryrun "false" \
    --arg selfDisable "true" \
    --arg ruleName "${RULE_NAME}" \
    --arg lambdaName "${LAMBDA_NAME}" \
    --arg ec2 "${EC2_ID}" \
    --arg rds "${RDS_ID}" \
    --arg cf "${CF_FRONTEND_ID},${CF_BACKEND_ID}" \
    '{Variables:{NET_COST_THRESHOLD_USD:$threshold,DRY_RUN:$dryrun,SELF_DISABLE_ON_TRIGGER:$selfDisable,SCHEDULER_RULE_NAME:$ruleName,LAMBDA_FUNCTION_NAME:$lambdaName,EC2_INSTANCE_IDS:$ec2,RDS_INSTANCE_IDS:$rds,CLOUDFRONT_DISTRIBUTION_IDS:$cf}}')" \
  --region "${REGION}" >/dev/null
aws lambda wait function-updated \
  --function-name "${LAMBDA_NAME}" \
  --region "${REGION}"

RULE_ARN="$(aws events put-rule \
  --name "${RULE_NAME}" \
  --schedule-expression 'rate(1 hour)' \
  --state ENABLED \
  --region "${REGION}" \
  --query RuleArn --output text)"

aws events put-targets \
  --rule "${RULE_NAME}" \
  --targets "Id"="1","Arn"="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LAMBDA_NAME}" \
  --region "${REGION}" >/dev/null

if ! aws lambda get-policy --function-name "${LAMBDA_NAME}" --region "${REGION}" 2>/dev/null | grep -q "${RULE_NAME}"; then
  aws lambda add-permission \
    --function-name "${LAMBDA_NAME}" \
    --statement-id "${RULE_NAME}" \
    --action "lambda:InvokeFunction" \
    --principal events.amazonaws.com \
    --source-arn "${RULE_ARN}" \
    --region "${REGION}" >/dev/null
fi

echo "Cost guard deployed."
echo "Lambda: ${LAMBDA_NAME}"
echo "Rule: ${RULE_NAME}"

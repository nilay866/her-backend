#!/usr/bin/env bash
set -euo pipefail

REGION="${1:-ap-south-1}"
LAMBDA_NAME="${2:-hercare-cost-guard}"
RULE_NAME="${3:-hercare-cost-guard-every-1h}"

today="$(date -u +%Y-%m-%d)"
month_start="$(date -u +%Y-%m-01)"

echo "=== Cost Guard Status ==="
echo "Region: ${REGION}"
echo "Lambda: ${LAMBDA_NAME}"
echo "Rule:   ${RULE_NAME}"
echo

echo "--- Lambda Configuration ---"
aws lambda get-function-configuration \
  --function-name "${LAMBDA_NAME}" \
  --region "${REGION}" \
  --query '{
    State: State,
    LastUpdateStatus: LastUpdateStatus,
    ReservedConcurrency: ReservedConcurrentExecutions,
    Threshold: Environment.Variables.NET_COST_THRESHOLD_USD,
    DryRun: Environment.Variables.DRY_RUN,
    SelfDisable: Environment.Variables.SELF_DISABLE_ON_TRIGGER
  }' \
  --output table
echo

echo "--- EventBridge Rule ---"
aws events describe-rule \
  --name "${RULE_NAME}" \
  --region "${REGION}" \
  --query '{State: State, Schedule: ScheduleExpression, Arn: Arn}' \
  --output table
echo

echo "--- EventBridge Targets ---"
aws events list-targets-by-rule \
  --rule "${RULE_NAME}" \
  --region "${REGION}" \
  --query 'Targets[].{Id: Id, Arn: Arn}' \
  --output table
echo

echo "--- Current Month Net Cost (USD) ---"
aws ce get-cost-and-usage \
  --region us-east-1 \
  --time-period Start="${month_start}",End="${today}" \
  --granularity MONTHLY \
  --metrics NetUnblendedCost \
  --query 'ResultsByTime[0].Total.NetUnblendedCost'

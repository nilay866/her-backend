# Cost Guard (Auto Disable When Credits Are Over)

This automation checks monthly `NetUnblendedCost` (after credits/discounts).
If cost is greater than threshold, it:

- stops configured EC2 instances
- stops configured RDS instances
- disables configured CloudFront distributions
- disables its EventBridge schedule and freezes its own Lambda concurrency

## Files

- `ops/cost_guard_lambda.py`
- `ops/deploy_cost_guard.sh`

## Deploy

From `hercare-backend/`:

```bash
chmod +x ops/deploy_cost_guard.sh
./ops/deploy_cost_guard.sh ap-south-1 i-01e9b3c211aaca94b hercare-dbb E214DC5NC7861G E3FLYSZVJQREQZ
```

## Notes

- Trigger schedule: every 1 hour.
- Threshold: `NET_COST_THRESHOLD_USD=0.01`.
- Cost Explorer data can lag by several hours.
- Exact zero overage is not guaranteed because AWS billing metrics are delayed.
- Stopped RDS can auto-start after ~7 days by AWS behavior. For strict zero bill, delete DB resources manually when needed.
- S3 storage may still incur tiny charges if objects remain.

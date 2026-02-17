import datetime as dt
import os
from typing import List

import boto3


ce = boto3.client("ce", region_name="us-east-1")
ec2 = boto3.client("ec2")
rds = boto3.client("rds")
cloudfront = boto3.client("cloudfront")
events = boto3.client("events")
lambda_client = boto3.client("lambda")


def _split_env(name: str) -> List[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _month_bounds_utc() -> tuple[str, str]:
    today = dt.date.today()
    start = today.replace(day=1)
    # Cost Explorer End is exclusive, so use tomorrow.
    end = today + dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _net_cost_usd() -> float:
    start, end = _month_bounds_utc()
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["NetUnblendedCost"],
    )
    rows = resp.get("ResultsByTime", [])
    if not rows:
        return 0.0
    amount = rows[0].get("Total", {}).get("NetUnblendedCost", {}).get("Amount", "0")
    try:
        return float(amount)
    except Exception:
        return 0.0


def _stop_ec2(instance_ids: List[str], dry_run: bool) -> List[str]:
    if not instance_ids:
        return []

    desc = ec2.describe_instances(InstanceIds=instance_ids)
    running = []
    for reservation in desc.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            state = (inst.get("State") or {}).get("Name")
            if state == "running":
                running.append(inst["InstanceId"])

    if running and not dry_run:
        ec2.stop_instances(InstanceIds=running)
    return running


def _stop_rds(db_ids: List[str], dry_run: bool) -> List[str]:
    if not db_ids:
        return []

    stoppable = []
    for db_id in db_ids:
        try:
            resp = rds.describe_db_instances(DBInstanceIdentifier=db_id)
            item = resp["DBInstances"][0]
            status = item.get("DBInstanceStatus")
            engine = (item.get("Engine") or "").lower()
            # Aurora clusters are handled differently; skip here.
            if status == "available" and not engine.startswith("aurora"):
                stoppable.append(db_id)
        except Exception:
            continue

    if not dry_run:
        for db_id in stoppable:
            try:
                rds.stop_db_instance(DBInstanceIdentifier=db_id)
            except Exception:
                pass
    return stoppable


def _disable_cloudfront(distribution_ids: List[str], dry_run: bool) -> List[str]:
    changed = []
    for dist_id in distribution_ids:
        try:
            cfg = cloudfront.get_distribution_config(Id=dist_id)
            etag = cfg["ETag"]
            dist_cfg = cfg["DistributionConfig"]
            if dist_cfg.get("Enabled", True):
                if not dry_run:
                    dist_cfg["Enabled"] = False
                    cloudfront.update_distribution(
                        Id=dist_id,
                        IfMatch=etag,
                        DistributionConfig=dist_cfg,
                    )
                changed.append(dist_id)
        except Exception:
            continue
    return changed


def _disable_automation(rule_name: str, lambda_name: str, dry_run: bool) -> dict:
    out = {
        "disabled_rule": False,
        "removed_targets": False,
        "lambda_concurrency_zero": False,
    }
    if dry_run:
        return out

    # 1) Disable schedule rule
    try:
        events.disable_rule(Name=rule_name)
        out["disabled_rule"] = True
    except Exception:
        pass

    # 2) Remove all targets from the rule
    try:
        targets = events.list_targets_by_rule(Rule=rule_name).get("Targets", [])
        if targets:
            events.remove_targets(
                Rule=rule_name,
                Ids=[t["Id"] for t in targets],
                Force=True,
            )
        out["removed_targets"] = True
    except Exception:
        pass

    # 3) Freeze lambda execution
    try:
        lambda_client.put_function_concurrency(
            FunctionName=lambda_name,
            ReservedConcurrentExecutions=0,
        )
        out["lambda_concurrency_zero"] = True
    except Exception:
        pass

    return out


def handler(event, context):
    threshold = float(os.getenv("NET_COST_THRESHOLD_USD", "0.01"))
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    self_disable = os.getenv("SELF_DISABLE_ON_TRIGGER", "true").lower() == "true"
    rule_name = os.getenv("SCHEDULER_RULE_NAME", "hercare-cost-guard-every-1h")
    lambda_name = os.getenv("LAMBDA_FUNCTION_NAME", context.function_name)

    ec2_ids = _split_env("EC2_INSTANCE_IDS")
    rds_ids = _split_env("RDS_INSTANCE_IDS")
    cf_ids = _split_env("CLOUDFRONT_DISTRIBUTION_IDS")

    current_net = _net_cost_usd()

    result = {
        "net_cost_usd": current_net,
        "threshold_usd": threshold,
        "dry_run": dry_run,
        "action_taken": False,
        "stopped_ec2": [],
        "stopped_rds": [],
        "disabled_cloudfront": [],
        "automation_shutdown": {},
    }

    if current_net <= threshold:
        return result

    result["action_taken"] = True
    result["stopped_ec2"] = _stop_ec2(ec2_ids, dry_run=dry_run)
    result["stopped_rds"] = _stop_rds(rds_ids, dry_run=dry_run)
    result["disabled_cloudfront"] = _disable_cloudfront(cf_ids, dry_run=dry_run)
    if self_disable:
        result["automation_shutdown"] = _disable_automation(
            rule_name=rule_name,
            lambda_name=lambda_name,
            dry_run=dry_run,
        )
    return result

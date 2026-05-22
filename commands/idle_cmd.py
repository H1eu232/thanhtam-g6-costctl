"""idle — (stretch) find idle EC2 instances by N-hour CPU average.

WHAT YOU MUST BUILD
-------------------
A script that:
  1. Iterates running EC2 instances (skip ones tagged `keep=true`)
  2. For each, queries CloudWatch CPUUtilization average over last N hours
  3. Marks as IDLE if avg < threshold
  4. Prints per-instance status + final idle list

AWS APIS YOU'LL NEED
--------------------
cw = boto3.client("cloudwatch")
cw.get_metric_statistics(
    Namespace="AWS/EC2",
    MetricName="CPUUtilization",
    Dimensions=[{"Name": "InstanceId", "Value": iid}],
    StartTime=<datetime>, EndTime=<datetime>,
    Period=3600,            # 1-hour buckets
    Statistics=["Average"],
)
Response: resp["Datapoints"] is a list of dicts with "Average" key.

NOTE: CloudWatch metrics start populating ~5 min after instance launch. New
instances (< 1h running) typically return zero Datapoints — handle that as
"NO DATA", not as idle.

EXPECTED OUTPUT FORMAT
----------------------
    Scanning running EC2 (excluding keep=true) — threshold 5.0% over 24h:
    ------------------------------------------------------------------------------
      i-0abc123def456789a   t3.micro     cpu_24h= 1.20%  <- IDLE
      i-0bbb456ef789012345   t3.small     cpu_24h=42.50%
      i-0ccc789f0123456789   t3.nano      cpu_24h=NO DATA
    ------------------------------------------------------------------------------

    Idle: 1 instance(s): ['i-0abc123def456789a']
    Tip: combo with terminate →  ./costctl.py terminate ec2 --id <id>

VERIFY MANUALLY (no test file for this command)
-----------------------------------------------
    ./costctl.py idle --threshold 5 --hours 24

If nothing idle in your account, lower threshold to e.g. 50 to test the
path: `./costctl.py idle --threshold 50 --hours 1`.

COMBO IDEA FOR W6 EVIDENCE PACK
-------------------------------
1. Run `idle` to find waste
2. `terminate` the idle instances
3. Run `cost --tag Application=<your-app>` 24h later
4. Document the delta in your evidence pack
"""
import boto3
from datetime import datetime, timedelta, timezone
from statistics import mean

from commands._common import tags_to_dict


def _avg_cpu(cw, instance_id, hours):
    """Return average CPU% over last N hours, or None if no datapoints."""
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=hours)
    
    response = cw.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start_time,
        EndTime=now,
        Period=3600,
        Statistics=["Average"],
    )
    
    datapoints = response.get("Datapoints", [])
    if not datapoints:
        return None
    
    # Calculate average of all datapoint averages
    averages = [dp["Average"] for dp in datapoints]
    return mean(averages) if averages else None


def run(args):
    """Entry point.

    Args set by argparse:
        args.threshold  — float, default 5.0 (% CPU)
        args.hours      — int, default 24
    """
    ec2 = boto3.client("ec2")
    cw = boto3.client("cloudwatch")
    
    threshold = args.threshold
    hours = args.hours
    
    print(f"Scanning running EC2 (excluding keep=true) - threshold {threshold}% over {hours}h:")
    print("-" * 80)
    
    # Get running instances
    response = ec2.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )
    
    idle_instances = []
    
    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            instance_id = instance["InstanceId"]
            instance_type = instance["InstanceType"]
            
            # Skip instances tagged with keep=true
            tags = tags_to_dict(instance.get("Tags", []))
            if tags.get("keep") == "true":
                continue
            
            # Get CPU average
            avg_cpu = _avg_cpu(cw, instance_id, hours)
            
            if avg_cpu is None:
                cpu_str = "NO DATA"
            else:
                cpu_str = f"{avg_cpu:>6.2f}%"
            
            # Determine idle status
            is_idle = avg_cpu is not None and avg_cpu < threshold
            idle_marker = "  <- IDLE" if is_idle else ""
            
            print(f"  {instance_id:<30} {instance_type:<12} cpu_{hours}h={cpu_str}{idle_marker}")
            
            if is_idle:
                idle_instances.append(instance_id)
    
    print("-" * 80)
    
    if idle_instances:
        print(f"\nIdle: {len(idle_instances)} instance(s): {idle_instances}")
        print("Tip: combo with terminate ->  ./costctl.py terminate ec2 --id <id>")
    else:
        print("\nNo idle instances found.")

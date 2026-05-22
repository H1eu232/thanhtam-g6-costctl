"""list — list AWS resources by type, filter by tag / missing-tag.

WHAT YOU MUST BUILD
-------------------
Support 4 resource types: ec2, rds, s3, volume.
Each takes:
- `want` — list of (key, value) tag pairs the resource MUST have
- `missing` — list of tag keys the resource MUST NOT have

Print a formatted table to stdout. Test cases are in tests/test_list.py.

HELPERS YOU CAN USE
-------------------
From commands._common:
  parse_kv(s) -> (k, v)            # "Owner=alice" -> ("Owner", "alice")
  tags_to_dict(items) -> dict       # boto3 [{"Key","Value"}] -> {k: v}
  tags_match(tags, want, missing) -> bool

AWS APIS YOU'LL NEED
--------------------
- EC2: ec2.describe_instances() with get_paginator
- RDS: rds.describe_db_instances(), then list_tags_for_resource(ResourceName=arn)
- S3:  s3.list_buckets(), then get_bucket_tagging(Bucket=name)
       (catch ClientError when bucket has no tagging config — treat as {})
- EBS: ec2.describe_volumes() with get_paginator

EXPECTED OUTPUT FORMAT (when run from CLI)
------------------------------------------
    EC2 Environment=dev — 1 found:
    ------------------------------------------------------------------------------
      i-0abc123def456789a       t3.micro       running       Environment=dev

VERIFY
------
    pytest tests/test_list.py -v
"""
import boto3
from botocore.exceptions import ClientError

from commands._common import tags_to_dict, tags_match, parse_kv


def _list_ec2(want_pairs, missing_keys):
    """List EC2 instances matching tag filters. Return list of [id, type, state, tags_dict]."""
    ec2 = boto3.client("ec2")
    rows = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                tags = tags_to_dict(instance.get("Tags", []))
                if tags_match(tags, want_pairs, missing_keys):
                    rows.append([
                        instance["InstanceId"],
                        instance["InstanceType"],
                        instance["State"]["Name"],
                        tags,
                    ])
    return rows


def _list_rds(want_pairs, missing_keys):
    """List RDS instances matching tag filters. Return list of [id, engine, state, tags_dict]."""
    rds = boto3.client("rds")
    rows = []
    response = rds.describe_db_instances()
    for db in response.get("DBInstances", []):
        arn = db["DBInstanceArn"]
        try:
            tag_response = rds.list_tags_for_resource(ResourceName=arn)
            tags = tags_to_dict(tag_response.get("TagList", []))
        except ClientError:
            tags = {}
        
        if tags_match(tags, want_pairs, missing_keys):
            rows.append([
                db["DBInstanceIdentifier"],
                db["Engine"],
                db["DBInstanceStatus"],
                tags,
            ])
    return rows


def _list_s3(want_pairs, missing_keys):
    """List S3 buckets matching tag filters. Return list of [bucket_name, region, "", tags_dict]."""
    s3 = boto3.client("s3")
    rows = []
    response = s3.list_buckets()
    
    for bucket in response.get("Buckets", []):
        bucket_name = bucket["Name"]
        try:
            tag_response = s3.get_bucket_tagging(Bucket=bucket_name)
            tags = tags_to_dict(tag_response.get("TagSet", []))
        except ClientError:
            # No tagging config, treat as empty tags
            tags = {}
        
        if tags_match(tags, want_pairs, missing_keys):
            rows.append([
                bucket_name,
                "s3",
                "",
                tags,
            ])
    return rows


def _list_volume(want_pairs, missing_keys):
    """List EBS volumes matching tag filters. Return list of [id, type-size, state, tags_dict]."""
    ec2 = boto3.client("ec2")
    rows = []
    paginator = ec2.get_paginator("describe_volumes")
    
    for page in paginator.paginate():
        for volume in page["Volumes"]:
            tags = tags_to_dict(volume.get("Tags", []))
            if tags_match(tags, want_pairs, missing_keys):
                vol_type_size = f"{volume['VolumeType']}-{volume['Size']}GB"
                rows.append([
                    volume["VolumeId"],
                    vol_type_size,
                    volume["State"],
                    tags,
                ])
    return rows


def run(args):
    """Entry point.
    
    Args set by argparse:
        args.type       — one of "ec2", "rds", "s3", "volume"
        args.tag        — list of "key=value" strings
        args.missing_tag — list of tag key strings
    """
    # Parse tags into want_pairs and missing_keys
    want_pairs = [parse_kv(t) for t in args.tag]
    missing_keys = args.missing_tag
    
    # Dispatch to appropriate function
    dispatch = {
        "ec2": _list_ec2,
        "rds": _list_rds,
        "s3": _list_s3,
        "volume": _list_volume,
    }
    
    rows = dispatch[args.type](want_pairs, missing_keys)
    
    # Print results
    tag_filter_str = ", ".join(args.tag) if args.tag else "(no filter)"
    print(f"{args.type.upper()} {tag_filter_str} - {len(rows)} found:")
    print("-" * 80)
    for row in rows:
        rid, spec, state, tags = row
        tags_str = ", ".join(f"{k}={v}" for k, v in sorted(tags.items()))
        print(f"  {rid:<30} {spec:<20} {state:<15} {tags_str}")

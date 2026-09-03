import os
import boto3

_dynamodb_resource = None
_s3_client = None


def get_dynamodb_resource():
    global _dynamodb_resource
    if _dynamodb_resource is None:
        region = os.environ.get("AWS_REGION", "ap-southeast-2")
        _dynamodb_resource = boto3.resource("dynamodb", region_name=region)
    return _dynamodb_resource


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        region = os.environ.get("AWS_REGION", "ap-southeast-2")
        _s3_client = boto3.client("s3", region_name=region)
    return _s3_client

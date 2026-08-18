"""S3-compatible object storage via boto3 (MinIO, AWS S3, etc.)."""
import os
import json
import uuid
from loguru import logger
from app.core.config import settings

try:
    import boto3
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    boto3 = None
    Config = None
    HAS_BOTO3 = False


def _bucket() -> str:
    return os.getenv("S3_BUCKET") or settings.S3_BUCKET or "erha-knowledge-assets"


def _get_client():
    """
    Creates boto3 S3 client with automatic fallback across docker network (http://minio:9000)
    and host localhost (http://localhost:9000).
    """
    endpoints = []
    env_endpoint = os.getenv("S3_ENDPOINT_URL") or settings.S3_ENDPOINT_URL
    if env_endpoint:
        endpoints.append(env_endpoint)
    # Add standard docker and host fallbacks
    for ep in ["http://minio:9000", "http://localhost:9000", "http://127.0.0.1:9000"]:
        if ep not in endpoints:
            endpoints.append(ep)

    access_key = os.getenv("S3_ACCESS_KEY") or settings.S3_ACCESS_KEY or "minioadmin"
    secret_key = os.getenv("S3_SECRET_KEY") or settings.S3_SECRET_KEY or "minioadmin"
    region = os.getenv("S3_REGION") or settings.S3_REGION or "us-east-1"
    use_path_style = settings.S3_USE_PATH_STYLE if hasattr(settings, "S3_USE_PATH_STYLE") else True

    for endpoint_url in endpoints:
        try:
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path" if use_path_style else "auto"},
                    connect_timeout=3,
                    read_timeout=5,
                    retries={'max_attempts': 2}
                ),
                region_name=region,
            )
            # Test connectivity
            client.list_buckets()
            return client
        except Exception:
            continue

    # Fallback to primary configured endpoint
    primary_ep = endpoints[0] if endpoints else "http://localhost:9000"
    return boto3.client(
        "s3",
        endpoint_url=primary_ep,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if use_path_style else "auto"}
        ),
        region_name=region,
    )


def _ensure_bucket():
    """Ensures MinIO bucket exists and has a public read policy for images."""
    try:
        client = _get_client()
        bucket_name = _bucket()
        try:
            client.head_bucket(Bucket=bucket_name)
        except Exception:
            client.create_bucket(Bucket=bucket_name)
            logger.info(f"Created MinIO bucket: '{bucket_name}'")

        # Set public read policy so browser/frontend can view images directly
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"]
                }
            ]
        }
        try:
            client.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(policy))
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Could not connect or ensure MinIO bucket '{_bucket()}': {e}")


def _format_browser_url(raw_url: str, s3_key: str) -> str:
    """Ensures image URL is accessible by the user's browser (converts docker 'minio:9000' to 'localhost:9000')."""
    if not raw_url:
        bucket_name = _bucket()
        return f"http://localhost:9000/{bucket_name}/{s3_key}"
    if "minio:9000" in raw_url:
        return raw_url.replace("minio:9000", "localhost:9000")
    return raw_url


def upload_image(content: bytes, filename: str, content_type: str = "image/png") -> dict:
    """
    Synchronously uploads image binary content to MinIO bucket and returns s3_key & browser-accessible image_url.
    """
    s3_key = f"images/{uuid.uuid4().hex}_{filename}"
    bucket_name = _bucket()

    if not HAS_BOTO3:
        logger.warning(f"boto3 package not installed. Returning fallback image info for '{filename}'.")
        return {
            "s3_key": s3_key,
            "image_url": f"http://localhost:9000/{bucket_name}/{s3_key}",
            "size": len(content),
            "status": "fallback"
        }
    try:
        _ensure_bucket()
        client = _get_client()

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=content,
            **extra_args
        )

        browser_url = f"http://localhost:9000/{bucket_name}/{s3_key}"

        logger.info(f"✅ Successfully uploaded image '{filename}' to MinIO -> {browser_url}")
        return {
            "s3_key": s3_key,
            "image_url": browser_url,
            "size": len(content),
            "status": "success"
        }
    except Exception as e:
        logger.warning(f"MinIO upload failed for '{filename}': {e}. Returning fallback URL.")
        fallback_url = f"http://localhost:9000/{bucket_name}/{s3_key}"
        return {
            "s3_key": s3_key,
            "image_url": fallback_url,
            "size": len(content),
            "status": "fallback"
        }


def get_presigned_url(s3_key: str, expires: int = 604800) -> str:
    """Generates presigned GET URL for an existing S3 object key."""
    try:
        client = _get_client()
        raw_url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": s3_key},
            ExpiresIn=expires
        )
        return _format_browser_url(raw_url, s3_key)
    except Exception as e:
        logger.warning(f"Failed to generate presigned URL for key '{s3_key}': {e}")
        return f"http://localhost:9000/{_bucket()}/{s3_key}"


def delete_image(s3_key: str) -> None:
    """Deletes an image object from MinIO bucket."""
    try:
        client = _get_client()
        client.delete_object(Bucket=_bucket(), Key=s3_key)
        logger.info(f"Deleted image key '{s3_key}' from MinIO")
    except Exception as e:
        logger.warning(f"Failed to delete image key '{s3_key}' from MinIO: {e}")

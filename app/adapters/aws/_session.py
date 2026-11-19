"""Phiên boto3: IAM role (mặc định, ECS task role) hoặc access key nhập trên UI."""

from __future__ import annotations


def session(region: str, cfg: dict | None = None, secrets: dict | None = None):
    import boto3

    cfg, secrets = cfg or {}, secrets or {}
    if cfg.get("auth") == "access_key" and secrets.get("access_key_id"):
        return boto3.Session(
            aws_access_key_id=secrets["access_key_id"],
            aws_secret_access_key=secrets.get("secret_access_key", ""),
            region_name=region,
        )
    return boto3.Session(region_name=region)

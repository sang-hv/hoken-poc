"""SecretStore trên AWS Secrets Manager (tên secret = AWS_SECRETS_PREFIX + name)."""

from __future__ import annotations

from app.adapters.aws._session import session


class AwsSecrets:
    def __init__(self, prefix: str, region: str):
        self.prefix = prefix
        self.sm = session(region).client("secretsmanager")

    def set(self, name: str, value: str) -> None:
        sid = self.prefix + name
        try:
            self.sm.put_secret_value(SecretId=sid, SecretString=value)
        except self.sm.exceptions.ResourceNotFoundException:
            self.sm.create_secret(Name=sid, SecretString=value)

    def get(self, name: str) -> str | None:
        try:
            return self.sm.get_secret_value(SecretId=self.prefix + name)["SecretString"]
        except self.sm.exceptions.ResourceNotFoundException:
            return None

    def delete(self, name: str) -> None:
        try:
            self.sm.delete_secret(SecretId=self.prefix + name, RecoveryWindowInDays=7)
        except self.sm.exceptions.ResourceNotFoundException:
            pass

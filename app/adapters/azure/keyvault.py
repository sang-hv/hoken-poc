"""SecretStore trên Azure Key Vault (Managed Identity cần quyền Key Vault Secrets Officer)."""

from __future__ import annotations


class KeyVaultSecrets:
    def __init__(self, vault_url: str):
        from azure.keyvault.secrets import SecretClient

        from app.adapters.azure._auth import credential

        self.c = SecretClient(vault_url, credential())

    def set(self, name: str, value: str) -> None:
        self.c.set_secret(name, value)

    def get(self, name: str) -> str | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self.c.get_secret(name).value
        except ResourceNotFoundError:
            return None

    def delete(self, name: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self.c.begin_delete_secret(name)
        except ResourceNotFoundError:
            pass

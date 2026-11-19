"""BlobStore trên Azure Blob Storage."""

from __future__ import annotations


class AzureBlob:
    def __init__(self, account_url: str, container: str, connection_string: str = ""):
        from azure.storage.blob import BlobServiceClient

        from app.adapters.azure._auth import credential

        if connection_string:
            svc = BlobServiceClient.from_connection_string(connection_string)
        else:
            svc = BlobServiceClient(account_url, credential=credential())
        self.c = svc.get_container_client(container)
        if not self.c.exists():
            self.c.create_container()

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        from azure.storage.blob import ContentSettings

        self.c.upload_blob(key, data, overwrite=True, content_settings=ContentSettings(content_type=content_type))

    def get(self, key: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self.c.download_blob(key).readall()
        except ResourceNotFoundError as e:
            raise FileNotFoundError(key) from e

    def exists(self, key: str) -> bool:
        return self.c.get_blob_client(key).exists()

    def delete_prefix(self, prefix: str) -> None:
        names = [b.name for b in self.c.list_blobs(name_starts_with=prefix)]
        for i in range(0, len(names), 250):
            self.c.delete_blobs(*names[i : i + 250])

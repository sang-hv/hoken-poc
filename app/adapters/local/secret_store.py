"""SecretStore local: mã hoá AES-GCM, lưu trong DocStore. Master key lấy từ SECRET_MASTER_KEY (env)."""

from __future__ import annotations

from app.core.util import decrypt, encrypt, now_iso
from app.domain.models import GLOBAL


class LocalSecretStore:
    COLL = "secrets"

    def __init__(self, store, master_key: str):
        self.store = store
        self.master = master_key

    def set(self, name: str, value: str) -> None:
        self.store.put(self.COLL, GLOBAL, name, {"value": encrypt(self.master, value), "at": now_iso()})

    def get(self, name: str) -> str | None:
        doc = self.store.get(self.COLL, GLOBAL, name)
        return decrypt(self.master, doc["value"]) if doc else None

    def delete(self, name: str) -> None:
        self.store.delete(self.COLL, GLOBAL, name)

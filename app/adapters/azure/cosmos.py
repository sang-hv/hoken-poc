"""DocStore trên Azure Cosmos DB (NoSQL). Một container `docs`, partition key `/pk` = "{coll}|{pk}"."""

from __future__ import annotations

import re
from typing import Any

_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CosmosStore:
    def __init__(self, endpoint: str, database: str, key: str = "", container: str = "docs"):
        from azure.cosmos import CosmosClient, PartitionKey

        from app.adapters.azure._auth import credential

        client = CosmosClient(endpoint, credential=key or credential())
        db = client.create_database_if_not_exists(database)
        self.c = db.create_container_if_not_exists(id=container, partition_key=PartitionKey(path="/pk"))

    @staticmethod
    def _pk(coll: str, pk: str) -> str:
        return f"{coll}|{pk}"

    def get(self, coll: str, pk: str, id: str) -> dict | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self.c.read_item(id, partition_key=self._pk(coll, pk))["data"]
        except CosmosResourceNotFoundError:
            return None

    def put(self, coll: str, pk: str, id: str, doc: dict) -> None:
        self.c.upsert_item({"id": id, "pk": self._pk(coll, pk), "data": doc})

    def create(self, coll: str, pk: str, id: str, doc: dict) -> bool:
        from azure.cosmos.exceptions import CosmosResourceExistsError

        try:
            self.c.create_item({"id": id, "pk": self._pk(coll, pk), "data": doc})
            return True
        except CosmosResourceExistsError:
            return False

    def delete(self, coll: str, pk: str, id: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            self.c.delete_item(id, partition_key=self._pk(coll, pk))
        except CosmosResourceNotFoundError:
            pass

    def delete_partition(self, coll: str, pk: str) -> None:
        key = self._pk(coll, pk)
        for it in list(
            self.c.query_items(
                "SELECT c.id FROM c WHERE c.pk=@pk", parameters=[{"name": "@pk", "value": key}], partition_key=key
            )
        ):
            self.c.delete_item(it["id"], partition_key=key)

    def query(
        self,
        coll: str,
        pk: str,
        eq: dict[str, Any] | None = None,
        id_gt: str | None = None,
        limit: int = 1000,
        desc: bool = False,
    ) -> list[dict]:
        key = self._pk(coll, pk)
        sql = f"SELECT TOP {int(limit)} c.data FROM c WHERE c.pk=@pk"
        params: list[dict] = [{"name": "@pk", "value": key}]
        for i, (k, v) in enumerate((eq or {}).items()):
            if not _FIELD.match(k):
                raise ValueError(f"tên trường không hợp lệ: {k}")
            sql += f' AND c.data["{k}"] = @v{i}'
            params.append({"name": f"@v{i}", "value": v})
        if id_gt:
            sql += " AND c.id > @after"
            params.append({"name": "@after", "value": id_gt})
        sql += f" ORDER BY c.id {'DESC' if desc else 'ASC'}"
        return [it["data"] for it in self.c.query_items(sql, parameters=params, partition_key=key)]

    def health(self) -> None:
        self.c.read()

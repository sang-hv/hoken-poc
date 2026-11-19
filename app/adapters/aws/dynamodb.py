"""DocStore trên DynamoDB. Một bảng: pk = "{coll}#{pk}", sk = id.

Document lưu dạng JSON trong thuộc tính `data` (tránh chuyển float↔Decimal). Các trường vô hướng ở
cấp đầu (chuỗi, số nguyên, bool) được chép ra thuộc tính `f_<tên>` để lọc `eq`.
"""

from __future__ import annotations

import json
from typing import Any

from app.adapters.aws._session import session


class DynamoStore:
    def __init__(self, table: str, region: str):
        ddb = session(region).resource("dynamodb")
        self.t = ddb.Table(table)
        try:
            self.t.load()
        except ddb.meta.client.exceptions.ResourceNotFoundException:
            self.t = ddb.create_table(
                TableName=table,
                BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ],
            )
            self.t.wait_until_exists()

    @staticmethod
    def _item(coll: str, pk: str, id: str, doc: dict) -> dict:
        item: dict[str, Any] = {"pk": f"{coll}#{pk}", "sk": id, "data": json.dumps(doc, ensure_ascii=False)}
        for k, v in doc.items():
            if isinstance(v, bool | str) or (isinstance(v, int) and not isinstance(v, bool)):
                item[f"f_{k}"] = v
        return item

    def get(self, coll: str, pk: str, id: str) -> dict | None:
        it = self.t.get_item(Key={"pk": f"{coll}#{pk}", "sk": id}).get("Item")
        return json.loads(it["data"]) if it else None

    def put(self, coll: str, pk: str, id: str, doc: dict) -> None:
        self.t.put_item(Item=self._item(coll, pk, id, doc))

    def create(self, coll: str, pk: str, id: str, doc: dict) -> bool:
        try:
            self.t.put_item(Item=self._item(coll, pk, id, doc), ConditionExpression="attribute_not_exists(pk)")
            return True
        except self.t.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def delete(self, coll: str, pk: str, id: str) -> None:
        self.t.delete_item(Key={"pk": f"{coll}#{pk}", "sk": id})

    def delete_partition(self, coll: str, pk: str) -> None:
        with self.t.batch_writer() as bw:
            for it in self._iter(f"{coll}#{pk}", None, None, False, projection=True):
                bw.delete_item(Key={"pk": it["pk"], "sk": it["sk"]})

    def _iter(self, key: str, eq: dict | None, id_gt: str | None, desc: bool, projection: bool = False):
        from boto3.dynamodb.conditions import Attr, Key

        cond = Key("pk").eq(key) & Key("sk").gt(id_gt) if id_gt else Key("pk").eq(key)
        kwargs: dict[str, Any] = {"KeyConditionExpression": cond, "ScanIndexForward": not desc}
        if eq:
            f = None
            for k, v in eq.items():
                c = Attr(f"f_{k}").eq(v)
                f = c if f is None else f & c
            kwargs["FilterExpression"] = f
        if projection:
            kwargs["ProjectionExpression"] = "pk, sk"
        while True:
            res = self.t.query(**kwargs)
            yield from res.get("Items", [])
            if "LastEvaluatedKey" not in res:
                return
            kwargs["ExclusiveStartKey"] = res["LastEvaluatedKey"]

    def query(
        self,
        coll: str,
        pk: str,
        eq: dict[str, Any] | None = None,
        id_gt: str | None = None,
        limit: int = 1000,
        desc: bool = False,
    ) -> list[dict]:
        out = []
        for it in self._iter(f"{coll}#{pk}", eq, id_gt, desc):
            out.append(json.loads(it["data"]))
            if len(out) >= limit:
                break
        return out

    def health(self) -> None:
        self.t.reload()

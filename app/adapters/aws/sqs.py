"""Hàng đợi trên Amazon SQS. URL hàng đợi = SQS_QUEUE_URL_PREFIX + tên (docling / ai / light)."""

from __future__ import annotations

import json

from app.adapters.aws._session import session
from app.ports import QueueMessage


class SqsQueue:
    def __init__(self, url_prefix: str, region: str):
        if not url_prefix:
            raise ValueError("SQS_QUEUE_URL_PREFIX bắt buộc khi QUEUE_TYPE=sqs")
        self.prefix = url_prefix
        self.sqs = session(region).client("sqs")

    def _url(self, queue: str) -> str:
        return f"{self.prefix}{queue}"

    def send(self, queue: str, body: dict, delay_s: int = 0) -> None:
        self.sqs.send_message(
            QueueUrl=self._url(queue), MessageBody=json.dumps(body), DelaySeconds=max(0, min(int(delay_s), 900))
        )

    def receive(self, queue: str, max_messages: int = 1, visibility_s: int = 900) -> list[QueueMessage]:
        res = self.sqs.receive_message(
            QueueUrl=self._url(queue),
            MaxNumberOfMessages=max(1, min(max_messages, 10)),
            VisibilityTimeout=min(int(visibility_s), 43200),
            WaitTimeSeconds=1,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        )
        return [
            QueueMessage(
                id=m["MessageId"],
                body=json.loads(m["Body"]),
                receipt=m["ReceiptHandle"],
                dequeue_count=int(m.get("Attributes", {}).get("ApproximateReceiveCount", 1)),
            )
            for m in res.get("Messages", [])
        ]

    def ack(self, queue: str, msg: QueueMessage) -> None:
        self.sqs.delete_message(QueueUrl=self._url(queue), ReceiptHandle=msg.receipt)

    def release(self, queue: str, msg: QueueMessage, delay_s: int = 0) -> None:
        self.sqs.change_message_visibility(
            QueueUrl=self._url(queue), ReceiptHandle=msg.receipt, VisibilityTimeout=max(0, min(int(delay_s), 43200))
        )

    def depth(self, queue: str) -> int:
        a = self.sqs.get_queue_attributes(
            QueueUrl=self._url(queue),
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )["Attributes"]
        return sum(int(v) for v in a.values())

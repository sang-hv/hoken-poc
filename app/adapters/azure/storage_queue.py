"""Hàng đợi trên Azure Storage Queue (Container Apps Jobs scale theo độ dài hàng đợi bằng KEDA)."""

from __future__ import annotations

import json

from app.ports import QueueMessage


class AzureStorageQueue:
    def __init__(self, account_url: str, connection_string: str = "", prefix: str = "hoken"):
        from azure.storage.queue import QueueServiceClient

        from app.adapters.azure._auth import credential

        if connection_string:
            self.svc = QueueServiceClient.from_connection_string(connection_string)
        else:
            self.svc = QueueServiceClient(account_url, credential=credential())
        self.prefix = prefix.lower()
        self._clients: dict[str, object] = {}

    def _q(self, queue: str):
        if queue not in self._clients:
            from azure.core.exceptions import ResourceExistsError

            client = self.svc.get_queue_client(f"{self.prefix}-{queue}")
            try:
                client.create_queue()
            except ResourceExistsError:
                pass
            self._clients[queue] = client
        return self._clients[queue]

    def send(self, queue: str, body: dict, delay_s: int = 0) -> None:
        self._q(queue).send_message(json.dumps(body), visibility_timeout=delay_s or None)

    def receive(self, queue: str, max_messages: int = 1, visibility_s: int = 900) -> list[QueueMessage]:
        out = []
        pages = self._q(queue).receive_messages(
            messages_per_page=max_messages, visibility_timeout=visibility_s, max_messages=max_messages
        )
        for m in pages:
            out.append(
                QueueMessage(
                    id=m.id,
                    body=json.loads(m.content),
                    receipt=(m.id, m.pop_receipt),
                    dequeue_count=m.dequeue_count or 1,
                )
            )
        return out

    def ack(self, queue: str, msg: QueueMessage) -> None:
        mid, receipt = msg.receipt
        self._q(queue).delete_message(mid, receipt)

    def release(self, queue: str, msg: QueueMessage, delay_s: int = 0) -> None:
        mid, receipt = msg.receipt
        self._q(queue).update_message(mid, receipt, visibility_timeout=delay_s)

    def depth(self, queue: str) -> int:
        return int(self._q(queue).get_queue_properties().approximate_message_count or 0)

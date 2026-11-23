"""Gom các adapter + service thành một container dùng chung cho API, worker và CLI."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.adapters.registry import make_blob, make_queue, make_store
from app.core.settings import BootstrapSettings, get_settings
from app.ports import BlobStore, Queue
from app.services.config_service import ConfigService
from app.services.repo import Repo


@dataclass
class Container:
    settings: BootstrapSettings
    repo: Repo
    queue: Queue
    blob: BlobStore
    config: ConfigService

    @classmethod
    def build(cls, settings: BootstrapSettings, *, store=None, queue=None, blob=None, env=None) -> Container:
        """`env`: nguồn biến môi trường cho lớp 2 (mặc định os.environ; test truyền dict)."""
        store = store or make_store(settings)
        repo = Repo(store)
        return cls(
            settings=settings,
            repo=repo,
            queue=queue or make_queue(settings, store),
            blob=blob or make_blob(settings),
            config=ConfigService(repo, settings.app_env, env),
        )


_override: Container | None = None


def set_container(c: Container | None) -> None:
    """Dùng trong test: thay container mặc định."""
    global _override
    _override = c
    _default.cache_clear()


@lru_cache(maxsize=1)
def _default() -> Container:
    return Container.build(get_settings())


def get_container() -> Container:
    return _override or _default()

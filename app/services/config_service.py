"""Lớp 2 (dịch vụ AI & search, xác thực SSO) và lớp 4 (tuỳ chọn pipeline).

- Lớp 2 đọc từ **biến môi trường**, giống hệt lớp 1: dev đặt trong `.env`, prod do IaC đặt (secret lấy từ
  Key Vault / Secrets Manager qua tham chiếu secret của Container Apps / ECS). Admin UI chỉ xem + thử kết nối.
  Tên biến: `<COMPONENT>_TYPE` chọn adapter, mỗi trường là `<COMPONENT>_<FIELD>` (vd `LLM_TYPE=azure`,
  `LLM_ENDPOINT`, `LLM_DEPLOYMENT`, `LLM_API_KEY`). SSO: `AUTH_<GOOGLE|ENTRA>_<FIELD>`.
- Lớp 4 lưu DB (collection `settings`), có phiên bản + lịch sử; Admin sửa trên UI.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping
from typing import Any

from app.adapters.registry import COMPONENTS, AdapterSpec, find_spec
from app.core.util import now_iso
from app.domain.options import PipelineOptions, editable_dump, options_from
from app.services.repo import Repo

log = logging.getLogger(__name__)


class NotConfigured(RuntimeError):
    """Thiếu / sai cấu hình. `code`: type_missing | type_unsupported | required | not_number | invalid;
    `env`: tên biến môi trường liên quan (chỉ tên, không có giá trị)."""

    def __init__(self, component: str, code: str = "type_missing", env: str = ""):
        super().__init__(f"{component} chưa được cấu hình ({code} {env})".strip())
        self.component = component
        self.code = code
        self.env = env

    @property
    def reason(self) -> str:
        return f"{self.code}:{self.env}"

    def public(self) -> dict:
        return {"code": self.code, "env": self.env}


ENV_PREFIX = {"llm": "LLM", "embedding": "EMBEDDING", "cu": "CU", "search": "SEARCH"}


def env_name(component: str, field: str) -> str:
    return f"{ENV_PREFIX[component]}_{field.upper()}"


AUTH_PROVIDERS = {
    "google": ["client_id", "client_secret", "allowed_domains", "default_role"],
    "entra": ["tenant_id", "client_id", "client_secret", "allowed_domains", "default_role"],
}
AUTH_SECRETS = {"client_secret"}


def auth_env_name(provider: str, field: str) -> str:
    return f"AUTH_{provider.upper()}_{field.upper()}"


def _as_bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


class ConfigService:
    def __init__(self, repo: Repo, app_env: str, env: Mapping[str, str] | None = None):
        self.repo = repo
        self.app_env = app_env
        self.env = dict(os.environ if env is None else env)
        self._cache: dict[str, Any] = {}
        self._lock = threading.Lock()
        self.overrides: dict[str, Any] = {}  # chỉ dùng cho test: component → adapter

    def _get(self, name: str) -> str:
        return (self.env.get(name) or "").strip()

    # ================================================================ lớp 2: provider (từ env)
    def _resolve(self, component: str) -> tuple[AdapterSpec, dict, dict]:
        """(spec, config, secrets) của component theo env. Ném NotConfigured nếu thiếu / sai."""
        type_ = self._get(env_name(component, "type")).lower()
        if not type_:
            raise NotConfigured(component, "type_missing", env_name(component, "type"))
        try:
            spec = find_spec(component, type_, self.app_env)
        except KeyError as e:
            raise NotConfigured(component, "type_unsupported", env_name(component, "type")) from e
        config: dict[str, Any] = {}
        secrets: dict[str, str] = {}
        for f in spec.fields:
            raw = self._get(env_name(component, f.name))
            if f.kind == "secret":
                if raw:
                    secrets[f.name] = raw
                continue
            v: Any = raw if raw else f.default
            if isinstance(v, str) and "<" in v and ">" in v:  # giá trị mẫu kiểu https://<resource>...
                v = None
            if v in (None, ""):
                continue
            if f.kind == "number" and isinstance(v, str):
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError as e:
                    raise NotConfigured(component, "not_number", env_name(component, f.name)) from e
            if f.kind == "bool" and isinstance(v, str):
                v = _as_bool(v)
            if f.kind == "select" and v not in f.options:
                raise NotConfigured(component, "invalid", env_name(component, f.name))
            config[f.name] = v
        for f in spec.fields:
            shown = all(config.get(k) == val for k, val in f.show_if.items())
            present = f.name in (secrets if f.kind == "secret" else config)
            # secret gắn với một chế độ auth (show_if) là bắt buộc khi chế độ đó được chọn
            needed = f.required or (f.kind == "secret" and bool(f.show_if))
            if needed and shown and not present:
                raise NotConfigured(component, "required", env_name(component, f.name))
        return spec, config, secrets

    def providers_public(self) -> dict:
        """Cho Admin UI (chỉ xem): adapter đang chọn, giá trị thường, secret chỉ có cờ "đã đặt"."""
        out: dict[str, dict] = {}
        for c in COMPONENTS:
            type_ = self._get(env_name(c, "type")).lower()
            item: dict[str, Any] = {"type_env": env_name(c, "type"), "type": type_ or None, "fields": []}
            try:
                spec, config, secrets = self._resolve(c)
                item["service"] = spec.service
                item["ok"] = True
            except NotConfigured as e:
                item["ok"] = False
                item["error"] = e.public()
                try:
                    spec = find_spec(c, type_, self.app_env) if type_ else None
                except KeyError:
                    spec = None
                config, secrets = {}, {}
                if spec:
                    item["service"] = spec.service
            if spec:
                for f in spec.fields:
                    if f.show_if and not all(
                        (config.get(k) or self._get(env_name(c, k))) == val for k, val in f.show_if.items()
                    ):
                        continue
                    row: dict[str, Any] = {"name": f.name, "env": env_name(c, f.name), "kind": f.kind}
                    if f.kind == "secret":
                        row["set"] = f.name in secrets or bool(self._get(env_name(c, f.name)))
                    else:
                        v = config.get(f.name, self._get(env_name(c, f.name)) or None)
                        row["value"] = v
                        row["default"] = not self._get(env_name(c, f.name)) and v is not None
                    item["fields"].append(row)
            out[c] = item
        return {"app_env": self.app_env, "components": out}

    def build(self, component: str):
        """Dựng adapter mới từ env (để thử kết nối)."""
        spec, config, secrets = self._resolve(component)
        return spec.load(config, secrets)

    def adapter(self, component: str):
        """Adapter đang dùng cho component (env không đổi khi đang chạy → dựng một lần)."""
        if component in self.overrides:
            return self.overrides[component]
        with self._lock:
            if component not in self._cache:
                try:
                    self._cache[component] = self.build(component)
                except NotConfigured as e:
                    log.warning("provider_not_configured component=%s reason=%s", component, e.reason)
                    raise
            return self._cache[component]

    def is_configured(self, component: str) -> bool:
        if component in self.overrides:
            return True
        try:
            self._resolve(component)
        except NotConfigured:
            return False
        return True

    # ================================================================ lớp 4: tuỳ chọn pipeline
    def pipeline(self) -> tuple[int, PipelineOptions]:
        d = self.repo.get_setting("pipeline")
        if not d:
            return 0, PipelineOptions()
        return int(d["version"]), options_from(d["options"])

    def pipeline_at(self, version: int) -> PipelineOptions:
        """Tuỳ chọn ở đúng phiên bản job đã ghi lại (để chạy lại cho kết quả giống)."""
        cur_v, cur = self.pipeline()
        if version in (0, cur_v):
            return cur if version == cur_v else PipelineOptions()
        d = self.repo.s.get("settings_history", "pipeline", f"{version:08d}")
        return options_from(d["options"]) if d else cur

    def update_pipeline(self, options: dict, actor: str) -> tuple[int, PipelineOptions]:
        """Chỉ nhận các mục trong EDITABLE (khoá khác bỏ qua); mục không gửi giữ giá trị hiện tại."""
        v, cur = self.pipeline()
        merged = editable_dump(cur)
        for sec, vals in (options or {}).items():
            if sec in merged and isinstance(vals, dict):
                merged[sec].update({k: x for k, x in vals.items() if k in merged[sec]})
        opts = options_from(merged)
        v += 1
        doc = {"version": v, "options": editable_dump(opts), "updated_by": actor, "updated_at": now_iso()}
        self.repo.put_setting("pipeline", doc)
        self.repo.s.put("settings_history", "pipeline", f"{v:08d}", doc)
        self.repo.audit(actor, "settings.pipeline.update", "pipeline", version=v)
        return v, opts

    # ================================================================ xác thực SSO (từ env)
    def auth(self) -> dict:
        """Bật khi có client_id + client_secret. Không trả secret, chỉ cờ `secrets_set`."""
        out = {}
        for name, fields in AUTH_PROVIDERS.items():
            vals = {f: self._get(auth_env_name(name, f)) for f in fields}
            role = vals.get("default_role") or "viewer"
            out[name] = {
                "enabled": bool(vals["client_id"] and vals["client_secret"]),
                **{f: v for f, v in vals.items() if f not in AUTH_SECRETS},
                "default_role": role if role in ("viewer", "reviewer") else "viewer",
                "secrets_set": [f for f in AUTH_SECRETS if vals.get(f)],
                "env": {f: auth_env_name(name, f) for f in fields},
            }
        return out

    def auth_secret(self, name: str) -> str | None:
        return self._get(auth_env_name(name, "client_secret")) or None

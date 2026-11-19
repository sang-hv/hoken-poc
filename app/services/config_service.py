"""Lớp 2 (dịch vụ AI & search, xác thực SSO) và lớp 4 (tuỳ chọn pipeline).

- Giá trị thường lưu trong DB (collection `settings`), có phiên bản + lịch sử.
- Trường secret ghi vào SecretStore (Key Vault / Secrets Manager / local mã hoá). DB chỉ giữ cờ "đã đặt".
"""

from __future__ import annotations

import threading
from typing import Any

from app.adapters.registry import COMPONENTS, AdapterSpec, find_spec, specs_for
from app.core.util import now_iso
from app.domain.options import PipelineOptions
from app.services.repo import Repo


class NotConfigured(RuntimeError):
    def __init__(self, component: str):
        super().__init__(f"{component} chưa được cấu hình")
        self.component = component


def secret_name(scope: str, field: str) -> str:
    return f"hoken-{scope}-{field}".replace("_", "-").lower()


AUTH_PROVIDERS = {
    "google": {"fields": ["client_id", "allowed_domains", "default_role"], "secrets": ["client_secret"]},
    "entra": {"fields": ["tenant_id", "client_id", "allowed_domains", "default_role"], "secrets": ["client_secret"]},
}


class ConfigService:
    def __init__(self, repo: Repo, secrets, app_env: str):
        self.repo = repo
        self.secrets = secrets
        self.app_env = app_env
        self._cache: dict[tuple[str, int], Any] = {}
        self._lock = threading.Lock()
        self.overrides: dict[str, Any] = {}  # chỉ dùng cho test: component → adapter

    # ================================================================ lớp 2: provider
    def providers(self) -> dict:
        return self.repo.get_setting("providers") or {"version": 0, "components": {}}

    def catalog(self) -> dict[str, list[dict]]:
        return {c: [s.public() for s in specs_for(c, self.app_env)] for c in COMPONENTS}

    def providers_public(self) -> dict:
        p = self.providers()
        return {
            "version": p["version"],
            "updated_at": p.get("updated_at", ""),
            "updated_by": p.get("updated_by", ""),
            "components": p["components"],
            "catalog": self.catalog(),
        }

    def _validate(
        self, spec: AdapterSpec, config: dict, secrets: dict[str, str | None], existing_secrets: set[str]
    ) -> dict:
        clean: dict[str, Any] = {}
        for f in spec.fields:
            if f.kind == "secret":
                continue
            v = config.get(f.name, f.default)
            if isinstance(v, str) and "<" in v and ">" in v:  # giá trị mẫu kiểu https://<resource>...
                v = None
            if f.kind == "number" and v not in (None, ""):
                v = float(v) if "." in str(v) else int(v)
            if f.kind == "bool":
                v = bool(v)
            if f.kind == "select" and v not in f.options:
                raise ValueError(f"{f.name}: giá trị không hợp lệ")
            if v in (None, ""):
                if f.required:
                    raise ValueError(f"{f.name}: bắt buộc")
                continue
            clean[f.name] = v
        for f in spec.fields:
            if f.kind == "secret" and f.required and not (secrets.get(f.name) or f.name in existing_secrets):
                raise ValueError(f"{f.name}: bắt buộc")
        return clean

    def update_provider(
        self, component: str, type_: str, config: dict, secrets: dict[str, str | None], actor: str
    ) -> dict:
        spec = find_spec(component, type_, self.app_env)
        p = self.providers()
        current = p["components"].get(component, {})
        same_type = current.get("type") == type_
        existing = set(current.get("secrets_set", [])) if same_type else set()
        clean = self._validate(spec, config, secrets, existing)
        secret_fields = {f.name for f in spec.fields if f.kind == "secret"}
        for name in secret_fields:
            value = secrets.get(name)
            sname = secret_name(f"{component}-{type_}", name)
            if value:
                self.secrets.set(sname, value)
                existing.add(name)
            elif value == "" and name in existing:  # chuỗi rỗng = xoá
                self.secrets.delete(sname)
                existing.discard(name)
        p["components"][component] = {"type": type_, "config": clean, "secrets_set": sorted(existing)}
        p["version"] = int(p.get("version", 0)) + 1
        p["updated_at"], p["updated_by"] = now_iso(), actor
        self.repo.put_setting("providers", p)
        self.repo.add_setting_history(
            "providers",
            {"version": p["version"], "component": component, "type": type_, "by": actor, "at": p["updated_at"]},
        )
        self.repo.audit(actor, "settings.provider.update", component, type=type_, version=p["version"])
        return p

    def _secrets_for(self, component: str, type_: str, names: list[str]) -> dict[str, str]:
        out = {}
        for n in names:
            v = self.secrets.get(secret_name(f"{component}-{type_}", n))
            if v:
                out[n] = v
        return out

    def build(self, component: str, type_: str, config: dict, secrets: dict[str, str | None] | None = None):
        spec = find_spec(component, type_, self.app_env)
        p = self.providers()["components"].get(component, {})
        stored = self._secrets_for(component, type_, p.get("secrets_set", [])) if p.get("type") == type_ else {}
        merged = {**stored, **{k: v for k, v in (secrets or {}).items() if v}}
        clean = self._validate(spec, config, merged, set(merged))
        return spec.load(clean, merged)

    def adapter(self, component: str):
        """Adapter đang dùng cho component (cache theo phiên bản cấu hình)."""
        if component in self.overrides:
            return self.overrides[component]
        p = self.providers()
        cur = p["components"].get(component)
        if not cur:
            raise NotConfigured(component)
        key = (component, int(p["version"]))
        with self._lock:
            if key not in self._cache:
                spec = find_spec(component, cur["type"], self.app_env)
                secrets = self._secrets_for(component, cur["type"], cur.get("secrets_set", []))
                self._cache = {k: v for k, v in self._cache.items() if k[0] != component}
                self._cache[key] = spec.load(cur["config"], secrets)
            return self._cache[key]

    def is_configured(self, component: str) -> bool:
        return component in self.overrides or component in self.providers()["components"]

    # ================================================================ lớp 4: tuỳ chọn pipeline
    def pipeline(self) -> tuple[int, PipelineOptions]:
        d = self.repo.get_setting("pipeline")
        if not d:
            return 0, PipelineOptions()
        return int(d["version"]), PipelineOptions(**d["options"])

    def pipeline_at(self, version: int) -> PipelineOptions:
        """Tuỳ chọn ở đúng phiên bản job đã ghi lại (để chạy lại cho kết quả giống)."""
        cur_v, cur = self.pipeline()
        if version in (0, cur_v):
            return cur if version == cur_v else PipelineOptions()
        d = self.repo.s.get("settings_history", "pipeline", f"{version:08d}")
        return PipelineOptions(**d["options"]) if d else cur

    def update_pipeline(self, options: dict, actor: str) -> tuple[int, PipelineOptions]:
        opts = PipelineOptions(**options)
        v, _ = self.pipeline()
        v += 1
        doc = {"version": v, "options": opts.model_dump(mode="json"), "updated_by": actor, "updated_at": now_iso()}
        self.repo.put_setting("pipeline", doc)
        self.repo.s.put("settings_history", "pipeline", f"{v:08d}", doc)
        self.repo.audit(actor, "settings.pipeline.update", "pipeline", version=v)
        return v, opts

    # ================================================================ xác thực SSO
    def auth(self) -> dict:
        d = self.repo.get_setting("auth") or {}
        out = {}
        for name, meta in AUTH_PROVIDERS.items():
            cur = d.get(name, {})
            out[name] = {
                "enabled": bool(cur.get("enabled")),
                **{f: cur.get(f, "") for f in meta["fields"]},
                "secrets_set": cur.get("secrets_set", []),
            }
        return out

    def update_auth(self, name: str, values: dict, actor: str) -> dict:
        if name not in AUTH_PROVIDERS:
            raise KeyError(name)
        meta = AUTH_PROVIDERS[name]
        d = self.repo.get_setting("auth") or {}
        cur = d.get(name, {})
        secrets_set = set(cur.get("secrets_set", []))
        for s in meta["secrets"]:
            v = values.get(s)
            if v:
                self.secrets.set(secret_name(f"auth-{name}", s), v)
                secrets_set.add(s)
        role = values.get("default_role") or "viewer"
        if role not in ("viewer", "reviewer"):
            raise ValueError("default_role chỉ được là viewer hoặc reviewer")
        d[name] = {
            "enabled": bool(values.get("enabled")),
            **{f: values.get(f, "") for f in meta["fields"]},
            "default_role": role,
            "secrets_set": sorted(secrets_set),
        }
        if d[name]["enabled"] and not (d[name]["client_id"] and "client_secret" in secrets_set):
            raise ValueError("Cần client_id và client_secret để bật")
        self.repo.put_setting("auth", d)
        self.repo.audit(actor, "settings.auth.update", name, enabled=d[name]["enabled"])
        return self.auth()

    def auth_secret(self, name: str) -> str | None:
        return self.secrets.get(secret_name(f"auth-{name}", "client_secret"))

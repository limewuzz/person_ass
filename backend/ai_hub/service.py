"""AI Hub Service (Workflow 2): Schema-driven AI providers, secret isolation, capability profiles, and routing."""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import uuid
from typing import Any

import queries as Q

ADAPTER_KINDS = {"openai_compatible", "gemini_native", "mistral_native"}
PRICING_TIERS = {"free", "standard", "premium", "custom"}


@dataclass
class ModelSpecRec:
    id: str
    display_name: str
    provider_id: str
    adapter_kind: str
    capabilities: dict[str, Any]
    enabled: bool = False
    source_kind: str = "mock"


@dataclass
class AIProviderRec:
    id: str
    display_name: str
    adapter_kind: str
    endpoint_url: str
    credential_ref: str
    has_secret_configured: bool = False
    status: str = "UNAVAILABLE"
    enabled: bool = False
    models: list[ModelSpecRec] = field(default_factory=list)
    source_kind: str = "mock"


class AIHubService:
    """Manages AI providers, secret vault isolation (V2-EXT-001), capability matrices (V2-EXT-002), and routing."""

    def __init__(self, engine) -> None:
        self._lock = threading.RLock()
        self.engine = engine
        self.providers: dict[str, AIProviderRec] = {}
        self.models: dict[str, ModelSpecRec] = {}
        # Secrets are stored strictly in an isolated vault mapped by provider_id, NEVER serialized in outputs
        self._secret_vault: dict[str, str] = {}
        self.routing_policy: dict[str, Any] = {
            "default_model_id": "model.deepseek-flash",
            "fallback_model_id": "model.kimi-k3",
            "task_routes": {
                "code": "model.codex-cliproxy",
                "paper": "model.deepseek-flash",
                "vision": "model.gemini-2.5-pro",
            },
            "updated_at": Q._now(),
        }
        self._seed_baseline()

    def _seed_baseline(self) -> None:
        baseline_providers = [
            AIProviderRec(
                id="prov.mac-gateway-8765",
                display_name="Mac 8765 OpenAI-Compatible 网关（旧系统只读登记）",
                adapter_kind="openai_compatible",
                endpoint_url="http://127.0.0.1:8765/v1",
                credential_ref="vault://mac-8765-gateway-ref",
                has_secret_configured=False,
                status="UNKNOWN",
                enabled=False,
                source_kind="mock",
                models=[
                    ModelSpecRec(
                        id="model.deepseek-flash",
                        display_name="DeepSeek flash（经 Mac 8765 网关）",
                        provider_id="prov.mac-gateway-8765",
                        adapter_kind="openai_compatible",
                        capabilities={
                            "supports_text": True,
                            "supports_tools": True,
                            "supports_vision": False,
                            "supports_structured_output": True,
                            "context_window": 64000,
                            "rate_limit_rpm": 60,
                            "pricing_tier": "standard",
                        },
                        enabled=False,
                    ),
                    ModelSpecRec(
                        id="model.kimi-k3",
                        display_name="Kimi k3（网关备通道）",
                        provider_id="prov.mac-gateway-8765",
                        adapter_kind="openai_compatible",
                        capabilities={
                            "supports_text": True,
                            "supports_tools": True,
                            "supports_vision": False,
                            "supports_structured_output": False,
                            "context_window": 128000,
                            "rate_limit_rpm": 30,
                            "pricing_tier": "standard",
                        },
                        enabled=False,
                    ),
                ],
            ),
            AIProviderRec(
                id="prov.us-cliproxy",
                display_name="US cliproxy（Codex 系列通道）",
                adapter_kind="openai_compatible",
                endpoint_url="https://cliproxy.example.invalid/v1",
                credential_ref="vault://us-cliproxy-ref",
                has_secret_configured=False,
                status="UNKNOWN",
                enabled=False,
                source_kind="mock",
                models=[
                    ModelSpecRec(
                        id="model.codex-cliproxy",
                        display_name="Codex 系列（US cliproxy）",
                        provider_id="prov.us-cliproxy",
                        adapter_kind="openai_compatible",
                        capabilities={
                            "supports_text": True,
                            "supports_tools": True,
                            "supports_vision": True,
                            "supports_structured_output": True,
                            "context_window": 200000,
                            "rate_limit_rpm": 120,
                            "pricing_tier": "premium",
                        },
                        enabled=False,
                    )
                ],
            ),
            AIProviderRec(
                id="prov.google-gemini",
                display_name="Google Gemini Native Adapter",
                adapter_kind="gemini_native",
                endpoint_url="https://generativelanguage.googleapis.com/v1beta",
                credential_ref="vault://gemini-developer-api-ref",
                has_secret_configured=False,
                status="UNAVAILABLE",
                enabled=False,
                source_kind="unavailable",
                models=[
                    ModelSpecRec(
                        id="model.gemini-2.5-pro",
                        display_name="Gemini 2.5 Pro",
                        provider_id="prov.google-gemini",
                        adapter_kind="gemini_native",
                        capabilities={
                            "supports_text": True,
                            "supports_tools": True,
                            "supports_vision": True,
                            "supports_structured_output": True,
                            "context_window": 1048576,
                            "rate_limit_rpm": 60,
                            "pricing_tier": "premium",
                        },
                        enabled=False,
                        source_kind="unavailable",
                    )
                ],
            ),
            AIProviderRec(
                id="prov.mistral-native",
                display_name="Mistral Native Adapter",
                adapter_kind="mistral_native",
                endpoint_url="https://api.mistral.ai/v1",
                credential_ref="vault://mistral-api-ref",
                has_secret_configured=False,
                status="UNAVAILABLE",
                enabled=False,
                source_kind="unavailable",
                models=[
                    ModelSpecRec(
                        id="model.mistral-large",
                        display_name="Mistral Large 2",
                        provider_id="prov.mistral-native",
                        adapter_kind="mistral_native",
                        capabilities={
                            "supports_text": True,
                            "supports_tools": True,
                            "supports_vision": False,
                            "supports_structured_output": True,
                            "context_window": 131072,
                            "rate_limit_rpm": 60,
                            "pricing_tier": "standard",
                        },
                        enabled=False,
                        source_kind="unavailable",
                    )
                ],
            ),
        ]
        for p in baseline_providers:
            self.providers[p.id] = p
            for m in p.models:
                self.models[m.id] = m

    def register_provider(self, body: dict, *, actor: str) -> dict:
        pid = body["id"]
        if "cherry" in pid.lower() or "cherry" in body["endpoint_url"].lower():
            raise PermissionError("cherry_frozen_boundary")
        if body["adapter_kind"] not in ADAPTER_KINDS:
            raise ValueError("invalid_adapter_kind")
        with self._lock:
            if pid in self.providers:
                raise FileExistsError("provider_already_exists")
            secret_val = body.get("api_key_secret")
            if secret_val:
                self._secret_vault[pid] = secret_val
            models: list[ModelSpecRec] = []
            for m in body["models"]:
                caps = dict(m["capabilities"])
                mspec = ModelSpecRec(
                    id=m["id"],
                    display_name=m["display_name"],
                    provider_id=pid,
                    adapter_kind=body["adapter_kind"],
                    capabilities=caps,
                    enabled=False,
                    source_kind="mock",
                )
                models.append(mspec)
                self.models[mspec.id] = mspec
            rec = AIProviderRec(
                id=pid,
                display_name=body["display_name"],
                adapter_kind=body["adapter_kind"],
                endpoint_url=body["endpoint_url"],
                credential_ref=body["credential_ref"],
                has_secret_configured=bool(secret_val),
                status="UNKNOWN",
                enabled=False,
                models=models,
                source_kind="mock",
            )
            self.providers[pid] = rec
            self.engine.audit(actor, "ai_hub.provider.register", pid, f"adapter={rec.adapter_kind}")
            return self.provider_out(rec)

    def update_provider(self, pid: str, body: dict, *, actor: str) -> dict:
        with self._lock:
            rec = self.providers.get(pid)
            if rec is None:
                raise KeyError(pid)
            if body.get("display_name") is not None:
                rec.display_name = body["display_name"]
            if body.get("endpoint_url") is not None:
                if "cherry" in body["endpoint_url"].lower():
                    raise PermissionError("cherry_frozen_boundary")
                rec.endpoint_url = body["endpoint_url"]
            if body.get("enabled") is not None:
                # Without real live verification, enabling stays MOCK_ONLY / unavailable
                rec.enabled = bool(body["enabled"]) and rec.status == "AVAILABLE"
            self.engine.audit(actor, "ai_hub.provider.update", pid, "updated")
            return self.provider_out(rec)

    def delete_provider(self, pid: str, *, actor: str) -> None:
        with self._lock:
            rec = self.providers.pop(pid, None)
            if rec is None:
                raise KeyError(pid)
            self._secret_vault.pop(pid, None)
            for m in rec.models:
                self.models.pop(m.id, None)
            self.engine.audit(actor, "ai_hub.provider.delete", pid, "deleted")

    def probe_provider(self, pid: str, *, actor: str) -> dict:
        """Safe capability discovery probe (V2-EXT-001): degrades safely to UNAVAILABLE without live network."""
        with self._lock:
            rec = self.providers.get(pid)
            if rec is None:
                raise KeyError(pid)
            # In local mock / unapproved production probe mode, discovery safely degrades to UNAVAILABLE
            rec.status = "UNAVAILABLE"
            rec.source_kind = "unavailable"
            for m in rec.models:
                m.enabled = False
                m.source_kind = "unavailable"
            self.engine.audit(actor, "ai_hub.provider.probe", pid, "degraded_unavailable")
            return self.provider_out(rec)

    def get_model_detail(self, model_id: str) -> dict:
        with self._lock:
            m = self.models.get(model_id)
            if m is None:
                raise KeyError(model_id)
            return {
                "id": m.id,
                "title": m.display_name,
                "provider_id": m.provider_id,
                "adapter_kind": m.adapter_kind,
                "capabilities": dict(m.capabilities),
                "enabled": m.enabled,
                "source_meta": Q._meta(m.source_kind),
            }

    def get_routing_policy(self) -> dict:
        with self._lock:
            return {
                **self.routing_policy,
                "source_meta": Q._meta("mock"),
            }

    def update_routing_policy(self, body: dict, *, actor: str) -> dict:
        with self._lock:
            default_id = body["default_model_id"]
            if default_id not in self.models:
                raise KeyError(default_id)
            fallback_id = body.get("fallback_model_id")
            if fallback_id and fallback_id not in self.models:
                raise KeyError(fallback_id)
            routes = dict(body.get("task_routes") or {})
            for target_model in routes.values():
                if target_model not in self.models:
                    raise KeyError(target_model)
            self.routing_policy = {
                "default_model_id": default_id,
                "fallback_model_id": fallback_id,
                "task_routes": routes,
                "updated_at": Q._now(),
            }
            self.engine.audit(actor, "ai_hub.routing.update", default_id, "ok")
            return self.get_routing_policy()

    def run_completion(self, body: dict, *, actor: str) -> dict:
        if body.get("dry_run") is not True:
            raise ValueError("dry_run_required_in_local_mode")
        with self._lock:
            req_model = body.get("model_id")
            task_kind = body.get("task_kind")
            if not req_model and task_kind:
                req_model = self.routing_policy["task_routes"].get(task_kind)
            if not req_model:
                req_model = self.routing_policy["default_model_id"]
            model = self.models.get(req_model)
            if model is None:
                raise KeyError(req_model)
            caps = model.capabilities
            if body.get("require_tools") and not caps.get("supports_tools"):
                raise ValueError("model_lacks_tools_capability")
            if body.get("require_vision") and not caps.get("supports_vision"):
                raise ValueError("model_lacks_vision_capability")
            cid = str(uuid.uuid4())
            self.engine.audit(actor, "ai_hub.completion.simulate", cid, f"model={model.id}")
            return {
                "completion_id": cid,
                "routed_model_id": model.id,
                "provider_id": model.provider_id,
                "content": f"[LOCAL_MOCK_SYNTHETIC_RESPONSE model={model.id}] Processed prompt ({len(body['prompt'])} chars)",
                "dry_run": True,
                "source_meta": Q._meta("mock"),
            }

    def provider_out(self, rec: AIProviderRec) -> dict:
        return {
            "id": rec.id,
            "display_name": rec.display_name,
            "adapter_kind": rec.adapter_kind,
            "endpoint_url": rec.endpoint_url,
            "credential_ref": rec.credential_ref,
            "has_secret_configured": rec.has_secret_configured,
            "status": rec.status,
            "models": [
                {
                    "id": m.id,
                    "display_name": m.display_name,
                    "capabilities": dict(m.capabilities),
                    "enabled": m.enabled,
                }
                for m in rec.models
            ],
            "source_meta": Q._meta(rec.source_kind),
        }

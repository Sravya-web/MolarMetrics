"""Check whether the local Ollama server and the configured model are available."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from molarmetrics.config import Settings, get_settings


@dataclass
class OllamaStatus:
    base_url: str
    model: str
    is_local: bool
    reachable: bool = False
    version: str | None = None
    model_available: bool = False
    installed_models: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.reachable and self.model_available

    @property
    def message(self) -> str:
        """An actionable, plain-English status line."""
        if not self.reachable:
            return (f"Ollama is not reachable at {self.base_url}. Start it with `ollama serve` "
                    "(or open the Ollama app), then refresh this page.")
        if not self.model_available:
            return (f"Ollama is running, but the model `{self.model}` is not installed. "
                    f"Run `ollama pull {self.model}`, then refresh this page.")
        return f"Ollama {self.version or ''} is running locally and `{self.model}` is available.".replace("  ", " ")


def check_ollama(settings: Settings | None = None, timeout: float = 2.0) -> OllamaStatus:
    s = settings or get_settings()
    status = OllamaStatus(base_url=s.ollama_base_url, model=s.ollama_model, is_local=s.ollama_is_local)
    try:
        with httpx.Client(timeout=timeout) as client:
            status.version = client.get(f"{s.ollama_base_url}/api/version").json().get("version")
            status.reachable = True
            tags = client.get(f"{s.ollama_base_url}/api/tags").json()
    except (httpx.HTTPError, ValueError):
        return status
    status.installed_models = sorted(m.get("name", "") for m in tags.get("models", []))
    wanted = s.ollama_model if ":" in s.ollama_model else f"{s.ollama_model}:latest"
    status.model_available = wanted in status.installed_models
    return status

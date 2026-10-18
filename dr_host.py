"""Adapters between the plugin and Hermes: settings, the model, and the TTS tool."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .dr_config import Settings, load_settings

logger = logging.getLogger("hermes.plugins.daily_reading")
PLUGIN_ID = "daily-reading"


def settings_from_ctx(ctx: Any, log: bool = True) -> Settings:
    return load_settings(lambda key, default=None: ctx.get_config(key, default), log=log)


def settings_from_config(log: bool = True) -> Settings:
    """For the dashboard backend, which has no plugin context: read config.yaml directly."""
    def get(key: str, default: Any = None) -> Any:
        try:
            from hermes_cli.config import load_config  # type: ignore

            entries = (load_config() or {}).get("plugins", {}).get("entries", {}) or {}
            settings = (entries.get(PLUGIN_ID) or {}).get("settings") or {}
            return settings.get(key, default)
        except Exception:
            return default
    return load_settings(get, log=log)


def model_call(llm: Any) -> Callable[[str, str, Dict[str, Any]], Any]:
    """Structured call on the user's current model; returns the parsed answer (or None)."""
    def call(instructions: str, text: str, schema: Dict[str, Any]) -> Any:
        result = llm.complete_structured(
            instructions=instructions, input=[{"type": "text", "text": text}], json_schema=schema,
            schema_name="daily_reading", purpose="daily-reading", max_tokens=12000, temperature=0.2)
        return getattr(result, "parsed", None)
    return call


def backend_llm() -> Optional[Any]:
    try:
        from agent.plugin_llm import PluginLlm  # type: ignore

        return PluginLlm(plugin_id=PLUGIN_ID)
    except Exception:
        return None


def _ensure_tool(name: str) -> None:
    """CLI commands run before Hermes loads its built-in tools; load them on demand."""
    try:
        from tools.registry import discover_builtin_tools, registry  # type: ignore

        if registry.get_entry(name) is None:
            discover_builtin_tools()
    except Exception:
        pass


def tool_dispatch(dispatch_tool: Optional[Callable[..., str]] = None) -> Callable[[str, Dict[str, Any]], str]:
    def dispatch(name: str, args: Dict[str, Any]) -> str:
        _ensure_tool(name)
        if dispatch_tool is not None:
            return dispatch_tool(name, args)
        from tools.registry import registry  # type: ignore

        return registry.dispatch(name, args)
    return dispatch

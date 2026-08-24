import json
import os
from pathlib import Path


def load_codex_auth():
    p = Path.home() / ".codex" / "auth.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_mode():
    auth = load_codex_auth()
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "api_key"
    if auth.get("OPENAI_API_KEY"):
        return "api_key"
    token = (auth.get("tokens") or {}).get("access_token")
    if token and auth.get("auth_mode") == "chatgpt":
        return "codex"
    return None


def api_key():
    env = os.environ.get("OPENAI_API_KEY", "").strip()
    if env:
        return env
    return load_codex_auth().get("OPENAI_API_KEY") or ""


def codex_tokens():
    auth = load_codex_auth()
    tokens = auth.get("tokens") or {}
    return tokens.get("access_token", ""), tokens.get("account_id", "")


def get_codex_model(default="gpt-5-codex"):
    p = Path.home() / ".codex" / "config.toml"
    if not p.exists():
        return default
    try:
        import tomllib
        cfg = tomllib.loads(p.read_text(encoding="utf-8"))
        return cfg.get("model") or default
    except Exception:
        return default

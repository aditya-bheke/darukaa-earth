"""Runtime configuration. Values come from environment variables, a local .env file,
or Streamlit secrets (for Streamlit Community Cloud)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
RAW_DIR = DATA_DIR / "raw"
INDEX_DIR = DATA_DIR / "index"

load_dotenv(ROOT / ".env")


def _secret(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    try:  # Streamlit Cloud exposes secrets via st.secrets
        import streamlit as st

        return st.secrets.get(name, default)
    except Exception:
        return default


# provider -> (base url, key variable, default model, default fallback model used on rate limits)
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b", "openai/gpt-oss-20b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "gemini-2.0-flash", ""),
}

LLM_PROVIDER = (_secret("LLM_PROVIDER", "groq") or "groq").lower()
if LLM_PROVIDER in PROVIDERS:
    LLM_BASE_URL, _key_name, _default_model, _default_fallback = PROVIDERS[LLM_PROVIDER]
    LLM_API_KEY = _secret(_key_name)
    LLM_MODEL = _secret("LLM_MODEL", _default_model)
    LLM_FALLBACK_MODEL = _secret("LLM_FALLBACK_MODEL", _default_fallback)
else:  # "none" disables the LLM; the deterministic engine still works
    LLM_BASE_URL = LLM_API_KEY = LLM_MODEL = LLM_FALLBACK_MODEL = None

DB_PATH = Path(_secret("DARUKAA_DB_PATH", str(DATA_DIR / "darukaa.db")))
EMBEDDING_MODEL = _secret("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
GEO_ENABLED = (_secret("GEO_ENABLED", "true") or "true").lower() == "true"

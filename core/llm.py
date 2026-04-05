import logging
from typing import Any

logger = logging.getLogger(__name__)

def get_llm(model_cfg: Any):
    provider = model_cfg.provider.lower()
    
    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model_cfg.model_name,
                temperature=model_cfg.temperature,
                api_key=model_cfg.api_key,
                base_url=(
                    model_cfg.base_url
                    if model_cfg.base_url != "http://localhost:11434"
                    else None
                ),
            )
        except ImportError as e:
            raise ImportError("langchain_openai required for openai provider") from e
            
    elif provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=model_cfg.model_name,
                temperature=model_cfg.temperature,
                api_key=model_cfg.api_key,
            )
        except ImportError as e:
            raise ImportError("langchain_google_genai required for gemini provider") from e
            
    else:
        # Ollama: local vs cloud routing
        is_local = (
            model_cfg.base_url is None
            or "localhost" in model_cfg.base_url
            or "127.0.0.1" in model_cfg.base_url
        )

        if is_local:
            # Local Ollama — use native langchain_ollama
            try:
                from langchain_ollama import ChatOllama
                return ChatOllama(
                    model=model_cfg.model_name,
                    temperature=model_cfg.temperature,
                    base_url=model_cfg.base_url or "http://localhost:11434",
                )
            except ImportError as e:
                raise ImportError("langchain_ollama required for local ollama") from e
        else:
            # Ollama Cloud — use OpenAI-compatible endpoint
            # langchain_ollama constructs wrong path (/v1/api/chat) for cloud
            try:
                from langchain_openai import ChatOpenAI
                base_url = model_cfg.base_url.rstrip("/")
                # Ensure /v1 suffix for OpenAI-compatible endpoint
                if not base_url.endswith("/v1"):
                    base_url = f"{base_url}/v1"
                return ChatOpenAI(
                    model=model_cfg.model_name,
                    temperature=model_cfg.temperature,
                    api_key=model_cfg.api_key,
                    base_url=base_url,
                )
            except ImportError as e:
                raise ImportError("langchain_openai required for ollama cloud") from e
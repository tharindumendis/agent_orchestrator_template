import logging
from typing import Any

logger = logging.getLogger(__name__)

def get_llm(model_cfg: Any):
    """
    Initializes and returns a LangChain ChatModel based on the provided configuration.
    Accepts ModelConfig or SummarizerModelConfig objects which have the standard properties:
    - provider
    - model_name
    - temperature
    - api_key
    - base_url
    """
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
        # Default to Ollama
        try:
            from langchain_ollama import ChatOllama
            return ChatOllama(
                model=model_cfg.model_name,
                temperature=model_cfg.temperature,
                base_url=model_cfg.base_url,
            )
        except ImportError as e:
            raise ImportError("langchain_ollama required for ollama provider") from e

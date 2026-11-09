"""Multi-provider free-tier AI layer: NVIDIA NIM -> Groq -> local analysis. See docs/AI-PROVIDERS.md."""
from .adapters import GroqAdapter, NVIDIAAdapter, OpenAICompatAdapter
from .health import AIHealthMonitor
from .manager import AIProviderManager, Route, build_default_manager
from .request_queue import AIRequestQueue
from .quota import AIQuotaManager, Limits
from .types import AIRequest, AIResponse, AllProvidersUnavailable, Priority, ProviderError

__all__ = ["GroqAdapter", "NVIDIAAdapter", "OpenAICompatAdapter", "AIHealthMonitor", "AIProviderManager", "Route",
           "build_default_manager", "AIRequestQueue", "AIQuotaManager", "Limits", "AIRequest", "AIResponse",
           "AllProvidersUnavailable", "Priority", "ProviderError"]

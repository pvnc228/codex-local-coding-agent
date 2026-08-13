"""Bounded controller components for delegating small coding tasks."""

from .controller import Controller
from .memory import LoadedModel, MemoryBudgetError, MemorySnapshot, ModelMemoryManager
from .ollama_adapter import ModelProfile, OllamaClient, OllamaError
from .task import TaskEnvelope
from .service import DirectCodingAdapter, ServiceError, ServiceRequest, ServiceResult, WorkspaceRegistry
from .validators import ValidationReport, validate_candidate

__all__ = [
    "Controller",
    "LoadedModel",
    "MemoryBudgetError",
    "MemorySnapshot",
    "ModelMemoryManager",
    "ModelProfile",
    "OllamaClient",
    "OllamaError",
    "DirectCodingAdapter",
    "ServiceError",
    "ServiceRequest",
    "ServiceResult",
    "TaskEnvelope",
    "ValidationReport",
    "WorkspaceRegistry",
    "validate_candidate",
]

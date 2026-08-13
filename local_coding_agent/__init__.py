"""Bounded controller components for delegating small coding tasks."""

from .atomizer import Decomposition, PreflightReport, TaskBudget, decompose, preflight
from .controller import Controller
from .delegator import DelegatingAgent, DecompositionTemplate, is_decomposable_failure
from .memory import LoadedModel, MemoryBudgetError, MemorySnapshot, ModelMemoryManager
from .ollama_adapter import ModelProfile, OllamaClient, OllamaError
from .service import DelegationRequest, DelegationService
from .stdio import StdioDelegationAdapter
from .task import TaskEnvelope
from .validators import ValidationReport, validate_candidate
from .worker_pool import BoundedWorkerPool

__all__ = [
    "Controller",
    "DelegationRequest",
    "DelegationService",
    "BoundedWorkerPool",
    "StdioDelegationAdapter",
    "DelegatingAgent",
    "DecompositionTemplate",
    "is_decomposable_failure",
    "Decomposition",
    "PreflightReport",
    "TaskBudget",
    "decompose",
    "preflight",
    "LoadedModel",
    "MemoryBudgetError",
    "MemorySnapshot",
    "ModelMemoryManager",
    "ModelProfile",
    "OllamaClient",
    "OllamaError",
    "TaskEnvelope",
    "ValidationReport",
    "validate_candidate",
]

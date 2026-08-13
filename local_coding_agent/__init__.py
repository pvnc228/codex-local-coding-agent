"""Bounded controller components for delegating small coding tasks."""

from .atomizer import Decomposition, PreflightReport, TaskBudget, decompose, preflight
from .calibration import calibrate_for_model, calibrate_workers, model_vram_bytes
from .controller import Controller
from .delegator import DelegatingAgent, DecompositionTemplate, is_decomposable_failure
from .memory import LoadedModel, MemoryBudgetError, MemorySnapshot, ModelMemoryManager
from .mcp_server import build_server
from .ollama_adapter import ModelProfile, OllamaClient, OllamaError
from .service import DelegationRequest, DelegationService
from .stats import DelegationStats, JsonlStatsSink, TimedDelegationStats
from .stdio import StdioDelegationAdapter
from .task import TaskEnvelope
from .validators import ValidationReport, validate_candidate
from .worker_pool import BoundedWorkerPool

__all__ = [
    "Controller",
    "DelegationRequest",
    "DelegationService",
    "DelegationStats",
    "JsonlStatsSink",
    "TimedDelegationStats",
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
    "calibrate_for_model",
    "calibrate_workers",
    "model_vram_bytes",
    "LoadedModel",
    "MemoryBudgetError",
    "MemorySnapshot",
    "ModelMemoryManager",
    "ModelProfile",
    "OllamaClient",
    "OllamaError",
    "build_server",
    "TaskEnvelope",
    "ValidationReport",
    "validate_candidate",
]

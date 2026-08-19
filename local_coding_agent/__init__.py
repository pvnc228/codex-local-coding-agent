"""Bounded controller components for delegating small coding tasks."""

__version__ = "0.7.0"


from .ast_compactor import skeletonize_file, skeletonize_python
from .atomizer import Decomposition, PreflightReport, TaskBudget, decompose, preflight

from .calibration import calibrate_for_model, calibrate_workers, model_vram_bytes
from .context_manager import (
    ContextAssembler,
    HarnessState,
    compact_tool_exchanges,
    purge_diff_residues,
)
from .controller import Controller
from .delegator import DelegatingAgent, DecompositionTemplate, is_decomposable_failure
from .doctor import (
    CheckResult,
    DoctorFixReport,
    DoctorReport,
    diagnose_environment,
    remediate_environment,
)
from .mcp_config import generate_mcp_config_dict, get_client_config_path, integrate_mcp_config
from .mcp_server import build_server
from .memory import LoadedModel, MemoryBudgetError, MemorySnapshot, ModelMemoryManager
from .monitor import MonitorServer
from .ollama_adapter import (
    ModelProfile,
    OllamaClient,
    OllamaError,
    OpenAICompatibleClient,
    build_client,
)
from .semantic_linter import (
    LinterDiagnostic,
    LinterReport,
    lint_patch_in_memory,
    lint_source_code,
)
from .service import DelegationRequest, DelegationService
from .smoke import run_smoke_test
from .speculative_racing import SpeculativeRacer
from .stats import DelegationStats, JsonlStatsSink, TimedDelegationStats
from .stdio import StdioDelegationAdapter
from .task import TaskEnvelope
from .task_store import JsonFileTaskStore, TaskRecord, TaskStore
from .validators import ValidationReport, validate_candidate
from .worker_pool import BoundedWorkerPool

try:
    from .tasks import TASKS_IDENTIFIER, TasksExtension
except ImportError:  # pragma: no cover - mcp is an optional dependency
    TasksExtension = None  # type: ignore[assignment]
    TASKS_IDENTIFIER = "io.modelcontextprotocol/tasks"

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
    "OpenAICompatibleClient",
    "build_client",
    "build_server",
    "TaskEnvelope",
    "ValidationReport",
    "validate_candidate",
    "TasksExtension",
    "TASKS_IDENTIFIER",
    "diagnose_environment",
    "DoctorReport",
    "DoctorFixReport",
    "remediate_environment",
    "CheckResult",
    "generate_mcp_config_dict",
    "get_client_config_path",
    "integrate_mcp_config",
    "run_smoke_test",
    "MonitorServer",
    "TaskStore",
    "TaskRecord",
    "JsonFileTaskStore",
    "HarnessState",
    "ContextAssembler",
    "compact_tool_exchanges",
    "purge_diff_residues",
    "skeletonize_python",
    "skeletonize_file",
    "LinterDiagnostic",
    "LinterReport",
    "lint_source_code",
    "lint_patch_in_memory",
    "SpeculativeRacer",
]

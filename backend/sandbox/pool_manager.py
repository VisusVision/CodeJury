"""
pool_manager.py — Global Sandbox Pool Manager

Call initialize_pool() at application startup.
Use get_pool() anywhere to access the active pool.
Call shutdown_pool() at application shutdown.
"""
import os

from backend.sandbox.pool import SandboxPool

_pool: SandboxPool | None = None

# Read from environment variables or fall back to defaults
_IMAGE     = os.getenv("SANDBOX_IMAGE",              "agentgrade-sandbox")
_POOL_SIZE = int(os.getenv("SANDBOX_POOL_SIZE",      "10"))
_BASE_PORT = int(os.getenv("SANDBOX_POOL_BASE_PORT", "8181"))
_TIMEOUT   = float(os.getenv("SANDBOX_POOL_TIMEOUT", "30.0"))


def initialize_pool() -> None:
    """Initialize the container pool (called at application startup)."""
    global _pool
    print(
        f"[pool-manager] Baslatiliyor: image={_IMAGE} "
        f"size={_POOL_SIZE} port={_BASE_PORT}-{_BASE_PORT + _POOL_SIZE - 1}",
        flush=True,
    )
    _pool = SandboxPool(
        image=_IMAGE,
        pool_size=_POOL_SIZE,
        base_port=_BASE_PORT,
        acquire_timeout=_TIMEOUT,
    )
    _pool.initialize()


def get_pool() -> SandboxPool | None:
    """Return the active pool. Returns None if Docker is unavailable."""
    return _pool


def shutdown_pool() -> None:
    """Stop all containers (called at application shutdown)."""
    global _pool
    if _pool is not None:
        _pool.shutdown()
        _pool = None

"""
pool_manager.py — Global Sandbox Pool Manager

Call initialize_pool() at application startup.
Use get_pool() anywhere to access the active pool.
Call shutdown_pool() at application shutdown.
"""
import os
import socket
import threading
import time

from backend.sandbox.pool import PoolState, SandboxPool

_pool: SandboxPool | None = None
_manager_condition = threading.Condition()
_initializing = False


def _owner_id() -> str:
    configured = os.getenv("SANDBOX_POOL_OWNER", "").strip()
    return configured or f"{socket.gethostname()}-{os.getpid()}"


def initialize_pool() -> SandboxPool:
    """Initialize the container pool (called at application startup). Thread-safe; concurrent callers wait for the same initialization."""
    global _pool, _initializing
    with _manager_condition:
        if _initializing:
            while _initializing:
                _manager_condition.wait()
            assert _pool is not None
            return _pool
        if _pool is not None and _pool.is_ready:
            return _pool
        _initializing = True
        candidate = SandboxPool(
            image=os.getenv("SANDBOX_IMAGE", "agentgrade-sandbox"),
            pool_size=int(os.getenv("SANDBOX_POOL_SIZE", "10")),
            base_port=int(os.getenv("SANDBOX_POOL_BASE_PORT", "8181")),
            acquire_timeout=float(os.getenv("SANDBOX_POOL_TIMEOUT", "30.0")),
            owner_id=_owner_id(),
        )
        candidate._set_state(PoolState.STARTING)
        _pool = candidate
        pool = candidate
        _manager_condition.notify_all()
    try:
        pool.initialize()
        return pool
    finally:
        with _manager_condition:
            _initializing = False
            _manager_condition.notify_all()


def reinitialize_pool() -> SandboxPool:
    """Discard the current pool (if any) and initialize a fresh one."""
    global _pool
    with _manager_condition:
        old_pool = _pool
        _pool = None
    if old_pool is not None:
        old_pool.shutdown()
    return initialize_pool()


def get_pool() -> SandboxPool | None:
    """Return the active pool. Returns None if not yet initialized."""
    return _pool


def wait_for_pool_ready(timeout_s: float = 15.0) -> SandboxPool | None:
    """Block until a pool exists and reaches READY/DEGRADED, or timeout. Returns the pool if usable, else None."""
    deadline = time.monotonic() + max(0.0, timeout_s)
    with _manager_condition:
        while _pool is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            _manager_condition.wait(remaining)
        pool = _pool
    remaining = max(0.0, deadline - time.monotonic())
    return pool if pool.wait_until_ready(remaining) else None


def shutdown_pool() -> None:
    """Stop all containers (called at application shutdown)."""
    global _pool
    with _manager_condition:
        pool = _pool
        _pool = None
        _manager_condition.notify_all()
    if pool is not None:
        pool.shutdown()

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from nonebot import logger


_tasks: set[asyncio.Task[Any]] = set()
_graceful_tasks: set[asyncio.Task[Any]] = set()
_keyed_tasks: dict[str, asyncio.Task[Any]] = {}
_accepting_tasks = True
_shutdown_callbacks: list[Callable[[], Awaitable[None]]] = []


def create_background_task(
    coroutine: Coroutine[Any, Any, Any],
    *,
    name: str,
    key: str | None = None,
    graceful: bool = False,
) -> asyncio.Task[Any] | None:
    global _accepting_tasks
    if not _accepting_tasks:
        coroutine.close()
        return None

    if key:
        existing = _keyed_tasks.get(key)
        if existing and not existing.done():
            coroutine.close()
            return existing

    task = asyncio.create_task(coroutine, name=name)
    _tasks.add(task)
    if graceful:
        _graceful_tasks.add(task)
    if key:
        _keyed_tasks[key] = task
    task.add_done_callback(lambda completed: _task_done(completed, key))
    return task


def _task_done(task: asyncio.Task[Any], key: str | None) -> None:
    _tasks.discard(task)
    _graceful_tasks.discard(task)
    if key and _keyed_tasks.get(key) is task:
        _keyed_tasks.pop(key, None)
    if task.cancelled():
        return
    try:
        exception = task.exception()
    except asyncio.CancelledError:
        return
    if exception is not None:
        logger.error("Background task {} failed: {}", task.get_name(), exception)


def register_shutdown_callback(callback: Callable[[], Awaitable[None]]) -> None:
    if callback not in _shutdown_callbacks:
        _shutdown_callbacks.append(callback)


async def shutdown_background_tasks(timeout_seconds: float = 10.0) -> None:
    global _accepting_tasks
    _accepting_tasks = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, timeout_seconds)
    for callback in reversed(_shutdown_callbacks):
        try:
            remaining = max(0.0, deadline - loop.time())
            await asyncio.wait_for(callback(), timeout=remaining)
        except TimeoutError:
            logger.warning("Background task shutdown callback timed out")
            break
        except Exception as exc:
            logger.warning("Background task shutdown callback failed: {}", exc)
    current = asyncio.current_task()
    pending = [task for task in _tasks if task is not current and not task.done()]
    if not pending:
        return

    immediate = [task for task in pending if task not in _graceful_tasks]
    for task in immediate:
        task.cancel()
    if immediate:
        await asyncio.gather(*immediate, return_exceptions=True)

    graceful = [task for task in pending if task in _graceful_tasks and not task.done()]
    remaining = max(0.0, deadline - loop.time())
    if graceful and remaining:
        _, graceful = await asyncio.wait(graceful, timeout=remaining)
    for task in graceful:
        task.cancel()
    if graceful:
        await asyncio.gather(*graceful, return_exceptions=True)
    logger.info("Stopped {} background tasks", len(pending))


def reset_background_task_registry() -> None:
    """Restore task acceptance for tests or an in-process restart setup."""
    global _accepting_tasks
    _accepting_tasks = True

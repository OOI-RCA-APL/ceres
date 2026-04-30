import asyncio
from typing import override

import pytest

from ceres.tasklet import Tasklet


class SimpleTasklet(Tasklet):
    @override
    async def __run__(self) -> None:
        await self.wait_until_stopping()

    @override
    async def __stop__(self) -> None:
        pass


class ImmediateTasklet(Tasklet):
    @override
    async def __run__(self) -> None:
        return

    @override
    async def __stop__(self) -> None:
        pass


class FailingTasklet(Tasklet):
    @override
    async def __run__(self) -> None:
        raise RuntimeError("task failed")

    @override
    async def __stop__(self) -> None:
        pass


class HookTrackingTasklet(Tasklet):
    def __init__(self) -> None:
        self.hooks_called: list[str] = []

    @override
    async def __run__(self) -> None:
        await self.wait_until_stopping()

    @override
    async def __stop__(self) -> None:
        self.hooks_called.append("stop")

    @override
    def __stopping__(self) -> None:
        self.hooks_called.append("stopping")

    @override
    async def __post_stop__(self) -> None:
        self.hooks_called.append("post_stop")


async def test_never_started_tasklet_is_stopped_and_stopping() -> None:
    tasklet = SimpleTasklet()
    assert tasklet.running is False
    assert tasklet.stopping is True


async def test_run_starts_and_waits_for_completion() -> None:
    tasklet = ImmediateTasklet()
    await tasklet.run()
    assert tasklet.running is False
    assert tasklet.stopping is True


async def test_start_and_stop_lifecycle() -> None:
    tasklet = SimpleTasklet()
    tasklet.start()
    await asyncio.sleep(0)

    assert tasklet.running is True
    assert tasklet.stopping is False

    await tasklet.stop()

    assert tasklet.running is False
    assert tasklet.stopping is True


async def test_running_and_stopping_properties_through_lifecycle() -> None:
    tasklet = SimpleTasklet()

    assert tasklet.running is False
    assert tasklet.stopping is True

    tasklet.start()
    await asyncio.sleep(0)

    assert tasklet.running is True
    assert tasklet.stopping is False

    await tasklet.stop()

    assert tasklet.running is False
    assert tasklet.stopping is True


async def test_start_on_already_running_tasklet_is_noop() -> None:
    tasklet = SimpleTasklet()
    tasklet.start()
    await asyncio.sleep(0)

    tasklet.start()
    assert tasklet.running is True

    await tasklet.stop()


async def test_run_raises_exception_from_failing_tasklet() -> None:
    tasklet = FailingTasklet()
    with pytest.raises(RuntimeError, match="task failed"):
        await tasklet.run()


async def test_wait_until_stopped_raises_captured_exception() -> None:
    tasklet = FailingTasklet()
    tasklet.start()

    with pytest.raises(RuntimeError, match="task failed"):
        await tasklet.wait_until_stopped(raise_exceptions=True)


async def test_on_exception_callback_fires() -> None:
    captured_exceptions: list[BaseException] = []

    def handle_exception(tasklet: FailingTasklet, exception: BaseException) -> None:
        captured_exceptions.append(exception)

    tasklet = FailingTasklet()
    tasklet.start(on_exception=handle_exception)
    await tasklet.wait_until_stopped(raise_exceptions=False)

    assert len(captured_exceptions) == 1
    assert isinstance(captured_exceptions[0], RuntimeError)
    assert str(captured_exceptions[0]) == "task failed"


async def test_on_completed_callback_fires_on_normal_completion() -> None:
    completed: list[Tasklet] = []

    def handle_completed(tasklet: ImmediateTasklet) -> None:
        completed.append(tasklet)

    tasklet = ImmediateTasklet()
    await tasklet.run(on_completed=handle_completed)

    assert len(completed) == 1
    assert completed[0] is tasklet


async def test_on_completed_callback_fires_on_exception() -> None:
    completed: list[Tasklet] = []

    def handle_completed(tasklet: FailingTasklet) -> None:
        completed.append(tasklet)

    tasklet = FailingTasklet()
    await tasklet.run(raise_exceptions=False, on_completed=handle_completed)

    assert len(completed) == 1
    assert completed[0] is tasklet


async def test_stop_with_raise_exceptions_reraises() -> None:
    tasklet = FailingTasklet()
    tasklet.start()
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="task failed"):
        await tasklet.stop(raise_exceptions=True)


async def test_stopping_hook_is_called() -> None:
    tasklet = HookTrackingTasklet()
    tasklet.start()
    await asyncio.sleep(0)
    await tasklet.stop()

    assert "stopping" in tasklet.hooks_called


async def test_post_stop_hook_is_called_after_stop() -> None:
    tasklet = HookTrackingTasklet()
    tasklet.start()
    await asyncio.sleep(0)
    await tasklet.stop()

    assert tasklet.hooks_called.index("stop") < tasklet.hooks_called.index("post_stop")


async def test_hook_order_is_stopping_then_stop_then_post_stop() -> None:
    tasklet = HookTrackingTasklet()
    tasklet.start()
    await asyncio.sleep(0)
    await tasklet.stop()

    assert tasklet.hooks_called == ["stopping", "stop", "post_stop"]


async def test_wait_until_stopping_resolves_when_stop_called() -> None:
    tasklet = SimpleTasklet()
    tasklet.start()
    await asyncio.sleep(0)

    async def stop_after_delay() -> None:
        await asyncio.sleep(0.05)
        await tasklet.stop()

    stopper = asyncio.create_task(stop_after_delay())
    await tasklet.wait_until_stopping()

    assert tasklet.stopping is True
    await stopper


async def test_wait_until_stopping_returns_immediately_for_never_started() -> None:
    tasklet = SimpleTasklet()
    await tasklet.wait_until_stopping()
    assert tasklet.stopping is True


async def test_run_with_raise_exceptions_false_suppresses_exception() -> None:
    tasklet = FailingTasklet()
    await tasklet.run(raise_exceptions=False)
    assert tasklet.running is False


async def test_wait_until_stopped_returns_immediately_for_never_started() -> None:
    tasklet = SimpleTasklet()
    await tasklet.wait_until_stopped()
    assert tasklet.running is False

"""Tests for generation concurrency limiting (L10)."""
import asyncio
import pytest
import pytest_asyncio

from app.main import MAX_CONCURRENT_GENERATIONS, _get_semaphore


class TestConcurrency:
    """Test semaphore-based concurrency limiting."""

    @pytest_asyncio.fixture(autouse=True)
    def _reset_semaphore(self):
        """Reset semaphore before each test."""
        import app.main as _m
        _m._generation_semaphore = None
        yield

    async def test_semaphore_limits_concurrency(self):
        """Semaphore allows exactly MAX_CONCURRENT_GENERATIONS concurrent tasks."""
        sem = await _get_semaphore()
        assert sem._value == MAX_CONCURRENT_GENERATIONS

        # Acquire all slots
        for _ in range(MAX_CONCURRENT_GENERATIONS):
            await sem.acquire()

        assert sem._value == 0

        # Next acquire should block
        release_event = asyncio.Event()

        async def _try_acquire():
            await sem.acquire()
            release_event.set()

        task = asyncio.create_task(_try_acquire())
        await asyncio.sleep(0.1)
        assert not release_event.is_set(), "Semaphore should block when full"

        # Release one slot
        sem.release()
        await asyncio.wait_for(release_event.wait(), timeout=2.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_semaphore_released_after_use(self):
        """Semaphore returns to original value after all tasks complete."""
        sem = await _get_semaphore()
        original_value = sem._value

        async def _task():
            async with sem:
                await asyncio.sleep(0.05)

        tasks = [asyncio.create_task(_task()) for _ in range(MAX_CONCURRENT_GENERATIONS)]
        await asyncio.gather(*tasks)

        assert sem._value == original_value

    async def test_sequential_acquires(self):
        """Sequential acquire/release maintains correct count."""
        sem = await _get_semaphore()
        assert sem._value == MAX_CONCURRENT_GENERATIONS

        for _ in range(MAX_CONCURRENT_GENERATIONS + 1):
            async with sem:
                assert sem._value >= 0

        assert sem._value == MAX_CONCURRENT_GENERATIONS

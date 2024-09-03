from asyncio import Event, create_task, sleep
from typing import Tuple, Hashable

from pytest import mark, param, fixture

from asyncio_multilock import MultiLock, MultiLockType, MultiLockSet


@fixture
def lock_pair() -> Tuple[MultiLockSet, MultiLock, MultiLock]:
    a = MultiLock()
    b = MultiLock()
    return MultiLockSet((a, b)), a, b


def test_release_not_acquired(lock_pair) -> None:
    s, a, b = lock_pair
    unknown = object()
    s.release(unknown)


@mark.parametrize(["type"], [param(type) for type in MultiLockType])
def test_acquire_nowait_ok_when_unlocked(lock_pair, type: MultiLockType) -> None:
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    acquired = s.acquire_nowait(type)
    assert acquired
    assert a.locked is type
    assert b.locked is type
    assert s.locked is type

    s.release(acquired)
    assert not a.locked
    assert not b.locked
    assert not s.locked


@mark.parametrize(["type"], [param(type) for type in MultiLockType])
def test_acquire_nowait_fail_when_exclusive(lock_pair, type: MultiLockType) -> None:
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    exclusive = a.acquire_nowait(MultiLockType.EXCLUSIVE)
    assert exclusive
    assert a.locked is MultiLockType.EXCLUSIVE
    assert not b.locked
    assert s.locked is MultiLockType.EXCLUSIVE

    assert not s.acquire_nowait(type)
    assert a.locked is MultiLockType.EXCLUSIVE
    assert not b.locked
    assert s.locked is MultiLockType.EXCLUSIVE

    a.release(exclusive)
    assert not a.locked
    assert not b.locked
    assert not s.locked


@mark.parametrize(
    ["type"], [param(MultiLockType.SHARED), param(MultiLockType.EXCLUSIVE)]
)
def test_acquire_nowait_fail_exclusive_when_locked(
    lock_pair, type: MultiLockType
) -> None:
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    acquired = a.acquire_nowait(type)
    assert acquired
    assert a.locked is type
    assert not b.locked
    assert s.locked is type

    assert not s.acquire_nowait(MultiLockType.EXCLUSIVE)
    assert a.locked is type
    assert not b.locked
    assert s.locked is type

    a.release(acquired)
    assert not a.locked
    assert not b.locked
    assert not s.locked


def test_acquire_nowait_ok_shared_when_shared(lock_pair) -> None:
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    inner = a.acquire_nowait(MultiLockType.SHARED)
    assert inner
    assert a.locked is MultiLockType.SHARED
    assert not b.locked
    assert s.locked is MultiLockType.SHARED

    outer = s.acquire_nowait(MultiLockType.SHARED)
    assert outer
    assert a.locked is MultiLockType.SHARED
    assert b.locked is MultiLockType.SHARED
    assert s.locked is MultiLockType.SHARED

    a.release(inner)
    assert a.locked is MultiLockType.SHARED
    assert b.locked is MultiLockType.SHARED
    assert s.locked is MultiLockType.SHARED

    s.release(outer)
    assert not a.locked
    assert not b.locked
    assert not s.locked


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_acquire_immediate_when_unlocked(lock_pair, type: MultiLockType) -> None:
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    acquired = await s.acquire(type)
    assert acquired
    assert a.locked is type
    assert b.locked is type
    assert s.locked is type

    s.release(acquired)
    assert not a.locked
    assert not b.locked
    assert not s.locked


# @mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_acquire_wait_when_exclusive(lock_pair, type: MultiLockType) -> None:
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    exclusive = a.acquire_nowait(MultiLockType.EXCLUSIVE)
    assert exclusive
    assert a.locked is MultiLockType.EXCLUSIVE
    assert not b.locked
    assert s.locked is MultiLockType.EXCLUSIVE

    handle = object()
    event = Event()
    task = create_task(s.acquire(type, handle, event))
    while any(event not in lock._notify for lock in (a, b)):
        await sleep(0)

    a.release(exclusive)
    assert await task is handle
    assert a.locked is type
    assert b.locked is type
    assert s.locked is type

    s.release(handle)
    assert not a.locked
    assert not b.locked
    assert not s.locked


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_acquire_wait_exclusive_when_locked(lock_pair, type: MultiLockType):
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    acquired = await s.acquire(type)
    assert acquired
    assert a.locked is type
    assert b.locked is type
    assert s.locked is type

    exclusive = object()
    acquiring = Event()

    async def acquire() -> Hashable:
        acquiring.set()
        return await s.acquire(MultiLockType.EXCLUSIVE, exclusive)

    task = create_task(acquire())
    await acquiring.wait()

    s.release(acquired)
    assert await task is exclusive
    assert a.locked is MultiLockType.EXCLUSIVE
    assert b.locked is MultiLockType.EXCLUSIVE
    assert s.locked is MultiLockType.EXCLUSIVE

    s.release(exclusive)
    assert not a.locked
    assert not b.locked
    assert not s.locked


@mark.timeout(3)
async def test_acquire_immediate_shared_when_shared(lock_pair):
    s, a, b = lock_pair
    primary = await s.acquire(MultiLockType.SHARED)
    assert primary
    assert a.locked is MultiLockType.SHARED
    assert b.locked is MultiLockType.SHARED
    assert s.locked is MultiLockType.SHARED

    secondary = await s.acquire(MultiLockType.SHARED)
    assert secondary
    assert a.locked is MultiLockType.SHARED
    assert b.locked is MultiLockType.SHARED
    assert s.locked is MultiLockType.SHARED

    s.release(primary)
    assert a.locked is MultiLockType.SHARED
    assert b.locked is MultiLockType.SHARED
    assert s.locked is MultiLockType.SHARED

    s.release(secondary)
    assert not s.locked


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_notify_immediate_when_unlocked(lock_pair, type: MultiLockType):
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    with s.notify(type) as available:
        assert available.is_set()


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_notify_wait_when_exclusive(lock_pair, type: MultiLockType):
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    handle = s.acquire_nowait(MultiLockType.EXCLUSIVE)
    assert handle
    assert a.locked is MultiLockType.EXCLUSIVE
    assert b.locked is MultiLockType.EXCLUSIVE
    assert s.locked is MultiLockType.EXCLUSIVE

    with s.notify(type) as available:
        assert not available.is_set()
        s.release(handle)
        assert available.is_set()


@mark.timeout(3)
@mark.parametrize(
    ["type"], [param(MultiLockType.SHARED), param(MultiLockType.EXCLUSIVE)]
)
async def test_notify_wait_exclusive_when_locked(lock_pair, type: MultiLockType):
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    handle = s.acquire_nowait(type)
    assert handle
    assert a.locked is type
    assert b.locked is type
    assert s.locked is type

    with s.notify(MultiLockType.EXCLUSIVE) as available:
        assert not available.is_set()
        s.release(handle)
        assert available.is_set()


@mark.timeout(3)
async def test_notify_immediate_shared_when_shared(lock_pair):
    s, a, b = lock_pair
    assert not a.locked
    assert not b.locked
    assert not s.locked

    assert s.acquire_nowait(MultiLockType.SHARED)
    assert a.locked is MultiLockType.SHARED
    assert b.locked is MultiLockType.SHARED
    assert s.locked is MultiLockType.SHARED

    with s.notify(MultiLockType.SHARED) as available:
        assert available.is_set()

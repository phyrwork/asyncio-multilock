from asyncio import Event, create_task, sleep

from pytest import mark, param

from asyncio_multilock import MultiLock, MultiLockType


def test_release_not_acquired() -> None:
    lock = MultiLock()
    unknown = object()
    lock.release(unknown)


@mark.parametrize(["type"], [param(type) for type in MultiLockType])
def test_acquire_nowait_ok_when_unlocked(type: MultiLockType) -> None:
    lock = MultiLock()
    assert not lock.locked

    acquired = lock.acquire_nowait(type)
    assert acquired
    assert lock.locked is type

    lock.release(acquired)
    assert not lock.locked


@mark.parametrize(["type"], [param(type) for type in MultiLockType])
def test_acquire_nowait_fail_when_exclusive(type: MultiLockType) -> None:
    lock = MultiLock()
    exclusive = lock.acquire_nowait(MultiLockType.EXCLUSIVE)
    assert exclusive
    assert lock.locked is MultiLockType.EXCLUSIVE

    assert not lock.acquire_nowait(type)
    assert lock.locked is MultiLockType.EXCLUSIVE

    lock.release(exclusive)
    assert not lock.locked


@mark.parametrize(
    ["type"], [param(MultiLockType.SHARED), param(MultiLockType.EXCLUSIVE)]
)
def test_acquire_nowait_fail_exclusive_when_locked(type: MultiLockType) -> None:
    lock = MultiLock()
    acquired = lock.acquire_nowait(type)
    assert acquired
    assert lock.locked is type

    assert not lock.acquire_nowait(MultiLockType.EXCLUSIVE)
    assert lock.locked is type

    lock.release(acquired)
    assert not lock.locked


def test_acquire_nowait_ok_shared_when_shared() -> None:
    lock = MultiLock()

    primary = lock.acquire_nowait(MultiLockType.SHARED)
    assert primary
    assert lock.locked is MultiLockType.SHARED

    secondary = lock.acquire_nowait(MultiLockType.SHARED)
    assert secondary
    assert lock.locked is MultiLockType.SHARED

    lock.release(primary)
    assert lock.locked is MultiLockType.SHARED

    lock.release(secondary)
    assert not lock.locked


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_acquire_immediate_when_unlocked(type: MultiLockType) -> None:
    lock = MultiLock()
    assert not lock.locked

    acquired = await lock.acquire(type)
    assert acquired
    assert lock.locked is type

    lock.release(acquired)
    assert not lock.locked


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_acquire_wait_when_exclusive(type: MultiLockType) -> None:
    lock = MultiLock()
    exclusive = await lock.acquire(MultiLockType.EXCLUSIVE)
    assert exclusive
    assert lock.locked is MultiLockType.EXCLUSIVE

    handle = object()
    event = Event()
    task = create_task(lock.acquire(type, handle, event))
    while event not in lock._notify:
        await sleep(0)

    lock.release(exclusive)
    assert await task is handle

    lock.release(handle)
    assert not lock.locked


@mark.timeout(3)
@mark.parametrize(
    ["type"], [param(MultiLockType.SHARED), param(MultiLockType.EXCLUSIVE)]
)
async def test_acquire_wait_exclusive_when_locked(type: MultiLockType):
    lock = MultiLock()
    acquired = await lock.acquire(type)
    assert acquired
    assert lock.locked is type

    exclusive = object()
    event = Event()
    task = create_task(lock.acquire(MultiLockType.EXCLUSIVE, exclusive, event))
    while event not in lock._notify:
        await sleep(0)

    lock.release(acquired)
    assert await task is exclusive

    lock.release(exclusive)
    assert not lock.locked


@mark.timeout(3)
async def test_acquire_immediate_shared_when_shared():
    lock = MultiLock()
    primary = await lock.acquire(MultiLockType.SHARED)
    assert primary
    assert lock.locked is MultiLockType.SHARED

    secondary = await lock.acquire(MultiLockType.SHARED)
    assert secondary
    assert lock.locked is MultiLockType.SHARED

    lock.release(primary)
    assert lock.locked is MultiLockType.SHARED

    lock.release(secondary)
    assert not lock.locked


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_notify_immediate_when_unlocked(type: MultiLockType):
    lock = MultiLock()
    assert not lock.locked

    with lock.notify(type) as available:
        assert available.is_set()


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_notify_wait_when_exclusive(type: MultiLockType):
    lock = MultiLock()
    handle = lock.acquire_nowait(MultiLockType.EXCLUSIVE)
    assert handle
    assert lock.locked is MultiLockType.EXCLUSIVE

    with lock.notify(type) as available:
        assert not available.is_set()
        lock.release(handle)
        assert available.is_set()


@mark.timeout(3)
@mark.parametrize(
    ["type"], [param(MultiLockType.SHARED), param(MultiLockType.EXCLUSIVE)]
)
async def test_notify_wait_exclusive_when_locked(type: MultiLockType):
    lock = MultiLock()
    handle = lock.acquire_nowait(type)
    assert handle
    assert lock.locked is type

    with lock.notify(MultiLockType.EXCLUSIVE) as available:
        assert not available.is_set()
        lock.release(handle)
        assert available.is_set()


@mark.timeout(3)
async def test_notify_immediate_shared_when_shared():
    lock = MultiLock()
    assert lock.acquire_nowait(MultiLockType.SHARED)
    assert lock.locked is MultiLockType.SHARED

    with lock.notify(MultiLockType.SHARED) as available:
        assert available.is_set()


@mark.timeout(3)
@mark.parametrize(["type"], [param(type) for type in MultiLockType])
async def test_context(type: MultiLockType):
    lock = MultiLock()
    assert not lock.locked

    async with lock.context(type) as acquired:
        assert acquired
        assert lock.locked is type

    assert not lock.locked

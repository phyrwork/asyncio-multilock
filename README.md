# asyncio-multilock

[![asyncio-multilock](https://circleci.com/gh/phyrwork/asyncio-multilock/tree/main.svg?style=svg)](https://app.circleci.com/pipelines/github/phyrwork/asyncio-multilock?branch=main)

`asyncio_multilock` provides `MultiLock`, an `asyncio` based lock with built-in
shared/exclusive mode semantics.

`MultiLock.locked` can be in one of three states:

1. `None` - not locked;
2. `MultiLockType.SHARED` - acquired one or more times in shared mode;
3. `MultiLockType.EXCLUSIVE` - acquired one time in exclusive mode.

When a lock is acquired, a `Hashable` handle is returned which uniquely identifies
the acquisition. This handle is used to release the acquisition.

```python
from asyncio import create_task, sleep
from asyncio_multilock import MultiLock, MultiLockType

lock = MultiLock()
assert not lock.locked

shared1 = await lock.acquire(MultiLockType.SHARED)
assert lock.locked is MultiLockType.SHARED

shared2 = await lock.acquire(MultiLockType.SHARED)

async def wait_release_shared(delay: float) -> None:
    await sleep(delay)
    lock.release(shared1)
    lock.release(shared2)
create_task(wait_release_shared(3))

# Acquisition context manager.
async with lock.context(MultiLockType.EXCLUSIVE) as exclusive:
    # Blocked for 3 seconds.
    assert lock.locked is MultiLockType.EXCLUSIVE
```

The lock can also be acquired synchronously, returning no handle if the acquisition
fails.

```python
from asyncio_multilock import MultiLock, MultiLockType

lock = MultiLock()
assert not lock.locked

shared = lock.acquire_nowait(MultiLockType.SHARED)
assert shared

exclusive = lock.acquire_nowait(MultiLockType.EXCLUSIVE)
assert not exclusive

assert lock.locked is MultiLockType.SHARED
```

The lock can also be monitored for when a given lock type is next acquirable.

```python
from asyncio_multilock import MultiLock, MultiLockType

lock = MultiLock()

async with lock.notify(MultiLockType.SHARED) as event:
    await event.wait()
    print("shared lock is acquirable")
    event.clear()
```

from __future__ import annotations

from asyncio import Event
from contextlib import asynccontextmanager, contextmanager
from enum import IntEnum
from functools import reduce
from typing import AsyncIterator, Dict, Hashable, Iterator, Optional

__sentinel__ = object()


class LockError(Exception):
    ...


class EventUsedError(LockError):
    ...


class HandleUsedError(LockError):
    ...


class MultiLockType(IntEnum):
    # 0 not used so that type is always truthy.
    SHARED = 1
    EXCLUSIVE = 2

    @staticmethod
    def max(a: MultiLockType, b: MultiLockType) -> MultiLockType:
        if a > b:
            return b
        return a


class MultiLock:
    """Shared/exclusive mode lock.

    An asynchronous lock with built-in shared/exclusive mode semantics.

    The lock may be in one state from
      - Not locked
      - Acquired one more times in shared mode
      - Acquired one time in exclusive mode

    Handles uniquely represent an acquirer. A handle may only be used for one
    acquisition at any given moment.

    Events notify listeners as to when the lock may be acquired with the given mode.

    Both handles and events may be optionally provided when interacting with the lock.
    If not given they will be created and returned as appropriate.
    """

    def __init__(self):
        self._locked: Optional[MultiLockType] = __sentinel__  # type: ignore
        self._acquire: Dict[Hashable, MultiLockType] = {}
        self._notify: Dict[Event, MultiLockType] = {}

    @property
    def locked(self) -> Optional[MultiLockType]:
        """Lock state.

        None if not locked. Acquired lock type otherwise.
        """
        if self._locked is __sentinel__:
            self._locked = (
                None
                if not self._acquire
                else reduce(MultiLockType.max, self._acquire.values())
            )
        return self._locked

    @contextmanager
    def notify(
        self, type: MultiLockType, event: Optional[Event] = None
    ) -> Iterator[Event]:
        """Context in which event is set when given lock type is acquirable.

        :param type: Lock type.
        :param event: User-specified lock type acquirable event.
        :return: Lock type acquirable event.
        """
        if not event:
            event = Event()
        elif event in self._notify:
            raise EventUsedError(f"{id(self)}: event {id(event)} already in notify")
        self._notify[event] = type
        try:
            if not self.locked or MultiLockType.EXCLUSIVE not in (self.locked, type):
                event.set()
            yield event
        finally:
            del self._notify[event]

    async def wait(self, type: MultiLockType, event: Optional[Event]) -> None:
        """Wait for given lock type to be acquirable.

        :param type: Lock type.
        :param event: User-specified lock type acquirable event.
        """
        with self.notify(type, event) as event:
            assert event
            await event.wait()

    def acquire_nowait(
        self, type: MultiLockType, handle: Optional[Hashable] = None
    ) -> Optional[Hashable]:
        """Acquire lock with given type (non-blocking).

        :param type: Lock type.
        :param handle: User-specified lock handle.
        :return: Handle if lock is acquired. None otherwise.
        """
        if self.locked and MultiLockType.EXCLUSIVE in (self.locked, type):
            return None
        if handle is None:
            handle = object()
        elif handle in self._acquire:
            raise HandleUsedError(
                f"{id(self)}: handle {id(handle)} already in acquired"
            )
        self._acquire[handle] = type
        self._locked = __sentinel__  # type: ignore
        return handle

    async def acquire(
        self,
        type: MultiLockType,
        handle: Optional[Hashable] = None,
        event: Optional[Event] = None,
    ) -> Hashable:
        """Acquire lock with given type (blocking).

        :param type: Lock type.
        :param handle: User-specified lock handle.
        :param event: User-specified lock type acquirable event.
        :return: Handle if lock is acquired. None otherwise.
        """
        with self.notify(type, event) as event:
            assert event
            if not handle:
                handle = object()
            while not self.acquire_nowait(type, handle):
                await event.wait()
                event.clear()
            return handle

    def release(self, handle: Hashable) -> None:
        self._acquire.pop(handle, None)  # OK to release unknown handle.
        self._locked = __sentinel__  # type: ignore
        for handle, type in self._notify.items():
            if not self.locked or MultiLockType.EXCLUSIVE not in (self.locked, type):
                handle.set()

    @asynccontextmanager
    async def context(
        self,
        type: MultiLockType,
        handle: Optional[Hashable] = None,
        event: Optional[Event] = None,
    ) -> AsyncIterator[Hashable]:
        """Acquire lock with given type for duration of context.

        :param type: Lock type.
        :param handle: User-specified lock handle.
        :param event: User-specified lock type acquirable event.
        :return: Handle if lock is acquired. None otherwise.
        """
        handle = await self.acquire(type, handle, event)
        try:
            yield handle
        finally:
            self.release(handle)

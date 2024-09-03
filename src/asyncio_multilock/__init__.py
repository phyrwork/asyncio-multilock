from __future__ import annotations

from asyncio import Event
from contextlib import asynccontextmanager, contextmanager, ExitStack
from enum import IntEnum
from functools import reduce
from typing import (
    AsyncIterator,
    Dict,
    Hashable,
    Iterator,
    Optional,
    FrozenSet,
    Protocol,
)


class LockError(Exception): ...


class EventUsedError(LockError): ...


class HandleUsedError(LockError): ...


class MultiLockType(IntEnum):
    NONE = 0
    SHARED = 1
    EXCLUSIVE = 2

    @staticmethod
    def max(a: MultiLockType, b: MultiLockType) -> MultiLockType:
        return a if a > b else b

    def excludes(self, other: MultiLockType) -> bool:
        if self is MultiLockType.NONE:
            return False

        return MultiLockType.EXCLUSIVE in (self, other)

    def includes(self, other: MultiLockType) -> bool:
        if self is MultiLockType.NONE:
            return True

        return MultiLockType.EXCLUSIVE not in (self, other)


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

    def __init__(self) -> None:
        self._locked: Optional[MultiLockType] = None
        self._acquire: Dict[Hashable, MultiLockType] = {}
        self._notify: Dict[Event, MultiLockType] = {}

    @property
    def locked(self) -> MultiLockType:
        """Lock state.

        None if not locked. Acquired lock type otherwise.
        """
        if self._locked is None:
            self._locked = reduce(
                MultiLockType.max, self._acquire.values(), MultiLockType.NONE
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
        if event is None:
            event = Event()
        elif event in self._notify:
            raise EventUsedError(f"{id(self)}: event {id(event)} already in notify")
        self._notify[event] = type
        try:
            if self.locked.includes(type):
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
        if self.locked.excludes(type):
            return None
        if handle is None:
            handle = object()
        elif handle in self._acquire:
            raise HandleUsedError(
                f"{id(self)}: handle {id(handle)} already in acquired"
            )
        self._acquire[handle] = type
        self._locked = None
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
        self._locked = None
        for handle, type in self._notify.items():
            if self.locked.includes(type):
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


class MultiLockSet(FrozenSet[MultiLock]):
    @property
    def locked(self) -> MultiLockType:
        return reduce(
            MultiLockType.max, (lock.locked for lock in self), MultiLockType.NONE
        )

    @contextmanager
    def notify(
        self, type: MultiLockType, event: Optional[Event] = None
    ) -> Iterator[Event]:
        if event is None:
            event = Event()

        with ExitStack() as stack:
            for lock in self:
                stack.enter_context(lock.notify(type, event))

            yield event

    async def wait(self, type: MultiLockType, event: Optional[Event]) -> None:
        with self.notify(type, event) as event:
            while await event.wait():
                if self.locked.includes(type):
                    return

    def acquire_nowait(
        self, type: MultiLockType, handle: Optional[Hashable] = None
    ) -> Optional[Hashable]:
        if self.locked.excludes(type):
            return None

        if handle is None:
            handle = object()

        with ExitStack() as stack:
            for lock in self:
                lock.acquire_nowait(type, handle)

                def release() -> None:
                    lock.release(handle)

                stack.callback(release)

            stack.pop_all()

        return handle

    async def acquire(
        self,
        type: MultiLockType,
        handle: Optional[Hashable] = None,
        event: Optional[Event] = None,
    ) -> Hashable:
        if not handle:
            handle = object()

        if event is None:
            event = Event()

        with self.notify(type, event) as event:
            while not self.acquire_nowait(type, handle):
                await event.wait()
                event.clear()

        return handle

    def release(self, handle: Hashable) -> None:
        for lock in self:
            lock.release(handle)


class MultiLockable(Protocol):
    """Shared/exclusive mode lock interface."""

    @property
    def locked(self) -> MultiLockType:
        """Lock state.

        None if not locked. Acquired lock type otherwise.
        """

    @contextmanager
    def notify(
        self, __type: MultiLockType, __event: Optional[Event] = None
    ) -> Iterator[Event]:
        """Context in which event is set when given lock type is acquirable.

        :param __type: Lock type.
        :param __event: User-specified lock type acquirable event.
        :return: Lock type acquirable event.
        """

    async def wait(self, __type: MultiLockType, __event: Optional[Event]) -> None:
        """Wait for given lock type to be acquirable.

        :param __type: Lock type.
        :param __event: User-specified lock type acquirable event.
        """

    def acquire_nowait(
        self, __type: MultiLockType, __handle: Optional[Hashable] = None
    ) -> Optional[Hashable]:
        """Acquire lock with given type (non-blocking).

        :param __type: Lock type.
        :param __handle: User-specified lock handle.
        :return: Handle if lock is acquired. None otherwise.
        """

    async def acquire(
        self,
        __type: MultiLockType,
        __handle: Optional[Hashable] = None,
        __event: Optional[Event] = None,
    ) -> Hashable:
        """Acquire lock with given type (blocking).

        :param __type: Lock type.
        :param __handle: User-specified lock handle.
        :param __event: User-specified lock type acquirable event.
        :return: Handle if lock is acquired. None otherwise.
        """

    def release(self, __handle: Hashable) -> None: ...

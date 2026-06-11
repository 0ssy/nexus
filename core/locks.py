import asyncio
import time
from typing import Dict, Optional

class DistributedLock:
    """
    Manages locks for shared resources in NEXUS.
    Prevents race conditions when multiple agents
    try to write to the same room context simultaneously.
    """
    def __init__(self):
        # room_id -> asyncio.Lock
        self._locks: Dict[str, asyncio.Lock] = {}
        # room_id -> agent_id (who holds the lock)
        self._holders: Dict[str, str] = {}
        # room_id -> timestamp (when lock was acquired)
        self._acquired_at: Dict[str, float] = {}
        # Maximum time a lock can be held (seconds)
        self.lock_timeout = 30

    def _get_lock(self, resource_id: str) -> asyncio.Lock:
        if resource_id not in self._locks:
            self._locks[resource_id] = asyncio.Lock()
        return self._locks[resource_id]

    async def acquire(self, resource_id: str, agent_id: str, timeout: float = 10.0) -> bool:
        """
        Acquire a lock on a resource.
        Returns True if lock acquired, False if timeout.
        """
        lock = self._get_lock(resource_id)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            self._holders[resource_id] = agent_id
            self._acquired_at[resource_id] = time.time()
            return True
        except asyncio.TimeoutError:
            return False

    async def release(self, resource_id: str, agent_id: str) -> bool:
        """
        Release a lock on a resource.
        Only the agent holding the lock can release it.
        """
        lock = self._get_lock(resource_id)
        holder = self._holders.get(resource_id)

        if holder != agent_id:
            return False

        if lock.locked():
            lock.release()

        self._holders.pop(resource_id, None)
        self._acquired_at.pop(resource_id, None)
        return True

    async def force_release(self, resource_id: str) -> bool:
        """
        Force release a lock — used when a lock has been held too long.
        """
        lock = self._get_lock(resource_id)
        if lock.locked():
            lock.release()
        self._holders.pop(resource_id, None)
        self._acquired_at.pop(resource_id, None)
        return True

    def is_locked(self, resource_id: str) -> bool:
        lock = self._locks.get(resource_id)
        return lock.locked() if lock else False

    def get_holder(self, resource_id: str) -> Optional[str]:
        return self._holders.get(resource_id)

    def is_stale(self, resource_id: str) -> bool:
        """Check if a lock has been held longer than the timeout."""
        acquired = self._acquired_at.get(resource_id)
        if not acquired:
            return False
        return (time.time() - acquired) > self.lock_timeout

    async def cleanup_stale_locks(self):
        """Release any locks held longer than lock_timeout."""
        stale = [r for r in self._acquired_at if self.is_stale(r)]
        for resource_id in stale:
            await self.force_release(resource_id)
        return len(stale)

    def get_status(self) -> dict:
        return {
            "total_locks": len(self._locks),
            "active_locks": sum(1 for l in self._locks.values() if l.locked()),
            "holders": dict(self._holders),
            "stale_count": sum(1 for r in self._acquired_at if self.is_stale(r))
        }


class RoomWriteQueue:
    """
    Queues writes to a room so agents never write simultaneously.
    Agents submit writes and they execute in order, one at a time.
    """
    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._workers: Dict[str, asyncio.Task] = {}
        self._write_counts: Dict[str, int] = {}

    def _get_queue(self, room_id: str) -> asyncio.Queue:
        if room_id not in self._queues:
            self._queues[room_id] = asyncio.Queue()
            self._write_counts[room_id] = 0
        return self._queues[room_id]

    async def submit_write(self, room_id: str, write_fn, *args, **kwargs):
        """
        Submit a write operation to the room queue.
        Returns the result of the write once executed.
        """
        future = asyncio.get_event_loop().create_future()
        queue = self._get_queue(room_id)
        await queue.put((write_fn, args, kwargs, future))

        # Start worker if not running
        if room_id not in self._workers or self._workers[room_id].done():
            self._workers[room_id] = asyncio.create_task(
                self._process_queue(room_id)
            )

        return await future

    async def _process_queue(self, room_id: str):
        queue = self._queues[room_id]
        while not queue.empty():
            write_fn, args, kwargs, future = await queue.get()
            try:
                result = await write_fn(*args, **kwargs)
                self._write_counts[room_id] += 1
                if not future.done():
                    future.set_result(result)
            except Exception as e:
                if not future.done():
                    future.set_exception(e)
            finally:
                queue.task_done()

    def get_queue_depth(self, room_id: str) -> int:
        queue = self._queues.get(room_id)
        return queue.qsize() if queue else 0

    def get_write_count(self, room_id: str) -> int:
        return self._write_counts.get(room_id, 0)


# Global instances
lock_manager = DistributedLock()
write_queue = RoomWriteQueue()
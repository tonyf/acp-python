from typing import AsyncIterator, TypeVar, List
import asyncio

T = TypeVar("T")


async def join_iters(
    *generators: AsyncIterator[T],
) -> AsyncIterator[T]:
    """Yields from multiple async generators in parallel as soon as they produce values."""
    tasks = {asyncio.create_task(gen.__anext__()): gen for gen in generators}

    while tasks:
        done, _ = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            gen = tasks.pop(task)
            try:
                value = task.result()
                yield value
                # Schedule the next item from the generator
                next_task = asyncio.create_task(gen.__anext__())
                tasks[next_task] = gen
            except StopAsyncIteration:
                continue  # Generator is exhausted, don't reschedule

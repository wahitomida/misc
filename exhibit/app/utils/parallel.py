# -*- coding: utf-8 -*-
"""並列実行ユーティリティ"""

import asyncio
from typing import Callable, Any
from app.config import settings


async def run_parallel(
    tasks: list[Callable],
    max_concurrent: int = None,
) -> list[Any]:
    """タスクを並列実行（セマフォで同時実行数を制御）"""
    if max_concurrent is None:
        max_concurrent = settings.MAX_PARALLEL_SEARCHES

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _run_with_semaphore(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*[_run_with_semaphore(t) for t in tasks])

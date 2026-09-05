import time
import logging
import functools
import asyncio

def log_execution_time(func):
    """
    Decorator to log the execution time of any function (sync or async).
    Usage:
        @log_execution_time
        def my_function(...): ...
    """
    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start_time
        logger.info(f"Execution time for {func.__qualname__}: {duration:.4f} seconds")
        return result

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        start_time = time.perf_counter()
        result = await func(*args, **kwargs)
        duration = time.perf_counter() - start_time
        logger.info(f"Execution time for {func.__qualname__}: {duration:.4f} seconds")
        return result

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper

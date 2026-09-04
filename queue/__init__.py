"""
Sasta Maal Distributed Queue Layer.

Note: To prevent collision with Python standard library 'queue' when this workspace
is in sys.path, standard library queue attributes are safely imported and re-exported here,
and pipeline components are lazily loaded.
"""
import os
import sys
import importlib.util

# Re-export Python standard library 'queue' symbols so standard library and 3rd party
# modules (e.g. threading, concurrent.futures, urllib3, pytest) continue to work seamlessly.
_stdlib_queue_path = os.path.join(os.path.dirname(os.__file__), 'queue.py')
if os.path.exists(_stdlib_queue_path):
    _spec = importlib.util.spec_from_file_location('_stdlib_queue', _stdlib_queue_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    for _attr in dir(_mod):
        if not _attr.startswith('_'):
            globals()[_attr] = getattr(_mod, _attr)

def __getattr__(name):
    if name == "RedisConnectionManager":
        from .redis_client import RedisConnectionManager
        return RedisConnectionManager
    elif name == "DealProducer":
        from .producer import DealProducer
        return DealProducer
    elif name == "DealPipelineWorker":
        from .worker import DealPipelineWorker
        return DealPipelineWorker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "RedisConnectionManager", 
    "DealProducer", 
    "DealPipelineWorker",
    "Queue",
    "LifoQueue",
    "PriorityQueue",
    "SimpleQueue",
    "Empty",
    "Full"
]

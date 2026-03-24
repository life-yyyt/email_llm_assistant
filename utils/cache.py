# -*- coding: utf-8 -*-
"""
简单 LRU 风格缓存，用于分类结果、生成结果等，避免重复调用模型。
"""

from typing import Any, Optional
from collections import OrderedDict
import hashlib
import threading


class SimpleCache:
    """线程安全的键值缓存，支持最大容量与 TTL（此处仅做容量限制，TTL 可选扩展）。"""

    def __init__(self, max_size: int = 500):
        self._max_size = max(1, max_size)
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.RLock()

    def _key(self, raw: str) -> str:
        """对长文本做短 hash 作为 key。"""
        return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:32]

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            else:
                while len(self._data) >= self._max_size:
                    self._data.popitem(last=False)
            self._data[key] = value

    def get_or_set(self, key: str, factory) -> Any:
        """若 key 存在则返回缓存值，否则调用 factory() 并缓存。"""
        v = self.get(key)
        if v is not None:
            return v
        v = factory()
        self.set(key, v)
        return v

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

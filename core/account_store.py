# -*- coding: utf-8 -*-
"""
内存中的多邮箱账号管理：支持添加、删除、列表、当前选中账号；
支持从本地 JSON 文件加载/保存，实现账号记忆（关闭程序后下次启动自动恢复）。
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional
import threading
import os
import json


@dataclass
class AccountItem:
    """单个邮箱账号信息。"""
    email: str
    password: str  # 或授权码
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    use_ssl: bool = True


def _default_accounts_path() -> str:
    """默认账号配置文件路径（不依赖数据库，仅 JSON 文件）。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~")
    dir_path = os.path.join(base, "EmailLLMAssistant")
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, "accounts.json")


class AccountStore:
    """多账号内存存储，线程安全；支持从 JSON 文件加载与保存。"""

    def __init__(self):
        self._accounts: List[AccountItem] = []
        self._current_index: int = 0
        self._lock = threading.RLock()
        self._file_path: Optional[str] = None  # 使用默认路径

    def _get_path(self, path: Optional[str] = None) -> str:
        return path or self._file_path or _default_accounts_path()

    def add(self, account: AccountItem) -> None:
        with self._lock:
            # 避免重复邮箱
            for a in self._accounts:
                if a.email.lower() == account.email.lower():
                    return
            self._accounts.append(account)

    def remove_by_email(self, email: str) -> bool:
        with self._lock:
            email_lower = email.strip().lower()
            for i, a in enumerate(self._accounts):
                if a.email.lower() == email_lower:
                    self._accounts.pop(i)
                    if self._current_index >= len(self._accounts) and self._current_index > 0:
                        self._current_index -= 1
                    return True
            return False

    def get_all(self) -> List[AccountItem]:
        with self._lock:
            return list(self._accounts)

    def get_current(self) -> Optional[AccountItem]:
        with self._lock:
            if not self._accounts:
                return None
            idx = max(0, min(self._current_index, len(self._accounts) - 1))
            return self._accounts[idx]

    def set_current_index(self, index: int) -> None:
        with self._lock:
            if 0 <= index < len(self._accounts):
                self._current_index = index

    def set_current_by_email(self, email: str) -> bool:
        with self._lock:
            email_lower = email.strip().lower()
            for i, a in enumerate(self._accounts):
                if a.email.lower() == email_lower:
                    self._current_index = i
                    return True
            return False

    def count(self) -> int:
        with self._lock:
            return len(self._accounts)

    def load_from_file(self, path: Optional[str] = None) -> int:
        """
        从 JSON 文件加载账号列表，追加到当前内存（不先清空，避免覆盖未保存的改动）。
        若文件不存在或为空则返回 0。
        :return: 本次加载的账号数量
        """
        file_path = self._get_path(path)
        self._file_path = file_path
        if not os.path.isfile(file_path):
            return 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return 0
            loaded = 0
            with self._lock:
                existing_emails = {a.email.lower() for a in self._accounts}
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    email = (item.get("email") or "").strip()
                    if not email or email.lower() in existing_emails:
                        continue
                    try:
                        acc = AccountItem(
                            email=email,
                            password=item.get("password") or "",
                            imap_host=item.get("imap_host") or "",
                            imap_port=int(item.get("imap_port", 993)),
                            smtp_host=item.get("smtp_host") or "",
                            smtp_port=int(item.get("smtp_port", 465)),
                            use_ssl=bool(item.get("use_ssl", True)),
                        )
                        self._accounts.append(acc)
                        existing_emails.add(email.lower())
                        loaded += 1
                    except (TypeError, ValueError):
                        continue
            return loaded
        except (json.JSONDecodeError, OSError):
            return 0

    def save_to_file(self, path: Optional[str] = None) -> bool:
        """将当前账号列表保存到 JSON 文件。密码以明文存储，请勿将文件放在共享目录。"""
        file_path = self._get_path(path)
        self._file_path = file_path
        try:
            with self._lock:
                data = [asdict(a) for a in self._accounts]
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except (OSError, TypeError):
            return False

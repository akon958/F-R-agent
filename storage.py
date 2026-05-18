from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


# ── 抽象接口 ──────────────────────────────────────────────────────────────────

class StorageBackend(ABC):
    """所有存储实现的统一接口。app.py 只调用这里的方法，不关心底层是文件还是数据库。"""

    @abstractmethod
    def load_notes(self) -> list[dict[str, Any]]:
        """返回所有观察记录，按时间倒序（最新在前）。"""
        ...

    @abstractmethod
    def save_note(self, note: dict[str, Any]) -> None:
        """把一条新记录写入存储（插入到最前面）。"""
        ...

    @abstractmethod
    def clear_notes(self) -> None:
        """清空所有记录（测试 / 重置用）。"""
        ...


# ── 本地文件实现 ──────────────────────────────────────────────────────────────

_DEFAULT_FILE = os.path.join(os.path.dirname(__file__), "family_notes.json")
_MAX_NOTES = 200  # 最多保留条数，防止文件无限增大


class LocalStorage(StorageBackend):
    """把观察记录存到本地 family_notes.json 文件。
    本地运行时关闭页面后仍保留；Streamlit Cloud 重新部署后会清除（第6步 Supabase 解决）。
    """

    def __init__(self, filepath: str = _DEFAULT_FILE) -> None:
        self._path = filepath

    def load_notes(self) -> list[dict[str, Any]]:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            # 文件损坏时安全降级，不崩溃
            return []

    def save_note(self, note: dict[str, Any]) -> None:
        notes = self.load_notes()
        notes.insert(0, note)
        notes = notes[:_MAX_NOTES]
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)

    def clear_notes(self) -> None:
        if os.path.exists(self._path):
            os.remove(self._path)


# ── Supabase 实现（第6步补全）────────────────────────────────────────────────

class SupabaseStorage(StorageBackend):
    """云端多人共享存储。第6步接入 Supabase 时在这里实现，app.py 无需改动。"""

    def __init__(self, url: str, anon_key: str) -> None:
        # 第6步：在这里初始化 supabase-py 客户端
        raise NotImplementedError("Supabase storage 将在第6步实现。")

    def load_notes(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def save_note(self, note: dict[str, Any]) -> None:
        raise NotImplementedError

    def clear_notes(self) -> None:
        raise NotImplementedError


# ── 工厂函数（唯一对外入口）─────────────────────────────────────────────────

def get_storage() -> StorageBackend:
    """返回当前应使用的存储后端。
    第6步：在这里检测 SUPABASE_URL 环境变量，有则切换到 SupabaseStorage，
    app.py 其余代码一行不用改。
    """
    # 第6步解注释：
    # supabase_url = os.getenv("SUPABASE_URL", "")
    # supabase_key = os.getenv("SUPABASE_ANON_KEY", "")
    # if supabase_url and supabase_key:
    #     return SupabaseStorage(supabase_url, supabase_key)
    return LocalStorage()


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def make_note(body: str, who: str = "我") -> dict[str, Any]:
    """构造一条标准格式的观察记录。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    avatar = who[0] if who else "我"
    return {
        "who": who,
        "when": now,
        "body": body,
        "avatar": avatar,
    }

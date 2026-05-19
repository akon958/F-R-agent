from __future__ import annotations

import csv
import json
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
ANALYSIS_HISTORY_FILE = BASE_DIR / "analysis_history.csv"
FOLLOWUP_HISTORY_FILE = BASE_DIR / "followup_history.csv"
FEEDBACK_HISTORY_FILE = BASE_DIR / "feedback_history.csv"
FAMILY_PROFILE_FILE = BASE_DIR / "family_profile.csv"
NOTES_FILE = BASE_DIR / "family_notes.json"
MAX_NOTES = 200
_LAST_ANALYSIS_SAVE_STATUS: dict[str, Any] = {
    "backend": "local_csv",
    "connected": False,
    "saved": False,
    "message": "尚未保存历史记录",
}


def get_family_id() -> str:
    return "default_family"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shanghai_tz() -> timezone | ZoneInfo:
    try:
        return ZoneInfo("Asia/Shanghai")
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=8))


def format_datetime_for_display(value: Any) -> str:
    """Format UTC/Supabase timestamps as Beijing time for page display."""
    if value in (None, ""):
        return "时间未知"
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            raw = str(value).strip()
            if not raw:
                return "时间未知"
            normalized = raw.replace("Z", "+00:00")
            if re.search(r"[+-]\d{2}$", normalized):
                normalized = f"{normalized}:00"
            try:
                dt = datetime.fromisoformat(normalized)
            except ValueError:
                dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_shanghai_tz()).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        text = str(value).strip()
        return text if text else "时间未知"


def _safe_json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return str(value)


def _json_text(value: Any) -> str:
    return json.dumps(_safe_json(value), ensure_ascii=False)


def _json_load(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:  # noqa: BLE001
        return default


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception:  # noqa: BLE001
        return []


def _append_csv_row(path: Path, row: dict[str, Any]) -> bool:
    try:
        old_rows = _read_csv_rows(path)
        headers: list[str] = []
        for source in old_rows + [row]:
            for key in source.keys():
                if key not in headers:
                    headers.append(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for old in old_rows:
                writer.writerow({key: old.get(key, "") for key in headers})
            writer.writerow({key: row.get(key, "") for key in headers})
        return True
    except Exception:  # noqa: BLE001
        return False


def _get_secret(name: str) -> str:
    try:
        import streamlit as st

        value = str(st.secrets.get(name, "")).strip()
        if value:
            return value
    except Exception:  # noqa: BLE001
        pass
    return os.getenv(name, "").strip()


def get_supabase_client() -> Any | None:
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client

        return create_client(url, key)
    except Exception:  # noqa: BLE001
        return None


def get_storage_status() -> dict[str, Any]:
    client = get_supabase_client()
    if client is None:
        return {
            "backend": "local_csv",
            "connected": False,
            "message": "当前使用本地 CSV 兜底",
        }
    return {
        "backend": "supabase",
        "connected": True,
        "message": "当前使用 Supabase 云数据库",
    }


def get_last_analysis_save_status() -> dict[str, Any]:
    return dict(_LAST_ANALYSIS_SAVE_STATUS)


def _analysis_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "family_id": get_family_id(),
        "holdings_summary": str(record.get("holdings_summary", "")),
        "family_cash": _to_float(record.get("family_cash")),
        "total_position_value": _to_float(record.get("total_position_value")),
        "cash_ratio": _to_float(record.get("cash_ratio")),
        "stock_ratio": _to_float(record.get("stock_ratio")),
        "max_position_ratio": _to_float(record.get("max_position_ratio")),
        "risk_score": _to_float(record.get("risk_score")),
        "risk_level": str(record.get("risk_level", "")),
        "main_risks": _safe_json(record.get("main_risks", [])),
        "missing_data": _safe_json(record.get("missing_data", {})),
        "data_status": _safe_json(record.get("data_status", {})),
        "pe_pb_status": str(record.get("pe_pb_status", "")),
        "financial_status": str(record.get("financial_status", "")),
        "ai_report_summary": str(record.get("ai_report_summary", "")),
        "full_agent_result": _safe_json(record.get("full_agent_result", {})),
    }


def save_analysis_history(record: dict[str, Any]) -> bool:
    global _LAST_ANALYSIS_SAVE_STATUS
    payload = _analysis_payload(record)
    client = get_supabase_client()
    if client is not None:
        try:
            client.table("analysis_history").insert(payload).execute()
            _LAST_ANALYSIS_SAVE_STATUS = {
                "backend": "supabase",
                "connected": True,
                "saved": True,
                "message": "记录已保存到云端，重新打开页面后仍可读取。",
            }
            return True
        except Exception:  # noqa: BLE001
            pass

    local_row = dict(payload)
    local_row["created_at"] = _now_iso()
    for key in ("main_risks", "missing_data", "data_status", "full_agent_result"):
        local_row[key] = _json_text(local_row.get(key))
    saved = _append_csv_row(ANALYSIS_HISTORY_FILE, local_row)
    _LAST_ANALYSIS_SAVE_STATUS = {
        "backend": "local_csv",
        "connected": False,
        "saved": saved,
        "message": (
            "本地 CSV 仅适合开发测试，Streamlit Cloud 重启或重新部署后可能丢失。"
            if saved
            else "历史记录暂时保存失败，不影响本次体检结果。"
        ),
    }
    return saved


def _normalize_analysis_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["family_cash"] = _to_float(row.get("family_cash") or row.get("家庭现金"))
    normalized["total_position_value"] = _to_float(row.get("total_position_value") or row.get("股票仓位"))
    normalized["cash_ratio"] = _to_float(row.get("cash_ratio") or row.get("现金比例"))
    normalized["stock_ratio"] = _to_float(row.get("stock_ratio") or row.get("股票仓位"))
    normalized["max_position_ratio"] = _to_float(row.get("max_position_ratio"))
    normalized["risk_score"] = _to_float(row.get("risk_score") or row.get("综合评分"))
    normalized["risk_level"] = row.get("risk_level") or row.get("风险等级") or ""
    normalized["main_risks"] = _json_load(row.get("main_risks") or row.get("主要风险"), [])
    normalized["missing_data"] = _json_load(row.get("missing_data"), {})
    normalized["data_status"] = _json_load(row.get("data_status") or row.get("数据状态"), {})
    normalized["full_agent_result"] = _json_load(row.get("full_agent_result"), {})
    normalized["created_at"] = row.get("created_at") or row.get("分析时间") or ""
    return normalized


def load_recent_analysis_history(limit: int = 5) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if client is not None:
        try:
            result = (
                client.table("analysis_history")
                .select("*")
                .eq("family_id", get_family_id())
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            data = result.data if isinstance(result.data, list) else []
            return data[:limit]
        except Exception:  # noqa: BLE001
            pass

    rows = [_normalize_analysis_row(row) for row in _read_csv_rows(ANALYSIS_HISTORY_FILE)]
    rows = list(reversed(rows))
    return rows[:limit]


def get_last_analysis_history() -> dict[str, Any] | None:
    rows = load_recent_analysis_history(limit=1)
    return rows[0] if rows else None


def save_followup_history(question: str, answer: str, related_analysis_id: int | None = None) -> bool:
    payload = {
        "family_id": get_family_id(),
        "question": str(question),
        "answer": str(answer),
        "related_analysis_id": related_analysis_id,
    }
    client = get_supabase_client()
    if client is not None:
        try:
            client.table("followup_history").insert(payload).execute()
            return True
        except Exception:  # noqa: BLE001
            pass

    local_row = dict(payload)
    local_row["created_at"] = _now_iso()
    return _append_csv_row(FOLLOWUP_HISTORY_FILE, local_row)


def load_recent_followup_history(limit: int = 10) -> list[dict[str, Any]]:
    client = get_supabase_client()
    if client is not None:
        try:
            result = (
                client.table("followup_history")
                .select("*")
                .eq("family_id", get_family_id())
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data if isinstance(result.data, list) else []
        except Exception:  # noqa: BLE001
            pass
    return list(reversed(_read_csv_rows(FOLLOWUP_HISTORY_FILE)))[:limit]


def save_feedback_history(
    feedback_rating: str = "",
    feedback_tags: list[str] | None = None,
    feedback_text: str = "",
    selected_followup_question: str = "",
) -> bool:
    payload = {
        "family_id": get_family_id(),
        "feedback_rating": feedback_rating,
        "feedback_tags": _safe_json(feedback_tags or []),
        "feedback_text": feedback_text,
        "selected_followup_question": selected_followup_question,
    }
    client = get_supabase_client()
    if client is not None:
        try:
            client.table("feedback_history").insert(payload).execute()
            return True
        except Exception:  # noqa: BLE001
            pass
    local_row = dict(payload)
    local_row["created_at"] = _now_iso()
    local_row["feedback_tags"] = _json_text(local_row["feedback_tags"])
    return _append_csv_row(FEEDBACK_HISTORY_FILE, local_row)


def save_family_profile(profile: dict[str, Any]) -> bool:
    payload = {
        "family_id": get_family_id(),
        "risk_preference": str(profile.get("risk_preference", "")),
        "report_style": str(profile.get("report_style", "")),
        "focus_topics": _safe_json(profile.get("focus_topics", [])),
        "explanation_level": str(profile.get("explanation_level", "")),
        "updated_at": _now_iso(),
    }
    client = get_supabase_client()
    if client is not None:
        try:
            client.table("family_profile").upsert(payload, on_conflict="family_id").execute()
            return True
        except Exception:  # noqa: BLE001
            pass
    local_row = dict(payload)
    local_row["focus_topics"] = _json_text(local_row["focus_topics"])
    return _append_csv_row(FAMILY_PROFILE_FILE, local_row)


def load_family_profile() -> dict[str, Any] | None:
    client = get_supabase_client()
    if client is not None:
        try:
            result = (
                client.table("family_profile")
                .select("*")
                .eq("family_id", get_family_id())
                .limit(1)
                .execute()
            )
            data = result.data if isinstance(result.data, list) else []
            return data[0] if data else None
        except Exception:  # noqa: BLE001
            pass
    rows = _read_csv_rows(FAMILY_PROFILE_FILE)
    return rows[-1] if rows else None


class StorageBackend(ABC):
    """Observation note storage used by the existing app note feature."""

    @abstractmethod
    def load_notes(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def save_note(self, note: dict[str, Any]) -> None:
        ...

    @abstractmethod
    def clear_notes(self) -> None:
        ...


class LocalStorage(StorageBackend):
    def __init__(self, filepath: Path = NOTES_FILE) -> None:
        self._path = filepath

    def load_notes(self) -> list[dict[str, Any]]:
        try:
            with self._path.open(encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            return []

    def save_note(self, note: dict[str, Any]) -> None:
        notes = self.load_notes()
        notes.insert(0, note)
        notes = notes[:MAX_NOTES]
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)

    def clear_notes(self) -> None:
        if self._path.exists():
            self._path.unlink()


class SupabaseStorage(StorageBackend):
    def __init__(self, client: Any) -> None:
        self._client = client

    def load_notes(self) -> list[dict[str, Any]]:
        try:
            result = (
                self._client.table("feedback_history")
                .select("*")
                .eq("family_id", get_family_id())
                .eq("selected_followup_question", "家庭观察记录")
                .order("created_at", desc=True)
                .limit(MAX_NOTES)
                .execute()
            )
            rows = result.data if isinstance(result.data, list) else []
        except Exception:  # noqa: BLE001
            rows = []
        notes: list[dict[str, Any]] = []
        for row in rows:
            body = row.get("feedback_text") or ""
            when = str(row.get("created_at", ""))[:16].replace("T", " ")
            notes.append({"who": "我", "when": when, "body": body, "avatar": "我"})
        return notes

    def save_note(self, note: dict[str, Any]) -> None:
        save_feedback_history(
            feedback_text=str(note.get("body", "")),
            selected_followup_question="家庭观察记录",
        )

    def clear_notes(self) -> None:
        return None


def get_storage() -> StorageBackend:
    client = get_supabase_client()
    if client is not None:
        return SupabaseStorage(client)
    return LocalStorage()


def make_note(body: str, who: str = "我") -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    avatar = who[0] if who else "我"
    return {
        "who": who,
        "when": now,
        "body": body,
        "avatar": avatar,
    }

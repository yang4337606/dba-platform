"""Local knowledge base for learned patterns and case history. JSON file storage."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge")
PATTERNS_FILE = os.path.join(KNOWLEDGE_DIR, "patterns.json")
CASES_FILE = os.path.join(KNOWLEDGE_DIR, "cases.json")
CONFIG_FILE = os.path.join(KNOWLEDGE_DIR, "config.json")
BACKUP_DIR = os.path.join(KNOWLEDGE_DIR, "backups")
DISTILL_LOG_FILE = os.path.join(KNOWLEDGE_DIR, "distillation_log.json")
MAX_BACKUPS = 10

# Confidence lifecycle constants
INITIAL_CONFIDENCE = 0.35
HIT_BOOST = 0.05
MISS_DECAY = -0.03
MISS_STREAK_THRESHOLD = 3
STALE_DAYS = 90
STALE_DECAY = -0.10
ACTIVE_THRESHOLD = 0.65
REJECT_THRESHOLD = 0.20
AUTO_PROMOTE_HITS = 10

# Simple obfuscation key derived from machine-id or fallback
_OBFUSCATION_KEY = hashlib.sha256(
    os.environ.get("SECRET_KEY", "awr-clean-default-key").encode()
).digest()


def _obfuscate(plaintext: str) -> str:
    """Simple XOR-based obfuscation for API keys at rest.

    This is NOT cryptographic encryption — it prevents casual exposure
    (e.g. someone opening the JSON file) but not a determined attacker.
    For production use, integrate a proper secrets manager.
    """
    data = plaintext.encode()
    key = _OBFUSCATION_KEY
    obfuscated = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return "obf:" + base64.b64encode(obfuscated).decode()


def _deobfuscate(stored: str) -> str:
    """Reverse the obfuscation."""
    if not stored.startswith("obf:"):
        # Legacy plaintext — return as-is
        return stored
    raw = base64.b64decode(stored[4:])
    key = _OBFUSCATION_KEY
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode()


class KnowledgeBase:
    """Manages patterns and cases stored in JSON files."""

    def __init__(self, knowledge_dir: str = KNOWLEDGE_DIR) -> None:
        self.knowledge_dir = knowledge_dir
        os.makedirs(self.knowledge_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._patterns_cache: dict | None = None
        self._patterns_cache_mtime: float = 0

    # === Config ===

    def load_config(self) -> dict[str, str]:
        """Load LLM config. Env vars override file values."""
        config = self._read_json(CONFIG_FILE, {})
        stored_key = config.get("api_key", "")
        # Deobfuscate stored key
        api_key = _deobfuscate(stored_key) if stored_key else ""
        return {
            "base_url": os.environ.get("LLM_BASE_URL") or config.get("base_url", ""),
            "api_key": os.environ.get("LLM_API_KEY") or api_key,
            "model": os.environ.get("LLM_MODEL") or config.get("model", ""),
        }

    def save_config(self, base_url: str, api_key: str, model: str) -> None:
        """Save LLM config to file. API key is obfuscated at rest."""
        with self._lock:
            existing = self._read_json(CONFIG_FILE, {})
            existing["base_url"] = base_url
            if api_key:
                existing["api_key"] = _obfuscate(api_key)
            existing["model"] = model
            self._write_json(CONFIG_FILE, existing)

    # === Patterns ===

    def get_active_patterns(self) -> list[dict]:
        """Get all active patterns for LLM context."""
        data = self._read_patterns_cached()
        return [p for p in data.get("patterns", []) if p.get("status") in ("active", "observed")]

    def get_all_patterns(self) -> list[dict]:
        data = self._read_patterns_cached()
        return data.get("patterns", [])

    def _read_patterns_cached(self) -> dict:
        """Read patterns.json with mtime-based caching."""
        try:
            mtime = os.path.getmtime(PATTERNS_FILE)
        except OSError:
            return {"patterns": []}
        if self._patterns_cache is not None and mtime == self._patterns_cache_mtime:
            return self._patterns_cache
        data = self._read_json(PATTERNS_FILE, {"patterns": []})
        self._patterns_cache = data
        self._patterns_cache_mtime = mtime
        return data

    def _invalidate_patterns_cache(self) -> None:
        """Invalidate the patterns cache after a write."""
        self._patterns_cache = None
        self._patterns_cache_mtime = 0

    def learn_patterns(self, patterns: list[dict]) -> list[str]:
        """Save new patterns from LLM analysis. Returns list of pattern IDs."""
        if not patterns:
            return []
        with self._lock:
            return self._learn_patterns_locked(patterns)

    def _learn_patterns_locked(self, patterns: list[dict]) -> list[str]:
        """Internal learn_patterns implementation (must hold self._lock)."""
        data = self._read_json(PATTERNS_FILE, {"patterns": []})
        existing_names = {p["name"] for p in data["patterns"]}
        new_ids = []

        # Deduplicate incoming patterns by name to avoid double-counting
        unique_patterns: dict[str, dict] = {}
        for p in patterns:
            name = p.get("pattern_name", "").strip()
            if not name:
                logger.warning("Skipping learned pattern with empty name")
                continue
            if name not in unique_patterns:
                unique_patterns[name] = p

        # Increment miss streak for all existing patterns not matched this round
        returned_names = set(unique_patterns.keys())
        for existing in data["patterns"]:
            if existing["name"] not in returned_names:
                existing["miss_streak"] = existing.get("miss_streak", 0) + 1
                if existing["miss_streak"] >= MISS_STREAK_THRESHOLD:
                    existing["confidence"] = max(0, existing.get("confidence", 0) + MISS_DECAY)
                # Stale decay
                last_hit = existing.get("last_hit_at")
                if last_hit:
                    try:
                        last_hit_dt = datetime.fromisoformat(last_hit)
                        if last_hit_dt.tzinfo is not None:
                            last_hit_dt = last_hit_dt.replace(tzinfo=None)
                        if (datetime.utcnow() - last_hit_dt).days > STALE_DAYS:
                            existing["confidence"] = max(0, existing.get("confidence", 0) + STALE_DECAY)
                    except (ValueError, TypeError):
                        logger.debug("Failed to parse last_hit_at for pattern %s", existing.get("name", ""))
                self._update_pattern_status(existing)

        for name, p in unique_patterns.items():
            if name in existing_names:
                # Match existing pattern - boost confidence
                for existing in data["patterns"]:
                    if existing["name"] == name:
                        existing["hit_count"] = existing.get("hit_count", 0) + 1
                        existing["miss_streak"] = 0
                        existing["confidence"] = min(1.0, existing.get("confidence", INITIAL_CONFIDENCE) + HIT_BOOST)
                        existing["last_hit_at"] = datetime.utcnow().isoformat()
                        self._update_pattern_status(existing)
                        new_ids.append(existing["id"])
                        break
                continue

            pattern_id = str(uuid.uuid4())[:8]
            new_pattern = {
                "id": pattern_id,
                "name": name,
                "conditions": p.get("conditions", ""),
                "solution": p.get("solution", ""),
                "source": "llm",
                "confidence": INITIAL_CONFIDENCE,
                "hit_count": 1,
                "miss_streak": 0,
                "created_at": datetime.utcnow().isoformat(),
                "last_hit_at": datetime.utcnow().isoformat(),
                "status": "candidate",
            }
            data["patterns"].append(new_pattern)
            existing_names.add(name)
            new_ids.append(pattern_id)

        self._write_json(PATTERNS_FILE, data)
        self._invalidate_patterns_cache()
        return new_ids

    def update_pattern_hits(self, matched_names: list[str]) -> None:
        """Boost confidence for matched pattern names."""
        if not matched_names:
            return
        with self._lock:
            data = self._read_json(PATTERNS_FILE, {"patterns": []})
            matched_set = set(matched_names)
            changed = False

            for p in data["patterns"]:
                if p["name"] in matched_set:
                    p["hit_count"] = p.get("hit_count", 0) + 1
                    p["miss_streak"] = 0
                    p["confidence"] = min(1.0, p.get("confidence", INITIAL_CONFIDENCE) + HIT_BOOST)
                    p["last_hit_at"] = datetime.utcnow().isoformat()
                    self._update_pattern_status(p)
                    changed = True

            if changed:
                self._write_json(PATTERNS_FILE, data)
                self._invalidate_patterns_cache()

    def decay_missed_patterns(self) -> None:
        """Decay patterns that haven't been hit recently. Run periodically."""
        with self._lock:
            data = self._read_json(PATTERNS_FILE, {"patterns": []})
            now = datetime.utcnow()
            changed = False

            for p in data["patterns"]:
                if p.get("source") == "builtin":
                    continue
                # Increment miss streak
                p["miss_streak"] = p.get("miss_streak", 0) + 1
                # Decay after threshold
                if p["miss_streak"] >= MISS_STREAK_THRESHOLD:
                    p["confidence"] = max(0, p.get("confidence", 0) + MISS_DECAY)
                    changed = True
                # Stale decay
                last_hit = p.get("last_hit_at")
                if last_hit:
                    try:
                        last_hit_dt = datetime.fromisoformat(last_hit)
                        # Normalize to naive UTC for comparison
                        if last_hit_dt.tzinfo is not None:
                            last_hit_dt = last_hit_dt.replace(tzinfo=None)
                        if (now - last_hit_dt).days > STALE_DAYS:
                            p["confidence"] = max(0, p.get("confidence", 0) + STALE_DECAY)
                            changed = True
                    except (ValueError, TypeError):
                        logger.debug("Failed to parse last_hit_at for pattern %s", p.get("name", ""))
                self._update_pattern_status(p)

            if changed:
                self._write_json(PATTERNS_FILE, data)
                self._invalidate_patterns_cache()

    def get_stats(self) -> dict:
        """Get knowledge base statistics."""
        patterns = self.get_all_patterns()
        cases = self._read_json(CASES_FILE, {"cases": []}).get("cases", [])
        return {
            "total_patterns": len(patterns),
            "active_patterns": sum(1 for p in patterns if p.get("status") in ("active", "observed")),
            "candidate_patterns": sum(1 for p in patterns if p.get("status") == "candidate"),
            "total_cases": len(cases),
        }

    # === Cases ===

    def save_case(self, result: Any, llm_result: dict[str, Any]) -> str:
        """Save a diagnostic case for future reference."""
        data = self._read_json(CASES_FILE, {"cases": []})
        case_id = str(uuid.uuid4())[:8]

        # Extract key metrics
        metrics = getattr(result, "raw_metrics", {}) or {}
        key_metrics = {
            "aas": metrics.get("aas", 0),
            "db_cpu_pct": metrics.get("db_cpu_pct_db_time", 0),
            "commit_pct": metrics.get("commit_pct_db_time", 0),
            "user_io_pct": metrics.get("user_io_pct_db_time", 0),
            "parse_pct": metrics.get("parse_time_pct_db_time", 0),
        }
        db_info = metrics.get("db_info", {}) or {}
        top_sql = metrics.get("top_sql_elapsed", []) or []

        case = {
            "id": case_id,
            "db_name": db_info.get("db_name", "unknown"),
            "severity": getattr(result, "severity", "INFO"),
            "main_bottleneck": getattr(result, "main_bottleneck", ""),
            "key_metrics": key_metrics,
            "top_sql_ids": [s.get("sql_id", "") for s in top_sql[:5]],
            "llm_summary": (llm_result.get("expert_analysis", "") or "")[:500],
            "learned_pattern_ids": [p.get("pattern_name", "") for p in llm_result.get("learned_patterns", [])],
            "created_at": datetime.utcnow().isoformat(),
        }

        data["cases"].append(case)
        # Keep last 200 cases
        if len(data["cases"]) > 200:
            data["cases"] = data["cases"][-200:]
        self._write_json(CASES_FILE, data)
        return case_id

    # === Seed ===

    def seed_builtin_patterns(self, patterns: list[dict]) -> int:
        """Seed built-in expert patterns. Skips duplicates by name. Returns count added."""
        patterns_file = os.path.join(self.knowledge_dir, "patterns.json")
        data = self._read_json(patterns_file, {"patterns": []})
        existing_names = {p["name"] for p in data["patterns"]}
        added = 0
        now = datetime.utcnow().isoformat()

        for p in patterns:
            if p["name"] in existing_names:
                continue
            data["patterns"].append({
                "id": str(uuid.uuid4())[:8],
                "name": p["name"],
                "conditions": p.get("conditions", ""),
                "solution": p.get("solution", ""),
                "source": "builtin",
                "confidence": p.get("confidence", 0.90),
                "hit_count": 0,
                "miss_streak": 0,
                "created_at": now,
                "last_hit_at": now,
                "status": "active",
            })
            existing_names.add(p["name"])
            added += 1

        if added:
            self._write_json(patterns_file, data)
        return added

    # === Backup & Distillation ===

    def backup_knowledge(self, label: str = "distill") -> str:
        """Backup patterns.json to knowledge/backups/. Returns backup path."""
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_name = f"patterns_{ts}_{label}.json"
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        if os.path.exists(PATTERNS_FILE):
            shutil.copy2(PATTERNS_FILE, backup_path)
        else:
            self._write_json(backup_path, {"patterns": []})
        self._prune_backups()
        return backup_path

    def restore_from_backup(self, backup_path: str) -> bool:
        """Restore patterns.json from a backup file."""
        try:
            if not os.path.exists(backup_path):
                return False
            shutil.copy2(backup_path, PATTERNS_FILE)
            return True
        except Exception as e:
            logger.error("Restore failed: %s", e)
            return False

    def list_backups(self) -> list[dict]:
        """List available backups sorted by time (newest first)."""
        if not os.path.isdir(BACKUP_DIR):
            return []
        backups = []
        for name in os.listdir(BACKUP_DIR):
            if name.startswith("patterns_") and name.endswith(".json"):
                path = os.path.join(BACKUP_DIR, name)
                backups.append({
                    "name": name,
                    "path": path,
                    "size": os.path.getsize(path),
                    "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                })
        backups.sort(key=lambda b: b["mtime"], reverse=True)
        return backups

    def get_latest_backup_path(self) -> str | None:
        """Get the path of the most recent backup."""
        backups = self.list_backups()
        return backups[0]["path"] if backups else None

    def save_distillation_log(self, log: dict) -> None:
        """Append a distillation log entry."""
        logs = self._read_json(DISTILL_LOG_FILE, [])
        if not isinstance(logs, list):
            logs = []
        log["timestamp"] = datetime.utcnow().isoformat()
        logs.append(log)
        self._write_json(DISTILL_LOG_FILE, logs)

    def get_distillation_logs(self) -> list[dict]:
        """Get all distillation log entries."""
        logs = self._read_json(DISTILL_LOG_FILE, [])
        return logs if isinstance(logs, list) else []

    def has_recent_distillation(self, hours: int = 24) -> bool:
        """Check if there was a distillation within the last N hours."""
        if hours <= 0:
            return False
        logs = self.get_distillation_logs()
        if not logs:
            return False
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        for log in reversed(logs):
            ts = log.get("timestamp", "")
            try:
                if datetime.fromisoformat(ts) > cutoff:
                    return True
            except (ValueError, TypeError):
                continue
        return False

    def replace_patterns(self, new_patterns: list[dict]) -> dict:
        """Atomically replace the patterns list. Returns summary."""
        with self._lock:
            old_data = self._read_json(PATTERNS_FILE, {"patterns": []})
            old_count = len(old_data.get("patterns", []))
            self._write_json(PATTERNS_FILE, {"patterns": new_patterns})
            self._invalidate_patterns_cache()
            new_count = len(new_patterns)
        return {"old_count": old_count, "new_count": new_count}

    def _prune_backups(self) -> None:
        """Keep only the most recent MAX_BACKUPS backups."""
        if not os.path.isdir(BACKUP_DIR):
            return
        backups = self.list_backups()
        for old in backups[MAX_BACKUPS:]:
            try:
                os.remove(old["path"])
            except OSError:
                pass

    # === Internal ===

    def _update_pattern_status(self, pattern: dict) -> None:
        """Update pattern status based on confidence."""
        confidence = pattern.get("confidence", 0)
        if confidence >= ACTIVE_THRESHOLD:
            pattern["status"] = "active"
        elif confidence >= 0.50:
            pattern["status"] = "observed"
        elif confidence < REJECT_THRESHOLD:
            pattern["status"] = "rejected"
        elif confidence < 0.35:
            pattern["status"] = "stale"
        else:
            pattern["status"] = "candidate"

    def _read_json(self, path: str, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def _write_json(self, path: str, data: Any) -> None:
        """Write JSON atomically (write to temp file, then rename)."""
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

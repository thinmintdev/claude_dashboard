"""Session collector — incremental tail-parser for Claude Code session JSONLs.

Maintains per-file byte offsets so a refresh only reads appended lines.
Cold-start on a large file seeks to the last COLD_TAIL_BYTES instead of
parsing hundreds of MB; cumulative counters are then "since first sight",
which the spec accepts.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from devdash.models import SessionInfo

COLD_TAIL_BYTES = 4 * 1024 * 1024
ACTIVE_SECS = 5 * 60          # event within 5 min → active
IDLE_SECS = 60 * 60           # within 1 h → idle; older → stale


@dataclass
class FileState:
    """Parser state for one session JSONL, persisted across refreshes."""

    offset: int = 0
    session_id: str = ""
    cwd: str = ""
    model: str = ""
    speed_mode: str = "standard"
    git_branch: str = ""
    version: str = ""
    is_sidechain: bool = False
    last_event_ts: float = 0.0
    last_text: str = ""
    ctx_tokens: int = 0          # prompt-side tokens of latest assistant event
    tokens_turn: int = 0
    tokens_total: int = 0
    malformed: int = 0
    # (ts, output_tokens, uncached_input) per assistant event — quota feed
    events: list[tuple[float, int, int]] = field(default_factory=list)


def _parse_ts(raw: str | None) -> float:
    if not raw:
        return 0.0
    from datetime import datetime

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _extract_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        for block in reversed(content):
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "").strip()
    return ""


class SessionCollector:
    def __init__(self, projects_dir: Path, model_windows: dict[str, int],
                 liveness_hours: float = 4.0):
        self.projects_dir = projects_dir
        self.model_windows = model_windows
        self.liveness_hours = liveness_hours
        self.files: dict[str, FileState] = {}

    # -- discovery ---------------------------------------------------------

    def discover(self) -> list[Path]:
        cutoff = time.time() - self.liveness_hours * 3600
        out = []
        for f in self.projects_dir.glob("*/*.jsonl"):
            try:
                if f.stat().st_mtime >= cutoff:
                    out.append(f)
            except OSError:
                continue
        return out

    # -- incremental parse -------------------------------------------------

    def parse_file(self, path: Path) -> FileState:
        key = str(path)
        st = self.files.get(key)
        if st is None:
            st = FileState(session_id=path.stem)
            self.files[key] = st
        try:
            size = path.stat().st_size
        except OSError:
            return st
        if size < st.offset:           # truncated/rotated — start over
            st.offset = 0
        if st.offset == 0 and size > COLD_TAIL_BYTES:
            st.offset = size - COLD_TAIL_BYTES
        if size == st.offset:
            return st

        with path.open("rb") as fh:
            fh.seek(st.offset)
            chunk = fh.read(size - st.offset)
        if st.offset and not chunk.startswith(b"{"):
            # landed mid-line after a cold seek — drop the partial first line
            nl = chunk.find(b"\n")
            chunk = chunk[nl + 1:] if nl >= 0 else b""
        # never advance past a line still being written
        complete, _, _partial = chunk.rpartition(b"\n")
        st.offset = size - len(_partial)

        for raw in complete.splitlines():
            if not raw.strip():
                continue
            try:
                ev = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                st.malformed += 1
                continue
            self._apply(st, ev)
        return st

    def _apply(self, st: FileState, ev: dict) -> None:
        ts = _parse_ts(ev.get("timestamp"))
        if ts:
            st.last_event_ts = max(st.last_event_ts, ts)
        for k, attr in (("cwd", "cwd"), ("gitBranch", "git_branch"),
                        ("version", "version"), ("sessionId", "session_id")):
            v = ev.get(k)
            if v:
                setattr(st, attr, v)
        if ev.get("isSidechain"):
            st.is_sidechain = True
        if ev.get("type") != "assistant":
            return
        msg = ev.get("message") or {}
        if msg.get("model"):
            st.model = msg["model"]
        text = _extract_text(msg)
        if text:
            st.last_text = text
        usage = msg.get("usage")
        if not usage:
            return
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        cache_r = usage.get("cache_read_input_tokens", 0)
        cache_c = usage.get("cache_creation_input_tokens", 0)
        st.ctx_tokens = inp + cache_r + cache_c
        st.tokens_turn = out
        st.tokens_total += out
        st.speed_mode = usage.get("speed", st.speed_mode)
        st.events.append((ts or time.time(), out, inp + cache_c))
        if len(st.events) > 5000:
            del st.events[:1000]

    # -- snapshot assembly ---------------------------------------------------

    def _window_for(self, model: str) -> int:
        if "[1m]" in model:
            return 1_000_000
        for prefix, win in self.model_windows.items():
            if prefix != "default" and model.startswith(prefix):
                return win
        return self.model_windows.get("default", 200_000)

    def collect(self) -> list[SessionInfo]:
        now = time.time()
        infos = []
        for path in self.discover():
            st = self.parse_file(path)
            if not st.last_event_ts:
                continue
            idle = max(0, int(now - st.last_event_ts))
            status = ("active" if idle <= ACTIVE_SECS
                      else "idle" if idle <= IDLE_SECS else "stale")
            win = self._window_for(st.model)
            if st.ctx_tokens > win:
                # model id carries no context-size marker; if usage exceeds
                # the configured window the session must be on the 1M tier
                win = max(win, 1_000_000)
            infos.append(SessionInfo(
                id=st.session_id,
                cwd=st.cwd,
                model=st.model,
                speed_mode=st.speed_mode,
                ctx_pct=round(100.0 * st.ctx_tokens / win, 1) if win else 0.0,
                tokens_turn=st.tokens_turn,
                tokens_total=st.tokens_total,
                idle_secs=idle,
                status=status,
                last_text=st.last_text[:300],
                git_branch=st.git_branch,
                version=st.version,
            ))
        infos.sort(key=lambda s: ({"active": 0, "idle": 1, "stale": 2}[s.status],
                                  s.idle_secs))
        return infos

    def sidechain_ids(self) -> set[str]:
        return {st.session_id for st in self.files.values() if st.is_sidechain}

    # -- offset persistence --------------------------------------------------

    _PERSISTED = ("offset", "session_id", "cwd", "model", "speed_mode",
                  "git_branch", "version", "is_sidechain", "last_event_ts",
                  "last_text", "ctx_tokens", "tokens_turn", "tokens_total",
                  "malformed")

    def save_state(self, cache_file: Path) -> None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        week_ago = time.time() - 7 * 24 * 3600
        data = {}
        for k, v in self.files.items():
            entry = {f: getattr(v, f) for f in self._PERSISTED}
            # keep the quota feed across restarts (trimmed to the week window)
            entry["events"] = [e for e in v.events if e[0] >= week_ago]
            data[k] = entry
        cache_file.write_text(json.dumps(data))

    def load_state(self, cache_file: Path) -> None:
        try:
            data = json.loads(cache_file.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for k, v in data.items():
            st = FileState(session_id=Path(k).stem)
            for f in self._PERSISTED:
                if f in v:
                    setattr(st, f, v[f])
            st.events = [tuple(e) for e in v.get("events", [])]
            self.files[k] = st

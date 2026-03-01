"""Config loader: YAML + env. Paths are relative to project root (this folder on Desktop)."""
import os
from pathlib import Path
from dataclasses import dataclass

try:
    import yaml
except ImportError:
    yaml = None

# Project root = folder containing src/ (e.g. Desktop/manideep-bot)
_BOT_ROOT = Path(__file__).resolve().parent.parent.parent
# Data and solved live in the same project
_SKILL_ROOT = _BOT_ROOT


def _env_or(key: str, file_val, default=None):
    v = os.environ.get(key)
    if v is not None and v != "":
        return v
    if file_val is not None and file_val != "":
        return file_val
    return default


@dataclass
class SlackConfig:
    enabled: bool = True
    bot_token: str = ""
    app_token: str = ""
    team_id: str = ""
    allowed_user_ids: list = None
    # Channel where bucket watcher posts "my tickets" suggestions (reply Done / Approve in thread)
    bucket_channel_id: str = ""

    def __post_init__(self):
        if self.allowed_user_ids is None:
            self.allowed_user_ids = []


@dataclass
class AnthropicConfig:
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    max_turns: int = 20


@dataclass
class GeminiConfig:
    api_key: str = ""
    model: str = "gemini-pro"
    max_tokens: int = 8192


@dataclass
class DevRevConfig:
    api_key: str = ""
    solved_states: str = "closed,done,resolved"
    pod_part_id: str = ""
    closed_stage_name: str = "Closed"


@dataclass
class MonitorConfig:
    enabled: bool = False
    interval_minutes: int = 20
    new_ticket_filter_parts: list = None  # applies_to_part IDs (optional if part_names set)
    new_ticket_filter_part_names: list = None  # part names, resolved to IDs via DevRev parts.list (e.g. "distribution channel and reseller")
    new_ticket_states: list = None
    new_ticket_stage_names: list = None  # e.g. ["triage"] – only tickets in these stages
    new_ticket_unassigned_only: bool = False  # only tickets with no owner
    my_tickets_enabled: bool = True
    my_tickets_states: list = None
    awaiting_info_stage_names: list = None
    solved_fetch_interval_hours: float = 24.0  # run fetch_my_solved once per this many hours

    def __post_init__(self):
        if self.new_ticket_filter_parts is None:
            self.new_ticket_filter_parts = []
        if self.new_ticket_filter_part_names is None:
            self.new_ticket_filter_part_names = []
        if self.new_ticket_states is None:
            self.new_ticket_states = ["open", "triaged", "backlog"]
        if self.new_ticket_stage_names is None:
            self.new_ticket_stage_names = []
        if self.my_tickets_states is None:
            self.my_tickets_states = ["open", "in_progress", "triaged"]
        if self.awaiting_info_stage_names is None:
            self.awaiting_info_stage_names = ["Awaiting info from reporter", "Awaiting Customer"]


@dataclass
class RetrieverConfig:
    """Retrieval of relevant past solved tickets (BM25 + tag boost)."""
    top_k: int = 12
    use_bm25: bool = True


@dataclass
class BucketConfig:
    """Watch 'my bucket' (tickets assigned to me), analyze and post suggestions to Slack."""
    max_tickets_per_run: int = 10
    states: list = None  # open states to fetch

    def __post_init__(self):
        if self.states is None:
            self.states = ["open", "in_progress", "triaged", "backlog"]


@dataclass
class PathsConfig:
    bot_root: Path = _BOT_ROOT
    skill_root: Path = _SKILL_ROOT

    @property
    def data_dir(self) -> Path:
        return self.skill_root / "data"

    @property
    def solved_dir(self) -> Path:
        return self.skill_root / "solved"

    @property
    def template_dir(self) -> Path:
        return self.bot_root / "template"


@dataclass
class Config:
    slack: SlackConfig
    anthropic: AnthropicConfig
    gemini: GeminiConfig
    devrev: DevRevConfig
    monitor: MonitorConfig
    retriever: RetrieverConfig
    bucket: BucketConfig
    paths: PathsConfig
    # AI provider for suggestions: "anthropic" (Claude) or "gemini" (Google)
    ai_provider: str = "anthropic"


def load_config(env: str = None) -> Config:
    env = env or os.environ.get("APP_ENV", "dev")
    raw = {}
    config_file = _BOT_ROOT / "config" / f"env.{env}.yaml"
    if config_file.exists() and yaml:
        with open(config_file) as f:
            raw = yaml.safe_load(f) or {}

    slk = raw.get("slack", {})
    ant = raw.get("anthropic", {})
    gem = raw.get("gemini", {})
    dev = raw.get("devrev", {})
    ai_section = raw.get("ai", {})

    return Config(
        slack=SlackConfig(
            enabled=slk.get("enabled", True),
            bot_token=_env_or("SLACK_BOT_TOKEN", slk.get("bot_token")),
            app_token=_env_or("SLACK_APP_TOKEN", slk.get("app_token")),
            team_id=_env_or("SLACK_TEAM_ID", slk.get("team_id")),
            allowed_user_ids=slk.get("allowed_user_ids", []),
            bucket_channel_id=_env_or("SLACK_BUCKET_CHANNEL_ID", slk.get("bucket_channel_id") or ""),
        ),
        anthropic=AnthropicConfig(
            api_key=_env_or("ANTHROPIC_API_KEY", ant.get("api_key")),
            model=ant.get("model", "claude-sonnet-4-20250514"),
            max_tokens=int(ant.get("max_tokens", 8192)),
            max_turns=int(ant.get("max_turns", 20)),
        ),
        gemini=GeminiConfig(
            api_key=_env_or("GEMINI_API_KEY", _env_or("GOOGLE_API_KEY", gem.get("api_key"))),
            model=_env_or("GEMINI_MODEL", gem.get("model", "gemini-pro")),
            max_tokens=int(gem.get("max_tokens", 8192)),
        ),
        devrev=DevRevConfig(
            api_key=_env_or("DEVREV_API_KEY", dev.get("api_key")),
            solved_states=_env_or("DEVREV_SOLVED_STATES", dev.get("solved_states"), "closed,done,resolved"),
            pod_part_id=_env_or("DEVREV_POD_PART_ID", dev.get("pod_part_id")),
            closed_stage_name=_env_or("DEVREV_CLOSED_STAGE", dev.get("closed_stage_name"), "Closed"),
        ),
        monitor=_load_monitor(raw.get("monitor", {})),
        retriever=_load_retriever(raw.get("retriever", {})),
        bucket=_load_bucket(raw.get("bucket", {})),
        paths=PathsConfig(),
        ai_provider=(_env_or("AI_PROVIDER", ai_section.get("provider")) or "anthropic").lower().strip(),
    )


def _load_retriever(raw: dict) -> "RetrieverConfig":
    return RetrieverConfig(
        top_k=int(raw.get("top_k", 12)),
        use_bm25=bool(raw.get("use_bm25", True)),
    )


def _load_bucket(raw: dict) -> "BucketConfig":
    return BucketConfig(
        max_tickets_per_run=int(raw.get("max_tickets_per_run", 10)),
        states=raw.get("states", ["open", "in_progress", "triaged", "backlog"]),
    )


def _load_monitor(raw: dict) -> "MonitorConfig":
    filters = raw.get("new_ticket_filters", {})
    parts = filters.get("applies_to_part") or []
    if not parts and os.environ.get("DEVREV_MONITOR_PART_IDS"):
        parts = [p.strip() for p in os.environ.get("DEVREV_MONITOR_PART_IDS", "").split(",") if p.strip()]
    part_names = filters.get("applies_to_part_names") or filters.get("part_names") or []
    if not part_names and os.environ.get("DEVREV_MONITOR_PART_NAMES"):
        part_names = [p.strip() for p in os.environ.get("DEVREV_MONITOR_PART_NAMES", "").split("|") if p.strip()]
    if isinstance(part_names, str):
        part_names = [s.strip() for s in part_names.split("|") if s.strip()]
    stage_names = filters.get("stage_names") or filters.get("stage") or []
    if isinstance(stage_names, str):
        stage_names = [s.strip() for s in stage_names.split(",") if s.strip()]
    unassigned_only = filters.get("unassigned_only", False)
    interval_hours = raw.get("solved_fetch_interval_hours")
    if interval_hours is None and os.environ.get("DEVREV_SOLVED_FETCH_INTERVAL_HOURS"):
        try:
            interval_hours = float(os.environ.get("DEVREV_SOLVED_FETCH_INTERVAL_HOURS"))
        except ValueError:
            interval_hours = 24.0
    my_cfg = raw.get("my_tickets", {})
    return MonitorConfig(
        enabled=raw.get("enabled", False),
        interval_minutes=int(raw.get("interval_minutes", 20)),
        new_ticket_filter_parts=parts,
        new_ticket_filter_part_names=part_names,
        new_ticket_states=filters.get("state", ["open", "triaged", "backlog"]),
        new_ticket_stage_names=stage_names,
        new_ticket_unassigned_only=unassigned_only,
        my_tickets_enabled=my_cfg.get("enabled", True),
        my_tickets_states=my_cfg.get("states_to_watch", ["open", "in_progress", "triaged"]),
        awaiting_info_stage_names=my_cfg.get("awaiting_info_stage_names", ["Awaiting info from reporter", "Awaiting Customer"]),
        solved_fetch_interval_hours=float(interval_hours) if interval_hours is not None else 24.0,
    )

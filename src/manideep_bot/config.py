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
    # Channel where bot posts proactive "my tickets" updates (private/personal channel)
    bucket_channel_id: str = ""
    # Channel to LISTEN for DevRev ticket notifications (e.g. #engage-production-issues)
    # Bot watches this channel, filters by your parts, replies in thread for matching tickets
    watch_channel_id: str = ""

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
class DevRevConfig:
    api_key: str = ""
    solved_states: str = "closed,done,resolved"
    closed_stage_name: str = "Closed"
    # Webhook: secret from DevRev webhooks.create (for X-DevRev-Signature verification)
    webhook_secret: str = ""
    # Base URL for ticket links in Slack (e.g. https://app.devrev.ai)
    app_base_url: str = "https://app.devrev.ai"
    # Your own DevRev user DON ID — used for auto-assigning unassigned tickets
    my_user_id: str = ""
    # SVCACC-2 DON ID — DevRev assigns unassigned tickets to this service account
    unassigned_svcacc_id: str = "don:identity:dvrv-in-1:devo/2sRI6Hepzz:svcacc/2"


@dataclass
class MonitorConfig:
    enabled: bool = False
    interval_minutes: int = 20
    new_ticket_filter_parts: list = None  # applies_to_part IDs — use PROD-19 for all PSE tickets
    new_ticket_filter_part_names: list = None  # legacy: resolved to IDs via parts.list (leave empty)
    new_ticket_filter_pse_pods: list = None  # post-fetch filter on ctype__pse_pod custom field
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
        if self.new_ticket_filter_pse_pods is None:
            self.new_ticket_filter_pse_pods = []
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
    """Retrieval of relevant past solved tickets (BM25 + tag boost; optional embeddings + threshold)."""
    top_k: int = 12
    use_bm25: bool = True
    use_embeddings: bool = False
    embedding_provider: str = "openai"
    min_similarity: float = 0.0
    use_devrev_hybrid: bool = True   # DevRev hybrid search to boost cross-validated matches
    devrev_hybrid_limit: int = 10    # how many results to fetch from DevRev hybrid search


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
    devrev: DevRevConfig
    monitor: MonitorConfig
    retriever: RetrieverConfig
    bucket: BucketConfig
    paths: PathsConfig


def load_config(env: str = None) -> Config:
    env = env or os.environ.get("APP_ENV", "dev")
    raw = {}
    config_file = _BOT_ROOT / "config" / f"env.{env}.yaml"
    if config_file.exists() and yaml:
        with open(config_file) as f:
            raw = yaml.safe_load(f) or {}

    slk = raw.get("slack", {})
    ant = raw.get("anthropic", {})
    dev = raw.get("devrev", {})

    return Config(
        slack=SlackConfig(
            enabled=slk.get("enabled", True),
            bot_token=_env_or("SLACK_BOT_TOKEN", slk.get("bot_token")),
            app_token=_env_or("SLACK_APP_TOKEN", slk.get("app_token")),
            team_id=_env_or("SLACK_TEAM_ID", slk.get("team_id")),
            allowed_user_ids=slk.get("allowed_user_ids", []),
            bucket_channel_id=_env_or("SLACK_BUCKET_CHANNEL_ID", slk.get("bucket_channel_id") or ""),
            watch_channel_id=_env_or("SLACK_WATCH_CHANNEL_ID", slk.get("watch_channel_id") or ""),
        ),
        anthropic=AnthropicConfig(
            api_key=_env_or("ANTHROPIC_API_KEY", ant.get("api_key")),
            model=ant.get("model", "claude-sonnet-4-20250514"),
            max_tokens=int(ant.get("max_tokens", 8192)),
            max_turns=int(ant.get("max_turns", 20)),
        ),
        devrev=DevRevConfig(
            api_key=_env_or("DEVREV_API_KEY", dev.get("api_key")),
            solved_states=_env_or("DEVREV_SOLVED_STATES", dev.get("solved_states"), "closed,done,resolved"),
            closed_stage_name=_env_or("DEVREV_CLOSED_STAGE", dev.get("closed_stage_name"), "Closed"),
            webhook_secret=_env_or("DEVREV_WEBHOOK_SECRET", dev.get("webhook_secret")),
            app_base_url=_env_or("DEVREV_APP_BASE_URL", dev.get("app_base_url"), "https://app.devrev.ai"),
            my_user_id=_env_or("DEVREV_MY_USER_ID", dev.get("my_user_id"), ""),
            unassigned_svcacc_id=_env_or(
                "DEVREV_UNASSIGNED_SVCACC_ID",
                dev.get("unassigned_svcacc_id"),
                "don:identity:dvrv-in-1:devo/2sRI6Hepzz:svcacc/2",
            ),
        ),
        monitor=_load_monitor(raw.get("monitor", {})),
        retriever=_load_retriever(raw.get("retriever", {})),
        bucket=_load_bucket(raw.get("bucket", {})),
        paths=PathsConfig(),
    )


def _load_retriever(raw: dict) -> "RetrieverConfig":
    return RetrieverConfig(
        top_k=int(raw.get("top_k", 12)),
        use_bm25=bool(raw.get("use_bm25", True)),
        use_embeddings=bool(raw.get("use_embeddings", False)),
        embedding_provider=(raw.get("embedding_provider") or "openai").strip(),
        min_similarity=float(raw.get("min_similarity", 0.0)),
        use_devrev_hybrid=bool(raw.get("use_devrev_hybrid", True)),
        devrev_hybrid_limit=int(raw.get("devrev_hybrid_limit", 10)),
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
    pse_pods = filters.get("pse_pod_names") or []
    if isinstance(pse_pods, str):
        pse_pods = [s.strip() for s in pse_pods.split(",") if s.strip()]
    interval_hours = raw.get("solved_fetch_interval_hours")
    if interval_hours is None and os.environ.get("DEVREV_SOLVED_FETCH_INTERVAL_HOURS"):
        try:
            interval_hours = float(os.environ.get("DEVREV_SOLVED_FETCH_INTERVAL_HOURS"))
        except ValueError:
            interval_hours = 24.0
    my_cfg = raw.get("my_tickets", {})
    enabled = raw.get("enabled", False)
    if os.environ.get("MONITOR_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        enabled = True
    return MonitorConfig(
        enabled=enabled,
        interval_minutes=int(raw.get("interval_minutes", 20)),
        new_ticket_filter_parts=parts,
        new_ticket_filter_part_names=part_names,
        new_ticket_filter_pse_pods=pse_pods,
        new_ticket_states=filters.get("state", ["open", "triaged", "backlog"]),
        new_ticket_stage_names=stage_names,
        new_ticket_unassigned_only=unassigned_only,
        my_tickets_enabled=my_cfg.get("enabled", True),
        my_tickets_states=my_cfg.get("states_to_watch", ["open", "in_progress", "triaged"]),
        awaiting_info_stage_names=my_cfg.get("awaiting_info_stage_names", ["Awaiting info from reporter", "Awaiting Customer"]),
        solved_fetch_interval_hours=float(interval_hours) if interval_hours is not None else 24.0,
    )

"""
Configuration settings for SRE Agent.

All settings loaded from environment variables using Pydantic Settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class SREAgentSettings(BaseSettings):
    """
    SRE Agent configuration settings.

    All values are loaded from environment variables with defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # ========== Mode Configuration ==========
    mode: str = "reactive"  # "reactive" (webhook only) or "continuous" (background monitoring)

    # ========== MCP Configuration ==========
    mcp_openshift_url: Optional[str] = None
    mcp_openshift_transport: str = "sse"
    mcp_gitea_url: Optional[str] = None
    mcp_gitea_transport: str = "streamable-http"

    # ========== Gitea Configuration (Legacy - for MCP compatibility) ==========
    mcp_gitea_user: str = "user1"
    mcp_gitea_repo: str = "mcp"

    # ========== Git Platform Configuration ==========
    git_platform: str = "github"  # Options: github, gitlab, gitea, azuredevops, bitbucket
    git_server_url: str = "https://github.com"  # For GitHub Enterprise: https://github.company.com
    git_organization: str = ""  # Organization/owner name
    git_repository: str = "cluster-issues"  # Repository name for issues/PRs
    git_token: str = ""  # Authentication token (loaded from secret)
    git_default_branch: str = "main"  # Default branch for PRs

    # ========== LiteLLM Configuration ==========
    litellm_url: str = ""
    litellm_api_key: str = ""
    litellm_model: str = "openai/Llama-4-Scout-17B-16E-W4A16"

    # ========== Audit Configuration ==========
    audit_storage: str = "sqlite"  # "sqlite" or "configmap" (future)
    audit_db_path: str = "/data/audit.db"

    # ========== Collection Intervals (seconds) ==========
    event_collection_interval: int = 60  # Events every 60s
    cluster_operator_interval: int = 120  # ClusterOperators every 2min
    machine_config_pool_interval: int = 300  # MachineConfigPools every 5min
    pod_collection_interval: int = 30  # Pods every 30s
    route_collection_interval: int = 60  # Routes every 60s
    build_collection_interval: int = 45  # Builds/PipelineRuns every 45s
    networking_collection_interval: int = 120  # Networking every 2min
    autoscaling_collection_interval: int = 90  # HPA/Autoscaler every 90s
    proactive_collection_interval: int = 300  # Proactive trends/anomalies every 5min

    # ========== Prometheus Configuration ==========
    prometheus_url: Optional[str] = None  # Prometheus server URL
    prometheus_enabled: bool = False  # Enable Prometheus integration

    # ========== Proactive Detection Configuration ==========
    trend_lookback_hours: int = 24  # Look back 24 hours for trend analysis
    anomaly_threshold_std: float = 3.0  # Standard deviations for anomaly detection
    proactive_memory_threshold_percent: float = 80.0  # Trigger at 80% of limit
    proactive_cpu_threshold_percent: float = 80.0  # Trigger at 80% of limit

    # ========== Knowledge Base Configuration ==========
    knowledge_base_enabled: bool = True
    knowledge_db_path: str = "/data/knowledge.db"
    incident_similarity_threshold: float = 0.85  # Minimum similarity score (0-1)

    # ========== Tier Enables ==========
    enable_tier1_auto: bool = True  # Enable automated remediation
    enable_tier2_gitops: bool = True  # Enable GitOps PR creation
    enable_tier3_notify: bool = True  # Enable notification/issue creation

    # ========== Remediation Configuration ==========
    remediation_cooldown_minutes: int = 30  # Don't retry same resource within 30min
    max_remediation_attempts: int = 3  # Max attempts per issue
    image_pull_retry_intervals: list[int] = [60, 120, 300]  # Exponential backoff (1min, 2min, 5min)

    # ========== RBAC Configuration ==========
    service_account: str = "sre-agent"
    rbac_check_enabled: bool = True  # Check RBAC before Tier 1 actions

    # ========== Cluster Configuration ==========
    cluster_name: Optional[str] = None  # Cluster name for multi-cluster setups

    # ========== Application Configuration ==========
    port: int = 8000
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # ========== Security ==========
    secret_scrubbing_enabled: bool = True  # NEVER disable this in production


# Global settings instance
_settings: Optional[SREAgentSettings] = None


def get_settings() -> SREAgentSettings:
    """
    Get global settings instance.

    Returns:
        SREAgentSettings instance
    """
    global _settings
    if _settings is None:
        _settings = SREAgentSettings()
    return _settings


if __name__ == "__main__":
    # Demo - show all settings
    import json
    settings = get_settings()
    print("SRE Agent Settings:")
    print(json.dumps(settings.model_dump(), indent=2, default=str))

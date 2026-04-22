"""
Evidence builder utility.

Provides helper functions to build properly structured evidence dictionaries
for diagnoses, ensuring all required fields are populated.
"""

from sre_agent.models.observation import Observation


def build_evidence(observation: Observation, **extra) -> dict:
    """
    Build evidence dict with required base fields.

    Always includes:
    - namespace
    - resource_kind
    - resource_name

    Args:
        observation: Source observation
        **extra: Additional evidence fields

    Returns:
        Complete evidence dictionary

    Example:
        evidence = build_evidence(
            observation,
            exit_code=137,
            memory_limit="128Mi"
        )
    """
    evidence = {
        "namespace": observation.namespace,
        "resource_kind": observation.resource_kind,
        "resource_name": observation.resource_name,
    }
    evidence.update(extra)
    return evidence

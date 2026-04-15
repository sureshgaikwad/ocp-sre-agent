"""
Workflow engine for orchestrating the SRE agent.

Coordinates the Observe → Diagnose → Remediate → Verify loop.
"""

import asyncio
from typing import TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from mcp_client import MCPToolRegistry

from sre_agent.collectors.base import BaseCollector
from sre_agent.analyzers.base import BaseAnalyzer
from sre_agent.handlers.base import BaseHandler
from sre_agent.models.observation import Observation
from sre_agent.models.diagnosis import Diagnosis, Confidence
from sre_agent.models.remediation import RemediationResult
from sre_agent.utils.json_logger import get_logger
from sre_agent.utils.audit_logger import get_audit_logger, OperationType
from sre_agent.utils.event_creator import get_event_creator
from sre_agent.config.settings import get_settings
from sre_agent.knowledge.incident_store import get_knowledge_store
from sre_agent.orchestrator.alert_correlator import AlertCorrelator

logger = get_logger(__name__)


class WorkflowEngine:
    """
    Main workflow orchestrator for the SRE agent.

    Coordinates:
    1. Collection: Run all registered collectors
    2. Analysis: Route observations to appropriate analyzers
    3. Remediation: Route diagnoses to appropriate handlers
    4. Audit: Log all actions
    """

    def __init__(self, mcp_registry: "MCPToolRegistry"):
        """
        Initialize workflow engine.

        Args:
            mcp_registry: MCP tool registry for passing to components
        """
        self.mcp_registry = mcp_registry
        self.settings = get_settings()
        self.audit_logger = get_audit_logger(self.settings.audit_db_path)

        # Component registries
        self.collectors: list[BaseCollector] = []
        self.analyzers: list[BaseAnalyzer] = []
        self.handlers: list[BaseHandler] = []

        # Cooldown tracking to prevent infinite loops
        self._remediation_cache: dict[str, datetime] = {}  # resource_key -> last_remediation_time

        # Phase 4: Knowledge base and alert correlation
        self.knowledge_store = None
        if self.settings.knowledge_base_enabled:
            self.knowledge_store = get_knowledge_store(self.settings.knowledge_db_path)

        self.alert_correlator = AlertCorrelator()

    async def initialize(self) -> None:
        """
        Initialize workflow engine.

        Sets up audit logger, knowledge store, and other async resources.
        """
        await self.audit_logger.initialize()

        if self.knowledge_store:
            await self.knowledge_store.initialize()
            logger.info("Knowledge store initialized")

        logger.info("Workflow engine initialized")

    def register_collector(self, collector: BaseCollector) -> None:
        """
        Register a collector.

        Args:
            collector: Collector instance to register
        """
        self.collectors.append(collector)
        logger.info(f"Registered collector: {collector.collector_name}")

    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """
        Register an analyzer.

        Args:
            analyzer: Analyzer instance to register
        """
        self.analyzers.append(analyzer)
        logger.info(f"Registered analyzer: {analyzer.analyzer_name}")

    def register_handler(self, handler: BaseHandler) -> None:
        """
        Register a handler.

        Args:
            handler: Handler instance to register
        """
        self.handlers.append(handler)
        logger.info(f"Registered handler: {handler.handler_name} (Tier {handler.tier})")

    async def run_workflow(self) -> dict:
        """
        Run a complete workflow cycle: Collect → Analyze → Handle.

        Returns:
            Dict with workflow statistics

        Raises:
            Exception: If workflow fails critically
        """
        request_id = logger.set_request_id()
        workflow_start = datetime.utcnow()

        logger.info(
            "Starting workflow execution",
            request_id=request_id,
            collectors=len(self.collectors),
            analyzers=len(self.analyzers),
            handlers=len(self.handlers)
        )

        stats = {
            "observations": 0,
            "diagnoses": 0,
            "remediations": 0,
            "errors": 0,
            "start_time": workflow_start.isoformat(),
        }

        try:
            # Phase 1: Collect observations
            observations = await self._collect_phase(request_id)
            stats["observations"] = len(observations)

            if not observations:
                logger.info(
                    "No observations collected, workflow complete",
                    request_id=request_id
                )
                return stats

            # Phase 1.5: Create observation events for OpenShift Console
            await self._create_observation_events(observations, request_id)

            # Phase 1.6: Correlate observations (Phase 4 feature)
            correlated_groups = await self.alert_correlator.correlate_observations(observations)
            stats["correlated_groups"] = len(correlated_groups)

            if correlated_groups:
                logger.info(
                    f"Alert correlation reduced {len(observations)} observations to {len(correlated_groups)} groups",
                    request_id=request_id,
                    original_count=len(observations),
                    correlated_count=len(correlated_groups)
                )
                # Process root causes, ignore symptoms for now
                observations_to_analyze = [group.root_cause for group in correlated_groups]
            else:
                observations_to_analyze = observations

            # Phase 2: Analyze observations
            diagnoses_with_obs = await self._analyze_phase(observations_to_analyze, request_id)
            diagnoses = [d for d, o in diagnoses_with_obs]  # Extract diagnoses
            stats["diagnoses"] = len(diagnoses)

            if not diagnoses:
                logger.info(
                    "No diagnoses generated, workflow complete",
                    request_id=request_id,
                    observations=len(observations)
                )
                return stats

            # Phase 3: Remediate based on diagnoses
            remediations = await self._remediate_phase(diagnoses, request_id)
            stats["remediations"] = len(remediations)

            # Phase 4: Store successful remediations in knowledge base
            if self.knowledge_store:
                for (diagnosis, observation), remediation in zip(diagnoses_with_obs, remediations):
                    if remediation.status.value == "success":
                        try:
                            incident_id = await self.knowledge_store.store_incident(
                                observation, diagnosis, remediation
                            )
                            logger.info(
                                f"Stored incident {incident_id} in knowledge base",
                                request_id=request_id,
                                incident_id=incident_id,
                                category=diagnosis.category.value
                            )
                        except Exception as e:
                            logger.warning(
                                f"Failed to store incident in knowledge base: {e}",
                                request_id=request_id,
                                exc_info=True
                            )

            # Calculate duration
            workflow_end = datetime.utcnow()
            duration = (workflow_end - workflow_start).total_seconds()
            stats["duration_seconds"] = duration
            stats["end_time"] = workflow_end.isoformat()

            logger.info(
                f"Workflow complete: {stats['observations']} observations, "
                f"{stats['diagnoses']} diagnoses, {stats['remediations']} remediations "
                f"in {duration:.2f}s",
                request_id=request_id,
                **stats
            )

        except Exception as e:
            stats["errors"] += 1
            logger.error(
                f"Workflow execution failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            raise

        return stats

    async def _collect_phase(self, request_id: str) -> list[Observation]:
        """
        Run all collectors in parallel.

        Args:
            request_id: Request ID for logging

        Returns:
            Combined list of observations from all collectors
        """
        logger.info(
            f"Starting collection phase with {len(self.collectors)} collectors",
            request_id=request_id,
            action_taken="collect"
        )

        all_observations = []

        # Run collectors in parallel
        collection_tasks = [
            self._run_collector(collector, request_id)
            for collector in self.collectors
        ]

        results = await asyncio.gather(*collection_tasks, return_exceptions=True)

        # Process results
        for i, result in enumerate(results):
            collector_name = self.collectors[i].collector_name
            if isinstance(result, Exception):
                logger.error(
                    f"Collector {collector_name} failed: {result}",
                    request_id=request_id,
                    collector=collector_name,
                    exc_info=True
                )
            elif isinstance(result, list):
                all_observations.extend(result)
                logger.info(
                    f"Collector {collector_name} returned {len(result)} observations",
                    request_id=request_id,
                    collector=collector_name,
                    observation_count=len(result)
                )

        logger.info(
            f"Collection phase complete: {len(all_observations)} total observations",
            request_id=request_id,
            observation_count=len(all_observations)
        )

        # Create Kubernetes Events for observations (OpenShift Console alerts)
        await self._create_observation_events(all_observations, request_id)

        return all_observations

    async def _run_collector(self, collector: BaseCollector, request_id: str) -> list[Observation]:
        """
        Run a single collector with error handling.

        Args:
            collector: Collector to run
            request_id: Request ID

        Returns:
            List of observations
        """
        try:
            observations = await collector.collect()
            return observations
        except Exception as e:
            logger.error(
                f"Collector {collector.collector_name} failed: {e}",
                request_id=request_id,
                exc_info=True
            )
            return []

    async def _create_observation_events(self, observations: list[Observation], request_id: str) -> None:
        """
        Create Kubernetes Events for observations (shows in OpenShift Console).

        Args:
            observations: List of observations
            request_id: Request ID for logging
        """
        if not observations:
            return

        event_creator = get_event_creator()

        # Create events in parallel
        event_tasks = []
        for obs in observations:
            # Only create events for important observations
            if obs.severity.value in ["critical", "warning"]:
                task = event_creator.create_observation_event(
                    namespace=obs.namespace or "cluster-wide",
                    resource_name=obs.resource_name,
                    resource_kind=obs.resource_kind,
                    reason=obs.labels.get("reason", obs.type.value),
                    message=obs.message,
                    severity="Warning"
                )
                event_tasks.append(task)

        if event_tasks:
            # Best-effort - don't fail workflow if events fail
            await asyncio.gather(*event_tasks, return_exceptions=True)
            logger.debug(
                f"Created {len(event_tasks)} observation events for OpenShift Console",
                request_id=request_id
            )

    async def _analyze_phase(self, observations: list[Observation], request_id: str) -> list[tuple[Diagnosis, Observation]]:
        """
        Analyze observations using registered analyzers.

        Args:
            observations: Observations to analyze
            request_id: Request ID for logging

        Returns:
            List of (diagnosis, observation) tuples
        """
        logger.info(
            f"Starting analysis phase with {len(observations)} observations",
            request_id=request_id,
            action_taken="analyze"
        )

        all_diagnoses_with_obs = []

        # Process each observation
        for observation in observations:
            # Phase 4: Check knowledge base for similar past incidents
            similar_incidents = []
            if self.knowledge_store:
                try:
                    similar_incidents = await self.knowledge_store.find_similar_incidents(
                        observation, limit=1
                    )
                    if similar_incidents:
                        incident = similar_incidents[0]
                        logger.info(
                            f"Found similar past incident for observation {observation.id}",
                            request_id=request_id,
                            observation_id=observation.id,
                            similar_incident_id=incident.incident_id,
                            category=incident.diagnosis.category.value,
                            mttr_seconds=incident.mttr_seconds
                        )

                        # Create NEW diagnosis with current observation data
                        # (Don't reuse old diagnosis - it has stale pod names in evidence!)
                        old_diag = incident.diagnosis

                        # Extract current pod/resource info from observation
                        current_evidence = {
                            "namespace": observation.namespace,
                            "pod_name": observation.resource_name,
                            "resource_kind": observation.resource_kind,
                            "container_name": observation.raw_data.get("container_name"),
                            "exit_code": observation.raw_data.get("exit_code"),
                            "reason": observation.raw_data.get("reason"),
                            "restart_count": observation.raw_data.get("restart_count"),
                            # Preserve memory limit info from observation
                            "memory_limit": observation.raw_data.get("container_status", {}).get(
                                "resources", {}
                            ).get("limits", {}).get("memory", "unknown"),
                        }

                        # Create fresh diagnosis with learned category but current data
                        diagnosis = Diagnosis(
                            observation_id=observation.id,
                            category=old_diag.category,  # Reuse learned category
                            root_cause=old_diag.root_cause,  # Reuse learned root cause
                            confidence=Confidence.HIGH,  # High confidence from past success
                            recommended_actions=old_diag.recommended_actions,  # Reuse learned actions
                            recommended_tier=old_diag.recommended_tier,  # Reuse learned tier
                            evidence=current_evidence,  # FRESH evidence from current observation
                            exit_code=observation.raw_data.get("exit_code"),
                            error_patterns=old_diag.error_patterns,
                            analyzer_name="knowledge_store",  # Mark as from knowledge base
                        )

                        logger.info(
                            f"Created fresh diagnosis from knowledge base with current data",
                            request_id=request_id,
                            observation_id=observation.id,
                            diagnosis_id=diagnosis.id,
                            category=diagnosis.category.value,
                            current_pod=current_evidence.get("pod_name")
                        )

                        all_diagnoses_with_obs.append((diagnosis, observation))
                        continue  # Skip fresh analysis, use learned knowledge
                except Exception as e:
                    logger.warning(
                        f"Knowledge base lookup failed: {e}",
                        request_id=request_id,
                        exc_info=True
                    )

            # Find analyzer that can handle this observation
            logger.info(
                f"Checking analyzers for observation {observation.id}",
                request_id=request_id,
                observation_id=observation.id,
                observation_type=observation.type.value if hasattr(observation.type, 'value') else str(observation.type),
                namespace=observation.namespace,
                resource_name=observation.resource_name
            )

            for analyzer in self.analyzers:
                can_handle = analyzer.can_analyze(observation)
                if can_handle:
                    logger.info(
                        f"Analyzer {analyzer.analyzer_name} CAN handle observation {observation.id}",
                        request_id=request_id,
                        analyzer=analyzer.analyzer_name,
                        observation_id=observation.id
                    )
                    try:
                        diagnosis = await analyzer.analyze(observation)
                        if diagnosis:
                            all_diagnoses_with_obs.append((diagnosis, observation))
                            logger.info(
                                f"Analyzer {analyzer.analyzer_name} diagnosed: {diagnosis.category.value}",
                                request_id=request_id,
                                analyzer=analyzer.analyzer_name,
                                observation_id=observation.id,
                                diagnosis_id=diagnosis.id,
                                category=diagnosis.category.value
                            )

                            # Audit the analysis
                            await self.audit_logger.log_operation(
                                operation_type=OperationType.ANALYZE,
                                action="analyze_observation",
                                success=True,
                                observation_id=observation.id,
                                diagnosis_id=diagnosis.id,
                                result_summary=f"{diagnosis.category.value}: {diagnosis.root_cause[:100]}"
                            )
                            break  # Use first matching analyzer
                    except Exception as e:
                        logger.error(
                            f"Analyzer {analyzer.analyzer_name} failed: {e}",
                            request_id=request_id,
                            analyzer=analyzer.analyzer_name,
                            observation_id=observation.id,
                            exc_info=True
                        )

        logger.info(
            f"Analysis phase complete: {len(all_diagnoses_with_obs)} diagnoses",
            request_id=request_id,
            diagnosis_count=len(all_diagnoses_with_obs)
        )

        return all_diagnoses_with_obs

    async def _remediate_phase(self, diagnoses: list[Diagnosis], request_id: str) -> list[RemediationResult]:
        """
        Remediate issues based on diagnoses.

        Args:
            diagnoses: Diagnoses to remediate
            request_id: Request ID for logging

        Returns:
            List of remediation results
        """
        logger.info(
            f"Starting remediation phase with {len(diagnoses)} diagnoses",
            request_id=request_id,
            action_taken="remediate"
        )

        all_remediations = []

        # Process each diagnosis
        for diagnosis in diagnoses:
            # Check cooldown to prevent infinite loops
            if self._is_in_cooldown(diagnosis):
                logger.warning(
                    f"Diagnosis {diagnosis.id} is in cooldown, skipping remediation",
                    request_id=request_id,
                    diagnosis_id=diagnosis.id
                )
                continue

            # Find handler that can handle this diagnosis
            for handler in self.handlers:
                if handler.can_handle(diagnosis):
                    try:
                        remediation = await handler.handle(diagnosis)
                        all_remediations.append(remediation)

                        logger.info(
                            f"Handler {handler.handler_name} remediated: {remediation.status.value}",
                            request_id=request_id,
                            handler=handler.handler_name,
                            diagnosis_id=diagnosis.id,
                            remediation_id=remediation.id,
                            status=remediation.status.value
                        )

                        # Audit the remediation
                        await self.audit_logger.log_operation(
                            operation_type=OperationType.REMEDIATE,
                            action=f"tier{handler.tier}_remediation",
                            success=remediation.status.value == "success",
                            diagnosis_id=diagnosis.id,
                            remediation_id=remediation.id,
                            result_summary=remediation.message[:200]
                        )

                        # Update cooldown
                        self._update_cooldown(diagnosis)

                        break  # Use first matching handler
                    except Exception as e:
                        logger.error(
                            f"Handler {handler.handler_name} failed: {e}",
                            request_id=request_id,
                            handler=handler.handler_name,
                            diagnosis_id=diagnosis.id,
                            exc_info=True
                        )

        logger.info(
            f"Remediation phase complete: {len(all_remediations)} remediations",
            request_id=request_id,
            remediation_count=len(all_remediations)
        )

        return all_remediations

    def _is_in_cooldown(self, diagnosis: Diagnosis) -> bool:
        """
        Check if diagnosis is in remediation cooldown.

        Args:
            diagnosis: Diagnosis to check

        Returns:
            True if in cooldown, False otherwise
        """
        # Create resource key from diagnosis
        resource_key = f"{diagnosis.category.value}:{diagnosis.observation_id}"

        if resource_key in self._remediation_cache:
            last_time = self._remediation_cache[resource_key]
            elapsed = (datetime.utcnow() - last_time).total_seconds()
            cooldown_seconds = self.settings.remediation_cooldown_minutes * 60

            if elapsed < cooldown_seconds:
                return True

        return False

    def _update_cooldown(self, diagnosis: Diagnosis) -> None:
        """
        Update remediation cooldown cache.

        Args:
            diagnosis: Diagnosis that was remediated
        """
        resource_key = f"{diagnosis.category.value}:{diagnosis.observation_id}"
        self._remediation_cache[resource_key] = datetime.utcnow()

    def get_stats(self) -> dict:
        """
        Get workflow engine statistics.

        Returns:
            Dict with component counts and cache info
        """
        return {
            "collectors": len(self.collectors),
            "analyzers": len(self.analyzers),
            "handlers": len(self.handlers),
            "remediation_cache_size": len(self._remediation_cache),
        }

import os
import json
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import litellm

from mcp_client import MCPClient, MCPToolRegistry

# Logger
logger = logging.getLogger(__name__)

# Global registry for MCP tools
mcp_registry = MCPToolRegistry()

# Global workflow engine and watch manager (initialized in lifespan)
workflow_engine = None
watch_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MCP connections and SRE agent on startup."""
    from sre_agent.config.settings import get_settings
    from sre_agent.orchestrator.workflow_engine import WorkflowEngine
    # Phase 2: Collectors
    from sre_agent.collectors.event_collector import EventCollector
    from sre_agent.collectors.cluster_operator_collector import ClusterOperatorCollector
    from sre_agent.collectors.machine_config_pool_collector import MachineConfigPoolCollector
    from sre_agent.collectors.pod_collector import PodCollector
    from sre_agent.collectors.route_collector import RouteCollector
    from sre_agent.collectors.build_collector import BuildCollector
    from sre_agent.collectors.networking_collector import NetworkingCollector
    from sre_agent.collectors.autoscaling_collector import AutoscalingCollector
    from sre_agent.collectors.proactive_collector import ProactiveCollector
    # Phase 3: Analyzers
    from sre_agent.analyzers.crashloop_analyzer import CrashLoopAnalyzer
    from sre_agent.analyzers.image_pull_analyzer import ImagePullAnalyzer
    from sre_agent.analyzers.route_analyzer import RouteAnalyzer
    from sre_agent.analyzers.build_analyzer import BuildAnalyzer
    from sre_agent.analyzers.networking_analyzer import NetworkingAnalyzer
    from sre_agent.analyzers.autoscaling_analyzer import AutoscalingAnalyzer
    from sre_agent.analyzers.proactive_analyzer import ProactiveAnalyzer
    from sre_agent.analyzers.llm_analyzer import LLMAnalyzer
    from sre_agent.analyzers.unknown_issue_handler import UnknownIssueHandler
    # Phase 3: Handlers
    from sre_agent.handlers.tier1_automated import Tier1AutomatedHandler
    from sre_agent.handlers.tier2_gitops import Tier2GitOpsHandler
    from sre_agent.handlers.tier3_notification import Tier3NotificationHandler

    settings = get_settings()

    print("\n" + "="*60)
    print(f"🚀 OpenShift SRE Agent - Starting up (Mode: {settings.mode})")
    print("="*60)

    # Configure MCP clients from environment variables
    print("\n📋 Loading MCP configuration from environment...")
    openshift_url = os.environ.get("MCP_OPENSHIFT_URL")
    openshift_transport = os.environ.get("MCP_OPENSHIFT_TRANSPORT", "sse")
    gitea_url = os.environ.get("MCP_GITEA_URL")
    gitea_transport = os.environ.get("MCP_GITEA_TRANSPORT", "streamable-http")

    if openshift_url:
        print(f"   OpenShift: {openshift_url} ({openshift_transport})")
        mcp_registry.add_client(MCPClient("openshift", openshift_url, transport=openshift_transport))
    else:
        print("   ⚠️  MCP_OPENSHIFT_URL not set, OpenShift tools unavailable")

    if gitea_url:
        print(f"   Gitea: {gitea_url} ({gitea_transport})")
        mcp_registry.add_client(MCPClient("gitea", gitea_url, transport=gitea_transport))
    else:
        print("   ⚠️  MCP_GITEA_URL not set, Gitea tools unavailable")

    # Initialize all MCP connections
    await mcp_registry.initialize_all()

    total_tools = len(mcp_registry.get_all_tools())
    print(f"\n✅ MCP initialization complete - {total_tools} tools available")

    # Initialize SRE Agent components (workflow engine + watch manager)
    global workflow_engine, watch_manager
    workflow_engine = None
    watch_manager = None

    print("\n🔧 Initializing SRE Agent workflow engine...")

    # Initialize workflow engine
    workflow_engine = WorkflowEngine(mcp_registry)
    await workflow_engine.initialize()

    # Register collectors (Phase 2 + New Route/Build/Networking)
    try:
        workflow_engine.register_collector(EventCollector(mcp_registry))
        workflow_engine.register_collector(ClusterOperatorCollector(mcp_registry))
        workflow_engine.register_collector(MachineConfigPoolCollector(mcp_registry))
        workflow_engine.register_collector(PodCollector(mcp_registry))
        workflow_engine.register_collector(RouteCollector(mcp_registry))
        workflow_engine.register_collector(BuildCollector(mcp_registry))
        workflow_engine.register_collector(NetworkingCollector(mcp_registry))
        workflow_engine.register_collector(AutoscalingCollector(mcp_registry))
        workflow_engine.register_collector(ProactiveCollector(mcp_registry))
        print(f"   ✅ Registered {len(workflow_engine.collectors)} collectors")
    except Exception as e:
        print(f"   ⚠️  Collector registration: {e}")

    # Register analyzers (Phase 3 + New Route/Build/Networking)
    # Note: Register specific analyzers BEFORE LLMAnalyzer (fallback)
    try:
        workflow_engine.register_analyzer(CrashLoopAnalyzer(mcp_registry))
        workflow_engine.register_analyzer(ImagePullAnalyzer(mcp_registry))
        workflow_engine.register_analyzer(RouteAnalyzer(mcp_registry))
        workflow_engine.register_analyzer(BuildAnalyzer(mcp_registry))
        workflow_engine.register_analyzer(NetworkingAnalyzer(mcp_registry))
        workflow_engine.register_analyzer(AutoscalingAnalyzer(mcp_registry))
        workflow_engine.register_analyzer(ProactiveAnalyzer(mcp_registry))
        # LLM analyzer is fallback for known patterns
        workflow_engine.register_analyzer(LLMAnalyzer(mcp_registry))
        # Unknown handler is ULTIMATE fallback - catches ALL undiagnosed issues
        workflow_engine.register_analyzer(UnknownIssueHandler(mcp_registry))
        print(f"   ✅ Registered {len(workflow_engine.analyzers)} analyzers")
    except Exception as e:
        print(f"   ⚠️  Analyzer registration: {e}")

    # Register handlers (Phase 3)
    # Order matters: Tier 1 → Tier 2 → Tier 3
    try:
        workflow_engine.register_handler(Tier1AutomatedHandler(mcp_registry))
        workflow_engine.register_handler(Tier2GitOpsHandler(mcp_registry))
        workflow_engine.register_handler(Tier3NotificationHandler(mcp_registry))
        print(f"   ✅ Registered {len(workflow_engine.handlers)} handlers")
    except Exception as e:
        print(f"   ⚠️  Handler registration: {e}")

    # Print Phase 4 features status
    if settings.knowledge_base_enabled:
        print(f"   ✅ Knowledge base enabled (path: {settings.knowledge_db_path})")
    if settings.prometheus_enabled:
        print(f"   ✅ Prometheus integration enabled (url: {settings.prometheus_url})")

    # Initialize watch-based monitoring
    print("\n👁️  Initializing watch-based real-time monitoring...")
    from sre_agent.watchers.watch_manager import WatchManager

    async def watch_event_callback(resource_type: str, event_data: dict):
        """
        Callback invoked when a watcher detects an event.

        Triggers targeted workflow execution for the specific event.
        """
        logger.info(
            f"Watch event detected: {resource_type}",
            resource_type=resource_type,
            event_name=event_data.get('name'),
            event_namespace=event_data.get('namespace')
        )

        # For now, trigger full workflow
        # In future, could optimize to only run relevant collectors/analyzers
        try:
            stats = await workflow_engine.run_workflow()
            logger.info(
                f"Workflow completed for {resource_type} event",
                resource_type=resource_type,
                stats=stats
            )
        except Exception as e:
            logger.error(f"Workflow failed for {resource_type} event: {e}", exc_info=True)

    watch_manager = WatchManager(watch_event_callback)
    await watch_manager.start_all()
    print(f"   ✅ Watch manager started with {len(watch_manager.watchers)} watchers")
    print("      - Pod watcher: CrashLoopBackOff, OOMKilled, ImagePullBackOff")
    print("      - Event watcher: Warning events cluster-wide")

    print("\n✅ Startup complete - Agent watching cluster in real-time")
    print("="*60 + "\n")

    yield

    # Shutdown - stop watchers and cleanup
    print("\n🛑 Shutting down SRE Agent...")
    if watch_manager:
        await watch_manager.stop_all()
        print("   ✅ Watch manager stopped")
    print("✅ Shutdown complete")


app = FastAPI(title="Pipeline Failure Agent", lifespan=lifespan)

MODEL_PROMPT = """You are a helpful assistant. You have access to a number of tools.
Whenever a tool is called, be sure to return the Response in a friendly and helpful tone.
"""

PROMPT_TEMPLATE = """You are an expert OpenShift administrator. Your task is to analyze pod logs, summarize the error, and generate a JSON object to create a Gitea issue for tracking. Follow the format in the examples below.

---
EXAMPLE 1:
Input: The logs for pod 'frontend-v2-abcde' in namespace 'webapp' show: ImagePullBackOff: Back-off pulling image 'my-registry/frontend:latest'.

Output:
The pod is in an **ImagePullBackOff** state. This means Kubernetes could not pull the container image 'my-registry/frontend:latest', likely due to an incorrect image tag or authentication issues.
{{"name":"create_issue","arguments":{{"owner":"{gitea_owner}","repo":"{gitea_repo}","title":"Issue with pipeline","body":"### Cluster/namespace location\\nwebapp/frontend-v2-abcde\\n\\n### Summary of the problem\\nThe pod is failing to start due to an ImagePullBackOff error.\\n\\n### Detailed error/code\\nImagePullBackOff: Back-off pulling image 'my-registry/frontend:latest'\\n\\n### Possible solutions\\n1. Verify the image tag 'latest' exists in the 'my-registry/frontend' repository.\\n2. Check for authentication errors with the image registry."}}}}

---
EXAMPLE 2:
Input: The logs for pod 'data-processor-xyz' in namespace 'pipelines' show: CrashLoopBackOff. Last state: OOMKilled.

Output:
The pod is in a **CrashLoopBackOff** state because it was **OOMKilled**. The container tried to use more memory than its configured limit.
{{"name":"create_issue","arguments":{{"owner":"{gitea_owner}","repo":"{gitea_repo}","title":"Issue with pipeline","body":"### Cluster/namespace location\\npipelines/data-processor-xyz\\n\\n### Summary of the problem\\nThe pod is in a CrashLoopBackOff state because it was OOMKilled (Out of Memory).\\n\\n### Detailed error/code\\nCrashLoopBackOff, Last state: OOMKilled\\n\\n### Possible solutions\\n1. Increase the memory limit in the pod's deployment configuration.\\n2. Analyze the application for memory leaks."}}}}
---

NOW, YOUR TURN:

Steps:
1. First, get the pod logs using: {{"name":"pods_log","arguments":{{"namespace":"{namespace}","name":"{pod_name}","tailLines":10}}}}
2. Analyze the logs for errors
3. Create a Gitea issue with the error summary using: {{"name":"create_issue","arguments":{{"owner":"{gitea_owner}","repo":"{gitea_repo}","title":"Issue with Agent pipeline","body":"<summary of the error>"}}}}

Start by getting the logs for pod '{pod_name}' in namespace '{namespace}'.
"""


class FailureReport(BaseModel):
    namespace: str
    pod_name: str
    container_name: str = None


def extract_json_tool_call(content: str, valid_tool_names: list[str] = None) -> dict | None:
    """Extract a JSON tool call from text content.

    Args:
        content: The text content to search for JSON tool calls
        valid_tool_names: List of valid tool names to match against
    """
    import re

    def is_valid_tool_call(parsed: dict) -> bool:
        """Check if parsed JSON is a valid tool call."""
        if "name" not in parsed:
            return False
        if valid_tool_names and parsed["name"] not in valid_tool_names:
            return False
        return True

    # Try to find all JSON objects in the content
    candidates = []

    # Find all potential JSON objects by matching braces
    i = 0
    while i < len(content):
        if content[i] == '{':
            depth = 0
            start = i
            for j in range(i, len(content)):
                if content[j] == '{':
                    depth += 1
                elif content[j] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(content[start:j+1])
                            if is_valid_tool_call(parsed):
                                candidates.append(parsed)
                        except json.JSONDecodeError:
                            pass
                        i = j
                        break
        i += 1

    # Return the first valid tool call found
    if candidates:
        return candidates[0]

    return None


async def run_agent(namespace: str, pod_name: str, container_name: str = None) -> str:
    """Run the agent to analyze a failed pod and create an issue."""
    print(f"\n🚀 Starting agent run...")
    print(f"   Pod: {pod_name}")
    print(f"   Namespace: {namespace}")
    print(f"   Container: {container_name or '(default)'}")

    gitea_owner = os.environ.get("MCP_GITEA_USER", "user1")
    gitea_repo = os.environ.get("MCP_GITEA_REPO", "mcp")

    formatted_prompt = PROMPT_TEMPLATE.format(
        pod_name=pod_name,
        namespace=namespace,
        gitea_owner=gitea_owner,
        gitea_repo=gitea_repo
    )
    print(f"\n📝 Prompt prepared ({len(formatted_prompt)} chars)")
    print(f"   Gitea target: {gitea_owner}/{gitea_repo}")

    litellm_url = os.environ.get("LITELLM_URL", "")
    litellm_api_key = os.environ.get("LITELLM_API_KEY", "")
    litellm_model = os.environ.get("LITELLM_MODEL", "openai/Llama-4-Scout-17B-16E-W4A16")

    print(f"\n🤖 LLM Configuration:")
    print(f"   Model: {litellm_model}")
    print(f"   API Base: {litellm_url or '(default)'}")

    messages = [
        {"role": "system", "content": MODEL_PROMPT},
        {"role": "user", "content": formatted_prompt}
    ]

    # Get tools from MCP servers
    tools = mcp_registry.get_all_tools()
    tool_names = [t["function"]["name"] for t in tools]
    print(f"\n🔧 Available tools ({len(tools)}): {tool_names}")

    if not tools:
        print("❌ No tools available!")
        return "Error: No tools available from MCP servers"

    max_iterations = 10
    iteration = 0

    print(f"\n{'='*60}")
    print("Starting agent loop (max {max_iterations} iterations)")
    print(f"{'='*60}")

    while iteration < max_iterations:
        iteration += 1
        print(f"\n┌─ Iteration {iteration}/{max_iterations} ─────────────────────────────────┐")

        try:
            print("│  📡 Calling LLM...")
            completion_kwargs = {
                "model": litellm_model,
                "messages": messages,
                "tools": tools,
                "api_key": litellm_api_key
            }
            if litellm_url:
                completion_kwargs["api_base"] = litellm_url

            response = await asyncio.to_thread(
                litellm.completion,
                **completion_kwargs
            )
            print("│  ✓ LLM response received")
        except Exception as e:
            print(f"│  ❌ LLM error: {str(e)}")
            return f"Error calling LiteLLM: {str(e)}"

        choice = response.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason
        print(f"│  Finish reason: {finish_reason}")

        if message.tool_calls:
            print(f"│  📞 Model requested {len(message.tool_calls)} tool call(s)")
            messages.append(message.model_dump())

            for i, tool_call in enumerate(message.tool_calls, 1):
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                print(f"│")
                print(f"│  🔧 Tool call {i}/{len(message.tool_calls)}: {tool_name}")
                print(f"│     Arguments: {json.dumps(arguments, indent=2).replace(chr(10), chr(10) + '│     ')}")
                print(f"│     Executing...")
                try:
                    result = await mcp_registry.call_tool(tool_name, arguments)
                    print(f"│     ✓ Tool completed successfully")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    result = f"Error calling tool: {str(e)}"
                    print(f"│     ❌ Tool failed: {str(e)}")

                result_preview = result[:200] + "..." if len(result) > 200 else result
                print(f"│     Result: {result_preview}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
        else:
            content = message.content or ""
            print(f"│  💬 Model returned text response")

            # Show a preview of the content
            content_preview = content[:150].replace('\n', ' ')
            if len(content) > 150:
                content_preview += "..."
            print(f"│     Preview: {content_preview}")

            # Check if the model output a JSON tool call in text form
            available_tool_names = [t["function"]["name"] for t in tools]
            json_tool_call = extract_json_tool_call(content, available_tool_names)
            if json_tool_call:
                tool_name = json_tool_call.get("name")
                arguments = json_tool_call.get("arguments") or json_tool_call.get("parameters", {})

                print(f"│")
                print(f"│  🔍 Found JSON tool call in text: {tool_name}")
                print(f"│     Arguments: {json.dumps(arguments, indent=2).replace(chr(10), chr(10) + '│     ')}")
                print(f"│     Executing...")
                try:
                    result = await mcp_registry.call_tool(tool_name, arguments)
                    print(f"│     ✓ Tool completed successfully")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    result = f"Error calling tool: {str(e)}"
                    print(f"│     ❌ Tool failed: {str(e)}")

                result_preview = result[:200] + "..." if len(result) > 200 else result
                print(f"│     Result: {result_preview}")

                # If create_issue was successful, we're done
                # Check for actual errors (starts with "Error:" or contains error JSON key)
                is_error = result.startswith("Error:") or '"error":' in result.lower()
                if tool_name == "create_issue" and not is_error:
                    print(f"│")
                    print(f"└─ ✅ Agent completed: Issue created successfully")
                    return f"Issue created: {result}"

                # Add the response and tool result to continue the conversation
                print(f"│  ↩ Continuing conversation with tool result...")
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"Tool result:\n{result}\n\nPlease continue with your analysis and create the issue."})
            else:
                print(f"│")
                print(f"└─ ✅ Agent completed with final response")
                print(f"\n{'─'*60}")
                print(f"Final response:\n{content}")
                print(f"{'─'*60}")
                return content

    print(f"\n⚠️ Agent reached maximum iterations ({max_iterations}) without completing")
    return "Agent reached maximum iterations without completing."


@app.post("/report-failure")
async def report_failure(report: FailureReport):
    """Handle a pipeline failure report and analyze it."""
    print(f"\n{'='*60}")
    print(f"📥 Received failure report")
    print(f"{'='*60}")
    print(f"   Namespace: {report.namespace}")
    print(f"   Pod:       {report.pod_name}")
    print(f"   Container: {report.container_name or '(not specified)'}")

    try:
        result = await run_agent(
            namespace=report.namespace,
            pod_name=report.pod_name,
            container_name=report.container_name
        )
        print(f"\n{'='*60}")
        print(f"📤 Sending response: success")
        print(f"{'='*60}\n")
        return {"status": "success", "result": result}
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"📤 Sending response: error - {str(e)}")
        print(f"{'='*60}\n")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check endpoint."""
    from sre_agent.config.settings import get_settings
    settings = get_settings()

    health_data = {
        "status": "healthy",
        "mode": "watch-based",
        "mcp_tools": len(mcp_registry.get_all_tools()),
    }

    # Add workflow engine stats if available
    if workflow_engine:
        health_data["workflow_engine"] = workflow_engine.get_stats()

    # Add watch manager stats
    if watch_manager:
        health_data["watch_manager"] = watch_manager.get_stats()

    return health_data


@app.post("/trigger-workflow")
async def trigger_workflow():
    """
    Manually trigger a full workflow run.

    The agent normally reacts in real-time via Kubernetes watches.
    This endpoint is provided for manual testing and on-demand full cluster scans.

    Returns workflow statistics including observations, diagnoses, and remediations.
    """
    if not workflow_engine:
        raise HTTPException(
            status_code=503,
            detail="Workflow engine not initialized"
        )

    try:
        # Run workflow directly
        stats = await workflow_engine.run_workflow()

        return {
            "status": "success",
            "message": "Workflow execution complete",
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class RemediationApprovalRequest(BaseModel):
    """Request model for remediation approval."""
    diagnosis_id: str
    approved: bool


@app.post("/approve-remediation")
async def approve_remediation(request: RemediationApprovalRequest):
    """
    Approve or reject a remediation request.

    When the agent detects an issue, it sends a Slack notification
    requesting approval. Users respond by calling this endpoint.

    Args:
        diagnosis_id: The diagnosis ID to approve/reject
        approved: True to approve, False to reject

    Returns:
        Confirmation message
    """
    if not workflow_engine:
        raise HTTPException(
            status_code=503,
            detail="Workflow engine not initialized"
        )

    try:
        from sre_agent.utils.event_deduplicator import get_event_deduplicator

        deduplicator = get_event_deduplicator()

        if request.approved:
            # Approve remediation
            success = deduplicator.approve_remediation_by_id(request.diagnosis_id)

            if success:
                logger.info(
                    f"Remediation approved by user",
                    diagnosis_id=request.diagnosis_id
                )

                return {
                    "status": "success",
                    "message": f"✅ Remediation approved for diagnosis {request.diagnosis_id}",
                    "diagnosis_id": request.diagnosis_id,
                    "action": "Will remediate on next workflow cycle (within 1 minute)",
                    "timestamp": datetime.utcnow().isoformat()
                }
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Diagnosis ID {request.diagnosis_id} not found. It may have already been processed or is too old."
                )
        else:
            logger.info(
                f"Remediation rejected by user",
                diagnosis_id=request.diagnosis_id
            )

            return {
                "status": "success",
                "message": f"❌ Remediation rejected for diagnosis {request.diagnosis_id}",
                "diagnosis_id": request.diagnosis_id,
                "action": "No action will be taken. Issue will be monitored for changes.",
                "timestamp": datetime.utcnow().isoformat()
            }

    except Exception as e:
        logger.error(f"Approval processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/index-docs")
async def index_internal_docs():
    """
    Index internal documentation for RAG (Tier 2).

    Requires RAG_ENABLED=true in configuration.
    """
    try:
        from sre_agent.knowledge import get_kb_retriever

        kb_retriever = get_kb_retriever()

        if not kb_retriever.rag_enabled:
            raise HTTPException(
                status_code=400,
                detail="RAG is not enabled. Set RAG_ENABLED=true in configuration."
            )

        count = await kb_retriever.index_internal_docs()

        return {
            "status": "success",
            "message": f"Indexed {count} document chunks",
            "chunks_indexed": count
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document indexing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(e)}")


class ResolutionSubmission(BaseModel):
    """Request model for submitting unknown issue resolution."""
    root_cause: str
    fix_applied: str
    fix_commands: Optional[list[str]] = None
    works_for_similar: bool = True
    notes: Optional[str] = None
    sre_name: Optional[str] = None


@app.get("/unknown-issues")
async def list_unknown_issues(
    min_occurrences: int = 1,
    limit: int = 50
):
    """
    List unresolved unknown issues for SRE investigation.

    Query Parameters:
        min_occurrences: Minimum occurrence count (default: 1)
        limit: Maximum number to return (default: 50)

    Returns list of unknown issues sorted by severity and occurrence.
    """
    try:
        from sre_agent.stores.unknown_issue_store import get_unknown_store

        unknown_store = get_unknown_store()
        issues = await unknown_store.get_unresolved_issues(
            min_occurrences=min_occurrences,
            limit=limit
        )

        # Convert to JSON-serializable format
        issues_data = []
        for issue in issues:
            issues_data.append({
                "fingerprint": issue.fingerprint,
                "first_seen": issue.first_seen.isoformat(),
                "last_seen": issue.last_seen.isoformat(),
                "occurrence_count": issue.occurrence_count,
                "category": issue.category,
                "severity_score": issue.severity_score,
                "namespace": issue.observation_data.get("namespace"),
                "resource_name": issue.observation_data.get("resource_name"),
                "resource_kind": issue.observation_data.get("resource_kind"),
                "error_patterns": issue.error_patterns[:3],  # First 3 patterns
                "investigation_url": f"/unknown-issues/{issue.fingerprint}"
            })

        return {
            "status": "success",
            "total": len(issues_data),
            "issues": issues_data
        }

    except Exception as e:
        logger.error(f"Failed to list unknown issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/unknown-issues/{fingerprint}")
async def get_unknown_issue(fingerprint: str):
    """
    Get detailed information about a specific unknown issue.

    Returns full investigation notes, evidence, and resolution form.
    """
    try:
        from sre_agent.stores.unknown_issue_store import get_unknown_store

        unknown_store = get_unknown_store()
        issue = await unknown_store.get_issue_by_fingerprint(fingerprint)

        if not issue:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown issue with fingerprint {fingerprint} not found"
            )

        return {
            "status": "success",
            "issue": {
                "fingerprint": issue.fingerprint,
                "first_seen": issue.first_seen.isoformat(),
                "last_seen": issue.last_seen.isoformat(),
                "occurrence_count": issue.occurrence_count,
                "category": issue.category,
                "severity_score": issue.severity_score,
                "resolved": issue.resolved,
                "resolution_data": issue.resolution_data,
                "observation": issue.observation_data,
                "error_patterns": issue.error_patterns,
                "investigation_notes": issue.investigation_notes,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get unknown issue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/unknown-issues/{fingerprint}/resolve")
async def resolve_unknown_issue(
    fingerprint: str,
    resolution: ResolutionSubmission
):
    """
    Submit resolution for an unknown issue.

    SREs use this endpoint to teach the agent how they fixed unknown issues.
    The agent will learn from this and potentially auto-fix similar issues.

    Args:
        fingerprint: Issue fingerprint
        resolution: Resolution details (root cause, fix, commands)

    Returns confirmation and next steps (pattern discovery, etc.)
    """
    try:
        from sre_agent.stores.unknown_issue_store import get_unknown_store

        unknown_store = get_unknown_store()

        # Verify issue exists
        issue = await unknown_store.get_issue_by_fingerprint(fingerprint)
        if not issue:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown issue with fingerprint {fingerprint} not found"
            )

        if issue.resolved:
            raise HTTPException(
                status_code=400,
                detail=f"Issue {fingerprint} is already marked as resolved"
            )

        # Build resolution data
        resolution_data = {
            "root_cause": resolution.root_cause,
            "fix_applied": resolution.fix_applied,
            "fix_commands": resolution.fix_commands or [],
            "works_for_similar": resolution.works_for_similar,
            "notes": resolution.notes or "",
            "sre_name": resolution.sre_name or "anonymous",
            "submitted_at": datetime.utcnow().isoformat(),
            "fingerprint": fingerprint
        }

        # Mark as resolved
        success = await unknown_store.mark_resolved(fingerprint, resolution_data)

        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to mark issue as resolved"
            )

        logger.info(
            "Unknown issue resolved by SRE",
            fingerprint=fingerprint,
            sre_name=resolution.sre_name,
            root_cause=resolution.root_cause[:100]
        )

        return {
            "status": "success",
            "message": f"✅ Resolution recorded for unknown issue {fingerprint}",
            "fingerprint": fingerprint,
            "next_steps": [
                "Resolution stored in knowledge base",
                "Similar issues will reference this solution",
                "Pattern discovery engine will analyze for auto-fix potential",
                f"If {issue.occurrence_count} similar issues occur, pattern may be promoted to analyzer"
            ],
            "impact": {
                "similar_issues_helped": f"Future occurrences of this pattern",
                "learning_enabled": True,
                "auto_fix_potential": resolution.works_for_similar
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resolve unknown issue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/unknown-issues/stats/summary")
async def get_unknown_stats():
    """
    Get statistics about unknown issues.

    Returns counts, resolution rates, trends, etc.
    """
    try:
        from sre_agent.stores.unknown_issue_store import get_unknown_store

        unknown_store = get_unknown_store()
        stats = await unknown_store.get_stats()

        return {
            "status": "success",
            "unknown_issues": stats
        }

    except Exception as e:
        logger.error(f"Failed to get unknown stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
async def get_stats():
    """
    Get agent statistics.

    Returns stats about workflow executions, observations, diagnoses, etc.
    """
    from sre_agent.config.settings import get_settings
    from sre_agent.utils.audit_logger import get_audit_logger

    settings = get_settings()
    stats = {
        "mode": settings.mode,
        "mcp_tools": len(mcp_registry.get_all_tools()),
    }

    # Add workflow engine stats
    if workflow_engine:
        stats["workflow_engine"] = workflow_engine.get_stats()

    # Add watch manager stats (watch-based mode)
    if watch_manager:
        stats["watch_manager"] = watch_manager.get_stats()

    # Add audit log stats
    try:
        audit_logger = get_audit_logger(settings.audit_db_path)
        audit_stats = await audit_logger.get_stats()
        stats["audit"] = audit_stats
    except Exception as e:
        stats["audit"] = {"error": str(e)}

    # Add KB retriever stats
    try:
        from sre_agent.knowledge import get_kb_retriever
        kb_retriever = get_kb_retriever()
        stats["kb_retriever"] = kb_retriever.get_stats()
    except Exception as e:
        stats["kb_retriever"] = {"error": str(e)}

    # Add unknown issue stats
    try:
        from sre_agent.stores.unknown_issue_store import get_unknown_store
        unknown_store = get_unknown_store()
        unknown_stats = await unknown_store.get_stats()
        stats["unknown_issues"] = unknown_stats
    except Exception as e:
        stats["unknown_issues"] = {"error": str(e)}

    return stats


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,  # Explicitly disable auto-reload
        log_level="info"
    )

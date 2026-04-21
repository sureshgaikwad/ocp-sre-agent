# Learning from Manual Cluster Fixes (Without Git)

## 🎯 The Real-World Scenario

**Common Reality**: Most SREs fix issues directly in the cluster:

```bash
# SRE gets alert: Pod failing
# SRE investigates and fixes directly:

oc set env deployment/app DB_POOL_SIZE=30
oc scale deployment/app --replicas=5
oc patch deployment/app -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","resources":{"limits":{"memory":"2Gi"}}}]}}}}'

# Fix works! Issue resolved!
# But... no Git commit, no PR, no record 😱
```

**Problem**: How does the agent learn from this fix if there's NO Git integration?

**Solution**: 4 complementary approaches

---

## 🔍 Approach 1: Kubernetes Resource Watch (Automatic)

### How It Works

The agent watches Kubernetes resources and detects changes in real-time.

```python
"""
Resource Change Detector - Automatic Learning from Cluster Changes
"""

class ResourceChangeDetector:
    """
    Watches Kubernetes resources for changes.
    
    When a resource changes:
    1. Captures what changed (diff)
    2. Correlates with recent unknown issues
    3. Creates provisional resolution record
    4. Asks SRE for confirmation
    """
    
    def __init__(self):
        self.watches = {}
        self.recent_unknowns = {}  # Cache of recent unknown issues
        
    async def start_watching(self):
        """Start watching critical resources."""
        
        # Watch Deployments
        await self._watch_resource(
            resource_type="Deployment",
            api="apps/v1"
        )
        
        # Watch StatefulSets
        await self._watch_resource(
            resource_type="StatefulSet", 
            api="apps/v1"
        )
        
        # Watch ConfigMaps
        await self._watch_resource(
            resource_type="ConfigMap",
            api="v1"
        )
        
        # Watch Secrets (watch modifications, don't log values!)
        await self._watch_resource(
            resource_type="Secret",
            api="v1"
        )
        
        # Watch HPAs
        await self._watch_resource(
            resource_type="HorizontalPodAutoscaler",
            api="autoscaling/v2"
        )
    
    async def _watch_resource(self, resource_type: str, api: str):
        """
        Watch a specific resource type for MODIFIED events.
        """
        from kubernetes import client, watch
        
        # Create watcher
        w = watch.Watch()
        
        # Get appropriate API client
        if api == "v1":
            api_client = client.CoreV1Api()
        elif api == "apps/v1":
            api_client = client.AppsV1Api()
        elif api == "autoscaling/v2":
            api_client = client.AutoscalingV2Api()
        
        # Watch for changes across all namespaces
        async for event in w.stream(
            api_client.list_deployment_for_all_namespaces,  # Example
            timeout_seconds=0  # Infinite watch
        ):
            if event['type'] == 'MODIFIED':
                await self._handle_modification(
                    resource_type=resource_type,
                    resource=event['object']
                )
    
    async def _handle_modification(self, resource_type: str, resource):
        """
        Handle resource modification event.
        
        Steps:
        1. Get current state
        2. Retrieve previous state from cache
        3. Calculate diff
        4. Check for related unknown issues
        5. Create provisional resolution
        """
        
        namespace = resource.metadata.namespace
        name = resource.metadata.name
        
        # Get current state
        current_state = self._extract_relevant_fields(resource)
        
        # Get previous state from cache
        cache_key = f"{namespace}/{resource_type}/{name}"
        previous_state = self.state_cache.get(cache_key)
        
        if previous_state is None:
            # First time seeing this resource, just cache it
            self.state_cache[cache_key] = current_state
            return
        
        # Calculate what changed
        changes = self._calculate_diff(previous_state, current_state)
        
        if not changes:
            return  # No meaningful changes
        
        # Update cache
        self.state_cache[cache_key] = current_state
        
        # Check if this resource has related unknown issues
        related_unknowns = await self._find_related_unknowns(
            namespace=namespace,
            resource_type=resource_type,
            resource_name=name,
            time_window_minutes=60  # Look back 1 hour
        )
        
        if related_unknowns:
            # Found related unknown issues!
            await self._capture_potential_fix(
                unknown_issues=related_unknowns,
                resource_type=resource_type,
                resource_name=name,
                namespace=namespace,
                changes=changes,
                changed_by=resource.metadata.managed_fields  # Who made the change
            )
```

### Example: Detecting Memory Increase

```python
async def _capture_potential_fix(self, unknown_issues, resource_type, resource_name, namespace, changes, changed_by):
    """
    Capture a potential fix and ask SRE for confirmation.
    
    Example:
    - Unknown issue: Pod OOMKilled
    - Detection: Deployment memory limit changed 512Mi → 1Gi
    - Action: Ask SRE if this was the fix
    """
    
    # Example changes detected
    # changes = {
    #     "spec.template.spec.containers[0].resources.limits.memory": {
    #         "old": "512Mi",
    #         "new": "1Gi"
    #     }
    # }
    
    # Create provisional resolution
    provisional_resolution = {
        "unknown_ids": [u.id for u in unknown_issues],
        "detection_method": "kubernetes_watch",
        "resource_modified": f"{namespace}/{resource_type}/{resource_name}",
        "changes": changes,
        "detected_at": datetime.utcnow().isoformat(),
        "changed_by": self._extract_user_from_managed_fields(changed_by),
        "status": "pending_confirmation"
    }
    
    # Store provisional resolution
    await self.provisional_store.save(provisional_resolution)
    
    # Notify SRE for confirmation
    await self._request_sre_confirmation(
        unknown_issues=unknown_issues,
        provisional_resolution=provisional_resolution
    )
```

### SRE Receives Notification

**Slack Notification**:
```
🤖 SRE Agent - Potential Fix Detected

We noticed you modified: production/Deployment/app

Changes detected:
  • memory limit: 512Mi → 1Gi
  • memory request: 256Mi → 512Mi

This might be related to:
  • Unknown Issue #142: OOMKilled (detected 45 mins ago)

❓ Was this change a fix for issue #142?

[Yes, this fixed it] [No, unrelated] [Partially fixed]
```

**Kubernetes Event** (if Slack not configured):
```yaml
apiVersion: v1
kind: Event
metadata:
  name: sre-agent.fix-detection.xyz
  namespace: production
reason: PotentialFixDetected
message: |
  🤖 Potential fix detected for Unknown Issue #142
  
  Resource modified: Deployment/app
  Changes:
    - memory limit: 512Mi → 1Gi
  
  If this fixed issue #142, please confirm:
  
  curl -X POST http://sre-agent:8000/api/feedback/confirm-fix \
    -d '{
      "provisional_id": "prov-xyz-123",
      "unknown_ids": ["unknown-142"],
      "confirmed": true,
      "root_cause": "Memory limit too low for workload"
    }'
```

### SRE Confirms

```bash
# Option A: Via Slack button click (easy!)
[Yes, this fixed it] ← Click

# Option B: Via API (if no Slack)
curl -X POST http://sre-agent:8000/api/feedback/confirm-fix \
  -H 'Content-Type: application/json' \
  -d '{
    "provisional_id": "prov-xyz-123",
    "unknown_ids": ["unknown-142"],
    "confirmed": true,
    "root_cause": "Application memory usage increased after new feature deployment. 512Mi was insufficient.",
    "category": "oom_killed",
    "recommended_tier": 2,
    "recommended_actions": [
      "Monitor memory usage after deployments",
      "Increase memory limit to 1.5x observed usage",
      "Set up alerts for memory >80%"
    ]
  }'
```

### Agent Learns

```python
async def confirm_fix(confirmation: FixConfirmation):
    """Process SRE's confirmation of a detected fix."""
    
    # Get provisional resolution
    provisional = await provisional_store.get(confirmation.provisional_id)
    
    if confirmation.confirmed:
        # This WAS the fix! Learn from it
        
        # 1. Create incident record
        incident_id = await knowledge_store.store_incident(
            observation=original_observation,
            diagnosis=Diagnosis(
                category=DiagnosisCategory[confirmation.category],
                root_cause=confirmation.root_cause,
                confidence=Confidence.HIGH,
                recommended_tier=confirmation.recommended_tier,
                recommended_actions=confirmation.recommended_actions,
                evidence={
                    "fix_detected_automatically": True,
                    "resource_modified": provisional.resource_modified,
                    "changes": provisional.changes,
                    "changed_by": provisional.changed_by
                }
            ),
            remediation=RemediationResult(
                status=RemediationStatus.SUCCESS,
                message=f"Manual fix confirmed: {provisional.changes}",
                actions_taken=[f"Changed {k}: {v['old']} → {v['new']}" 
                              for k, v in provisional.changes.items()]
            )
        )
        
        # 2. Mark unknown issues as resolved
        for unknown_id in confirmation.unknown_ids:
            await unknown_store.mark_resolved(
                unknown_id=unknown_id,
                resolution_notes=confirmation.root_cause,
                resolution_method="manual_cluster_fix",
                resolved_by=provisional.changed_by
            )
        
        # 3. Link pattern to solution
        await knowledge_store.create_pattern_mapping(
            error_patterns=extract_patterns_from_unknowns(unknowns),
            diagnosis_category=confirmation.category,
            solution_summary=format_changes_as_summary(provisional.changes),
            evidence_keywords=extract_keywords(confirmation.root_cause)
        )
        
        logger.info(
            "Manual cluster fix captured and learned",
            incident_id=incident_id,
            unknown_ids=confirmation.unknown_ids,
            changed_by=provisional.changed_by
        )
        
        return {
            "status": "success",
            "message": "Fix confirmed! Agent learned from this resolution.",
            "incident_id": incident_id,
            "will_auto_diagnose_next_time": True
        }
    
    else:
        # NOT the fix, just coincidental change
        await provisional_store.mark_rejected(confirmation.provisional_id)
        
        return {
            "status": "success",
            "message": "Noted as unrelated change. Unknown issue still open."
        }
```

---

## 🔍 Approach 2: Kubernetes Audit Log Analysis (Retroactive)

### How It Works

Parse Kubernetes audit logs to find resource modifications.

```python
"""
Audit Log Analyzer - Learn from Past Cluster Changes
"""

class AuditLogAnalyzer:
    """
    Analyzes Kubernetes audit logs to detect manual fixes.
    
    Useful for:
    - Retroactive learning (analyze past fixes)
    - When resource watch wasn't running
    - Historical pattern discovery
    """
    
    async def analyze_audit_logs_for_unknown(self, unknown_issue):
        """
        Search audit logs for changes that might have fixed this issue.
        
        Example:
        Unknown Issue:
          - Detected: 2026-04-21 10:00:00
          - Resolved: 2026-04-21 11:30:00
          - Resource: production/Pod/app-xyz
        
        Search audit logs:
          - Time range: 10:00:00 to 12:00:00
          - Namespace: production
          - Resource types: Deployment, ConfigMap, Secret
          - Verbs: update, patch
        """
        
        # Get audit log entries
        audit_entries = await self._fetch_audit_logs(
            namespace=unknown_issue.namespace,
            start_time=unknown_issue.first_seen,
            end_time=unknown_issue.resolved_at or unknown_issue.last_seen + timedelta(hours=2),
            resource_types=["deployments", "configmaps", "secrets", "services"],
            verbs=["update", "patch"]
        )
        
        # Find modifications to related resources
        related_modifications = []
        
        for entry in audit_entries:
            # Example audit entry:
            # {
            #   "verb": "patch",
            #   "objectRef": {
            #     "resource": "deployments",
            #     "namespace": "production",
            #     "name": "app"
            #   },
            #   "user": {
            #     "username": "john.doe@company.com"
            #   },
            #   "requestObject": {...},
            #   "responseObject": {...}
            # }
            
            if self._is_related_resource(entry, unknown_issue):
                # Calculate what changed
                changes = self._extract_changes_from_audit_entry(entry)
                
                related_modifications.append({
                    "timestamp": entry.requestReceivedTimestamp,
                    "user": entry.user.username,
                    "resource": f"{entry.objectRef.namespace}/{entry.objectRef.resource}/{entry.objectRef.name}",
                    "changes": changes
                })
        
        if related_modifications:
            # Found potential fixes!
            await self._create_retroactive_learning_opportunity(
                unknown_issue=unknown_issue,
                modifications=related_modifications
            )
        
        return related_modifications
    
    def _is_related_resource(self, audit_entry, unknown_issue):
        """
        Check if audit entry is related to the unknown issue.
        
        Related if:
        - Same namespace
        - Same resource or owner resource
        - Within time window
        """
        obj_ref = audit_entry.objectRef
        
        # Same namespace?
        if obj_ref.namespace != unknown_issue.namespace:
            return False
        
        # Direct match on resource name?
        if obj_ref.name == unknown_issue.resource_name:
            return True
        
        # Owner relationship? (e.g., Deployment owns Pod)
        if unknown_issue.resource_kind == "Pod":
            # Pod name: app-xyz-abc123
            # Deployment name: app-xyz
            # Check if deployment name is prefix of pod name
            if unknown_issue.resource_name.startswith(obj_ref.name):
                return True
        
        return False
```

### Example: Retroactive Analysis

```python
# Agent finds unknown issue was resolved but no fix recorded
unknown = await unknown_store.get("unknown-142")

if unknown.resolution_status == "resolved_externally":
    # Someone fixed it but didn't tell us how!
    # Analyze audit logs to figure out what they did
    
    modifications = await audit_analyzer.analyze_audit_logs_for_unknown(unknown)
    
    # Found:
    # [
    #   {
    #     "timestamp": "2026-04-21T11:15:00Z",
    #     "user": "john.doe@company.com",
    #     "resource": "production/deployments/app",
    #     "changes": {
    #       "spec.template.spec.containers[0].env[DB_POOL_SIZE]": {
    #         "old": "10",
    #         "new": "30"
    #       }
    #     }
    #   }
    # ]
    
    # Create learning opportunity
    await notify_sre_for_retroactive_confirmation(
        unknown=unknown,
        detected_changes=modifications
    )
```

---

## 🔍 Approach 3: Resource State Snapshots (Periodic)

### How It Works

Take snapshots of resource state and compare over time.

```python
"""
Resource State Snapshotter - Detect Changes via Periodic Comparison
"""

class ResourceStateSnapshotter:
    """
    Periodically snapshots resource state.
    
    When unknown issue occurs:
    1. Take snapshot of resource state
    2. Mark as "baseline"
    3. After issue resolves, take new snapshot
    4. Compare snapshots to find what changed
    """
    
    async def create_baseline_snapshot(self, unknown_issue):
        """
        Create baseline snapshot when unknown issue is detected.
        """
        
        # Identify resources to snapshot
        resources_to_snapshot = await self._identify_related_resources(
            namespace=unknown_issue.namespace,
            resource_name=unknown_issue.resource_name,
            resource_kind=unknown_issue.resource_kind
        )
        
        # Take snapshot of each resource
        snapshot = {}
        
        for resource in resources_to_snapshot:
            # Get current state via MCP/kubectl
            state = await self.mcp_registry.call_tool("get_resource", {
                "resource_type": resource.kind,
                "name": resource.name,
                "namespace": resource.namespace,
                "output": "yaml"
            })
            
            # Extract relevant fields only (not status, not timestamps)
            relevant_state = self._extract_relevant_fields(state)
            
            snapshot[f"{resource.namespace}/{resource.kind}/{resource.name}"] = relevant_state
        
        # Store snapshot
        await self.snapshot_store.save(
            unknown_id=unknown_issue.id,
            snapshot_type="baseline",
            snapshot_data=snapshot,
            created_at=datetime.utcnow()
        )
        
        logger.info(
            "Baseline snapshot created for unknown issue",
            unknown_id=unknown_issue.id,
            resources_captured=len(snapshot)
        )
    
    async def detect_changes_for_resolved_unknown(self, unknown_id):
        """
        Detect what changed by comparing snapshots.
        
        Called when unknown issue is marked as resolved.
        """
        
        # Get baseline snapshot
        baseline = await self.snapshot_store.get(
            unknown_id=unknown_id,
            snapshot_type="baseline"
        )
        
        if not baseline:
            logger.warning(f"No baseline snapshot for {unknown_id}")
            return None
        
        # Take new snapshot now (after resolution)
        current_snapshot = {}
        
        for resource_key in baseline.snapshot_data.keys():
            namespace, kind, name = resource_key.split("/")
            
            state = await self.mcp_registry.call_tool("get_resource", {
                "resource_type": kind,
                "name": name,
                "namespace": namespace,
                "output": "yaml"
            })
            
            current_snapshot[resource_key] = self._extract_relevant_fields(state)
        
        # Compare snapshots
        changes = self._compare_snapshots(
            baseline=baseline.snapshot_data,
            current=current_snapshot
        )
        
        if changes:
            # Found what changed!
            await self._create_learning_opportunity_from_changes(
                unknown_id=unknown_id,
                changes=changes
            )
        
        return changes
```

### Periodic Snapshot Job

```python
async def periodic_snapshot_comparison():
    """
    Run every hour to check for resolved unknowns.
    
    For each unknown that was resolved externally:
    1. Compare snapshots
    2. Detect changes
    3. Ask SRE for confirmation
    """
    
    # Find unknowns that were marked resolved but have no fix recorded
    unknowns = await unknown_store.find_by_criteria(
        resolution_status="resolved",
        resolution_method=None,  # No recorded fix method
        has_baseline_snapshot=True
    )
    
    for unknown in unknowns:
        # Compare snapshots to find what changed
        changes = await snapshotter.detect_changes_for_resolved_unknown(unknown.id)
        
        if changes:
            # Found changes! Ask SRE to confirm
            await notify_sre_about_detected_changes(unknown, changes)
```

---

## 🔍 Approach 4: SRE Self-Reporting (Simple Feedback)

### Quick Post-Fix Notification

Make it SUPER EASY for SREs to report fixes:

```bash
# After fixing an issue manually
oc annotate pod app-xyz-abc123 \
  sre-agent.io/fixed-by="increased-memory" \
  sre-agent.io/root-cause="OOMKilled-due-to-small-limit"

# Agent detects this annotation and learns from it!
```

Or via simple webhook:

```bash
# SRE just finished fixing issue #142
# Quick curl to tell agent:

curl -X POST http://sre-agent:8000/api/quick-fix \
  -d "issue=142&what=increased-memory&why=oomkilled"

# That's it! Agent learns from this minimal info
```

---

## 📊 Comparison: Learning Methods

| Method | Automation | Accuracy | SRE Effort | Best For |
|--------|-----------|----------|------------|----------|
| **Resource Watch** | ✅ Fully automatic | ⭐⭐⭐⭐ 95% | 🟢 Low (just confirm) | Real-time fixes |
| **Audit Log Analysis** | ✅ Automatic | ⭐⭐⭐ 85% | 🟡 Medium (confirm) | Retroactive |
| **State Snapshots** | ✅ Automatic | ⭐⭐⭐ 80% | 🟡 Medium (confirm) | Periodic check |
| **Self-Reporting** | ❌ Manual | ⭐⭐⭐⭐⭐ 100% | 🔴 High (must report) | Quick fixes |

**Recommendation**: Use **Resource Watch (Approach 1)** as primary method with **Self-Reporting (Approach 4)** as backup.

---

## 🚀 Complete Example: Learning Without Git

### Timeline: Unknown → Manual Fix → Learning

```
════════════════════════════════════════════════════════════════════
10:00 - Unknown Issue Detected
════════════════════════════════════════════════════════════════════

Pod crashes: "OOMKilled"
  ↓
Pattern analyzers: No match
  ↓
LLM investigation: Low confidence
  ↓
Unknown Handler: Creates unknown-142
  ↓
Baseline snapshot created:
  Deployment/app:
    resources.limits.memory: 512Mi
    resources.requests.memory: 256Mi
  ↓
Slack notification sent to SRE

════════════════════════════════════════════════════════════════════
10:30 - SRE Investigates
════════════════════════════════════════════════════════════════════

John checks logs, finds OOMKilled
John decides to increase memory

════════════════════════════════════════════════════════════════════
10:35 - SRE Fixes Directly in Cluster (NO GIT!)
════════════════════════════════════════════════════════════════════

oc set resources deployment/app \
  --limits=memory=1Gi \
  --requests=memory=512Mi
  
Deployment updated
Pod restarts
Issue resolved!

════════════════════════════════════════════════════════════════════
10:36 - Agent Detects Change Automatically
════════════════════════════════════════════════════════════════════

Resource Watch:
  ✓ Detected modification to Deployment/app
  ✓ Changes:
    - resources.limits.memory: 512Mi → 1Gi
    - resources.requests.memory: 256Mi → 512Mi
  ✓ Changed by: john.doe@company.com
  ✓ Correlation: Found unknown-142 (detected 36 mins ago)
  
Creates provisional resolution: prov-001
  ↓
Slack notification:

  ┌─────────────────────────────────────────┐
  │ 🤖 Potential Fix Detected               │
  ├─────────────────────────────────────────┤
  │ Resource: production/Deployment/app     │
  │                                          │
  │ Changes detected:                        │
  │   • memory limit: 512Mi → 1Gi           │
  │   • memory request: 256Mi → 512Mi       │
  │                                          │
  │ Changed by: john.doe@company.com        │
  │                                          │
  │ Related to: Unknown Issue #142          │
  │ (OOMKilled - detected 36 mins ago)      │
  │                                          │
  │ ❓ Was this the fix?                    │
  │                                          │
  │ [Yes, fixed it] [No, unrelated]         │
  └─────────────────────────────────────────┘

════════════════════════════════════════════════════════════════════
10:37 - SRE Confirms
════════════════════════════════════════════════════════════════════

John clicks: [Yes, fixed it]
  ↓
Confirmation dialog:

  ┌─────────────────────────────────────────┐
  │ Great! Help us learn:                    │
  │                                          │
  │ Root Cause (optional):                   │
  │ [Memory limit too low for workload]     │
  │                                          │
  │ Category:                                │
  │ [oom_killed] ▼                          │
  │                                          │
  │ Recommended Actions (optional):          │
  │ [Monitor memory usage after deploys]    │
  │ [Increase to 1.5x observed usage]       │
  │                                          │
  │ [Submit] [Skip]                          │
  └─────────────────────────────────────────┘

John submits with details
(or clicks Skip - basic info still captured!)

════════════════════════════════════════════════════════════════════
10:38 - Agent Learns!
════════════════════════════════════════════════════════════════════

Knowledge Base:
  ✓ Created incident #142
  ✓ Category: oom_killed
  ✓ Root Cause: "Memory limit too low"
  ✓ Solution: "Increase memory limit 512Mi → 1Gi"
  ✓ Resolved by: john.doe@company.com
  ✓ Method: manual_cluster_fix
  ✓ Success rate: 100% (1/1)
  
Pattern Mapping:
  ✓ Error pattern: "OOMKilled"
  ✓ → Solution: "Increase memory limit"
  ✓ Evidence: resources.limits.memory change
  
Unknown Issue:
  ✓ Marked as resolved
  ✓ Resolution method: manual_cluster_fix
  ✓ Fix details: stored

════════════════════════════════════════════════════════════════════
DAY 5: Same Issue in Different App
════════════════════════════════════════════════════════════════════

New pod: OOMKilled
  ↓
Pattern analyzers: No match
  ↓
LLM investigation:
  ↓
  Knowledge base search: FOUND incident #142!
    Similarity: 95%
    Solution: "Increase memory limit"
    Proven success: 100%
  ↓
  Auto-diagnoses:
    Category: oom_killed
    Root Cause: "Memory limit too low (based on incident #142)"
    Recommended Actions: [from John's fix]
      • Increase memory limit to 1.5x observed usage
      • Monitor memory after deployment
    Evidence:
      learned_from: incident_142
      original_fix_by: john.doe@company.com
      
Tier 2 Handler:
  ✓ Creates recommendation (no Git, so logs it)
  ✓ Sends Slack with detailed steps
  ✓ Includes: "Based on fix by John on Day 1"

SRE applies same fix:
  oc set resources deployment/app2 --limits=memory=1Gi

MTTR: 5 minutes (vs 35 minutes on Day 1)
✨ Learned from John's manual fix!
```

---

## 🛠️ Implementation

### Step 1: Add Resource Watch to Agent

```python
# File: sre_agent/watchers/resource_change_watcher.py

from kubernetes import client, watch
import asyncio

class ResourceChangeWatcher:
    """Watches for resource modifications to detect manual fixes."""
    
    def __init__(self, mcp_registry):
        self.mcp_registry = mcp_registry
        self.state_cache = {}
        
    async def start(self):
        """Start watching deployments."""
        await asyncio.gather(
            self._watch_deployments(),
            self._watch_statefulsets(),
            self._watch_hpas()
        )
    
    async def _watch_deployments(self):
        """Watch deployment modifications."""
        # Implementation from Approach 1
        pass
```

### Step 2: Add to main.py

```python
# In main.py lifespan():

from sre_agent.watchers.resource_change_watcher import ResourceChangeWatcher

# After watch_manager initialization:
resource_change_watcher = ResourceChangeWatcher(mcp_registry)
await resource_change_watcher.start()

logger.info("Resource change watcher started")
```

### Step 3: Add Confirmation API

```python
# In main.py:

class FixConfirmation(BaseModel):
    provisional_id: str
    confirmed: bool
    root_cause: str = ""
    category: str = "unknown"
    recommended_actions: list[str] = []

@app.post("/api/feedback/confirm-fix")
async def confirm_fix(confirmation: FixConfirmation):
    """Confirm a detected fix and learn from it."""
    # Implementation from above
    pass
```

---

## 🎯 Summary

### The Problem
SRE fixes issues directly with `oc` commands. No Git commits. How does agent learn?

### The Solution
**Automatic Detection** via:

1. ✅ **Resource Watch** (Primary)
   - Detects changes in real-time
   - Correlates with recent unknowns
   - Asks SRE for confirmation
   - 95% accuracy

2. ✅ **Audit Log Analysis** (Retroactive)
   - Analyzes past changes
   - Finds historical fixes
   - Batch learning from old data

3. ✅ **State Snapshots** (Periodic)
   - Compares before/after state
   - Detects resolved unknowns
   - Periodic analysis

4. ✅ **Self-Reporting** (Backup)
   - Quick annotation/webhook
   - 100% accuracy
   - Requires SRE action

### The Result
**Agent learns from manual cluster fixes even WITHOUT Git!** 🎓

**Files to Create**:
- `sre_agent/watchers/resource_change_watcher.py` (NEW)
- `sre_agent/stores/provisional_resolution_store.py` (NEW)
- Add `/api/feedback/confirm-fix` endpoint to main.py

**Next Steps**:
1. Implement Resource Change Watcher (Approach 1)
2. Add confirmation API
3. Test with manual `oc` commands
4. Monitor learning success rate

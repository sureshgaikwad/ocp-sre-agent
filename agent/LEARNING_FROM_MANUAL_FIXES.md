# How the Agent Learns from Manual Fixes

## 🎯 The Learning Problem

**Scenario**: SRE manually fixes an issue the agent doesn't recognize

**Questions**:
1. How does the agent know a manual fix happened?
2. How does it capture what the SRE did?
3. How does it apply this knowledge to future similar issues?
4. How does it avoid learning incorrect patterns?

**Answer**: 4-Stage Learning System

---

## 🔄 The Complete Learning Cycle

```
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 1: DETECTION - Agent Identifies Unknown Issue            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 2: MANUAL FIX - SRE Resolves Issue                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 3: CAPTURE - Agent Learns from Fix                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ STAGE 4: APPLICATION - Agent Auto-Diagnoses Next Time          │
└─────────────────────────────────────────────────────────────────┘
```

---

## STAGE 1: Detection - Agent Identifies Unknown

### What Happens
```python
# Day 1: New unknown issue occurs
Observation: Pod crash with error "connection timeout port 5432"

Pattern Analyzers: No match ❌
LLM Analyzer: Low confidence
Enhanced LLM Investigation: Partial success

Result: 
  Unknown Issue Detected
  ↓
  UnknownHandler stores:
    - fingerprint: "abc123def456"
    - error_patterns: ["connection timeout", "port 5432"]
    - occurrence_count: 1
    - logs: [full container logs]
    - events: [kubernetes events]
    - status: "unresolved"
  ↓
  Creates Tier 3 notification:
    - GitHub Issue #142
    - Slack notification
    - Kubernetes Event
```

### Database Record Created
```sql
INSERT INTO unknown_issues (
    unknown_id,
    fingerprint,
    observation_type,
    error_message,
    error_patterns,
    occurrence_count,
    resolution_status,
    first_seen,
    last_seen
) VALUES (
    'unknown-abc-123',
    'abc123def456',
    'pod_failure',
    'connection timeout port 5432',
    '["connection timeout", "port 5432"]',
    1,
    'unresolved',
    '2026-04-21T10:00:00Z',
    '2026-04-21T10:00:00Z'
);
```

---

## STAGE 2: Manual Fix - SRE Resolves Issue

### SRE Investigation Process

**Step 1: SRE receives notification**
```
GitHub Issue #142 or Slack notification:

🔍 Unknown Issue Investigation

Severity: 7.5/10
Occurrences: 1

Error: connection timeout port 5432

Container Logs:
  psycopg2.OperationalError: could not connect
  connection timeout; port 5432
  Retried 3 times, giving up

Kubernetes Events:
  Readiness probe failed
  Liveness probe failed
```

**Step 2: SRE investigates**
```bash
# SRE checks pod
oc logs pod/app-xyz-abc123 -n production

# Checks database connectivity
oc run debug --rm -it --image=postgres:15 -- \
  psql -h database -p 5432 -U admin -c "SELECT 1"

# Finds: Database connection pool exhausted
# Database logs show: "max_connections reached"

# Checks current app config
oc get deployment app -o yaml | grep -A5 env
  - name: DB_POOL_SIZE
    value: "10"  # Too low!
```

**Step 3: SRE fixes the issue**
```bash
# Increase connection pool size
oc set env deployment/app DB_POOL_SIZE=30

# Wait for rollout
oc rollout status deployment/app

# Verify fix
oc logs pod/app-xyz-new123 -n production
# No more connection timeout errors!
```

**Step 4: This is where learning starts!**

---

## STAGE 3: Capture - Agent Learns from Fix

### Option A: Automatic Capture (GitOps Detection)

If the fix was done via GitOps/Git commit:

```python
# Agent watches for commits to config repo
GitOpsHandler.detect_manual_fix():
  
  # Detects new commit
  commit = {
    "message": "Fix: Increase DB connection pool",
    "files_changed": ["manifests/production/app/deployment.yaml"],
    "diff": """
      - name: DB_POOL_SIZE
-       value: "10"
+       value: "30"
    """
  }
  
  # Searches for related unknown issues
  unknown_issues = find_unknowns_by_context(
    namespace="production",
    resource_name="app",
    time_window="last 24 hours"
  )
  
  # Found: unknown-abc-123 (connection timeout)
  
  # Auto-creates resolution record
  await create_resolution_from_commit(
    unknown_id="unknown-abc-123",
    commit=commit,
    auto_detected=True
  )
```

**What gets captured automatically**:
- ✅ What changed (deployment.yaml, DB_POOL_SIZE: 10 → 30)
- ✅ When it changed (commit timestamp)
- ✅ Who changed it (commit author)
- ❌ WHY it was changed (needs manual explanation)

### Option B: Manual Capture (Feedback API)

**SRE submits resolution explicitly**:

```bash
# SRE calls feedback API
curl -X POST http://sre-agent:8000/api/feedback/resolution \
  -H 'Content-Type: application/json' \
  -d '{
    "unknown_id": "unknown-abc-123",
    "resolution_method": "manual_fix",
    "root_cause": "Database connection pool size was too low (10 connections) for the workload. During peak traffic, all connections were in use, causing new connection attempts to timeout.",
    "category": "application_config_error",
    "recommended_tier": 2,
    "recommended_actions": [
      "Increase DB_POOL_SIZE from 10 to 30 (or 3x current value)",
      "Monitor connection pool usage with metrics",
      "Set alerts for connection pool >80% usage",
      "Review application connection handling for leaks"
    ],
    "fix_applied": {
      "type": "config_change",
      "resource": "deployment/app",
      "namespace": "production",
      "change": "DB_POOL_SIZE: 10 -> 30"
    },
    "resolved_by": "john.doe@company.com",
    "verification": "Monitored for 2 hours, no more timeouts"
  }'
```

**Response**:
```json
{
  "status": "success",
  "message": "Resolution captured! Agent will use this for future similar issues.",
  "actions_taken": [
    "Marked unknown_id=unknown-abc-123 as resolved",
    "Created incident record in knowledge base",
    "Linked error pattern 'connection timeout port 5432' to solution",
    "Future similar issues will reference this resolution"
  ],
  "learning_impact": {
    "similar_unknowns_found": 3,
    "will_auto_diagnose_next_time": true,
    "pattern_suggestion_created": true
  }
}
```

### What Happens Inside the Agent

```python
async def submit_resolution(feedback: ResolutionFeedback):
    """Process SRE's manual fix and learn from it."""
    
    # 1. Update unknown_issues table
    await unknown_store.mark_resolved(
        unknown_id=feedback.unknown_id,
        resolution_notes=feedback.root_cause,
        resolution_method="manual_fix",
        resolved_by=feedback.resolved_by
    )
    
    # 2. Create Incident Record in Knowledge Base
    incident_id = await knowledge_store.store_incident(
        observation=original_observation,  # Retrieved from DB
        diagnosis=Diagnosis(
            category=DiagnosisCategory[feedback.category],
            root_cause=feedback.root_cause,
            confidence=Confidence.HIGH,  # Human-validated = high confidence
            recommended_actions=feedback.recommended_actions,
            recommended_tier=feedback.recommended_tier,
            evidence={
                "manual_fix": True,
                "fix_details": feedback.fix_applied,
                "resolved_by": feedback.resolved_by
            }
        ),
        remediation=RemediationResult(
            status=RemediationStatus.SUCCESS,
            message=f"Manual fix: {feedback.fix_applied}",
            actions_taken=[feedback.fix_applied]
        )
    )
    
    # 3. Link Error Pattern to Solution
    await knowledge_store.create_pattern_mapping(
        error_patterns=["connection timeout", "port 5432"],
        diagnosis_category=feedback.category,
        solution_summary="Increase DB connection pool size",
        evidence_keywords=["database", "connection", "timeout"],
        success_rate=1.0  # First success
    )
    
    # 4. Check for Similar Unknowns (Batch Learning)
    similar_unknowns = await unknown_store.find_similar(
        fingerprint=original_fingerprint,
        error_patterns=["connection timeout", "port 5432"],
        threshold=0.8
    )
    
    if len(similar_unknowns) >= 3:
        # Create Pattern Suggestion for auto-promotion
        await pattern_discovery.create_suggestion(
            pattern_name="database_connection_pool_exhausted",
            error_patterns=["connection timeout.*port.*5432"],
            diagnosis_category="application_config_error",
            recommended_actions=feedback.recommended_actions,
            occurrence_count=len(similar_unknowns),
            resolution_success_rate=1.0
        )
        
        logger.info(
            "Pattern suggestion created - ready for review",
            pattern_name="database_connection_pool_exhausted",
            similar_issues=len(similar_unknowns)
        )
    
    return {"status": "success", "incident_id": incident_id}
```

---

## STAGE 4: Application - Auto-Diagnose Next Time

### Scenario: Same Issue Occurs Again (1 Week Later)

```
┌─────────────────────────────────────────────────────────────────┐
│ Day 8: Same Issue Occurs Again                                 │
└─────────────────────────────────────────────────────────────────┘

Observation: Pod crash with "connection timeout port 5432"
  ↓
Pattern Analyzers: No specific analyzer yet
  ↓
LLM Analyzer: Tries diagnosis
  ↓
Enhanced LLM Investigation:
  ↓
  Knowledge Base Lookup:
    - Searches for similar past incidents
    - Query: "connection timeout port 5432"
    - Similarity score: 95% match!
    ↓
  Found: Incident #142 (resolved by john.doe)
    - Category: application_config_error
    - Root Cause: "DB pool size too low"
    - Solution: "Increase DB_POOL_SIZE to 30"
    - Success Rate: 100% (1/1)
    - Confidence: HIGH (human-validated)
  ↓
  Creates Diagnosis FROM LEARNED KNOWLEDGE:
    Category: application_config_error (not UNKNOWN!)
    Confidence: HIGH
    Root Cause: "Database connection pool exhausted (based on incident #142)"
    Recommended Actions: [from john.doe's solution]
      1. Increase DB_POOL_SIZE from 10 to 30
      2. Monitor connection pool usage
      3. Set alerts for >80% usage
    Evidence: {
      "learned_from": "incident_142",
      "similar_issue": true,
      "resolution_proven": true,
      "resolved_by": "john.doe@company.com"
    }
```

**Result**: 
- ✅ NOT marked as unknown
- ✅ Auto-diagnosed using learned knowledge
- ✅ SRE gets solution immediately (from john.doe's fix)
- ✅ MTTR: 7 days → 2 minutes

---

## 🔍 How Similarity Detection Works

### Method 1: Fingerprint Matching (Exact)
```python
def _generate_fingerprint(observation):
    # Normalize error message
    normalized = observation.message.lower()
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}', '', normalized)  # Remove dates
    normalized = re.sub(r'-[a-z0-9]{5,10}', '-*', normalized)  # Remove pod suffixes
    normalized = re.sub(r'\b\d+\b', 'N', normalized)            # Numbers → N
    
    # Hash it
    fingerprint_str = f"{observation.type}|{observation.resource_kind}|{normalized[:100]}"
    return hashlib.md5(fingerprint_str.encode()).hexdigest()

# Example:
# "connection timeout to database:5432 in pod-abc123"
# becomes: "connection timeout to database:N in pod-*"
# fingerprint: "abc123def456"
```

### Method 2: Error Pattern Matching (Fuzzy)
```python
async def find_similar_incidents(observation):
    # Extract error patterns from observation
    current_patterns = extract_error_patterns(observation)
    # ["connection timeout", "port 5432", "database"]
    
    # Search knowledge base
    incidents = await knowledge_store.search_by_patterns(
        patterns=current_patterns,
        threshold=0.7  # 70% pattern overlap required
    )
    
    # Returns incidents with similar patterns
    # Example match:
    # Incident #142: ["connection timeout", "port 5432", "psycopg2"]
    # Overlap: 2/3 patterns = 66% → Below threshold
    # Incident #143: ["connection timeout", "port 5432", "database", "pool"]
    # Overlap: 3/3 patterns = 100% → Match!
```

### Method 3: Semantic Similarity (Advanced - Optional)
```python
async def find_similar_by_embeddings(observation):
    """
    Use embeddings for semantic similarity.
    
    Example:
    - "connection timeout to database"
    - "database connection timed out"
    - "db connection refused"
    
    These are semantically similar even with different words!
    """
    # Generate embedding for observation
    embedding = await generate_embedding(observation.message)
    
    # Search for similar embeddings in knowledge base
    similar = await knowledge_store.vector_search(
        embedding=embedding,
        top_k=5,
        threshold=0.85
    )
    
    return similar
```

---

## 📊 Learning Confidence Levels

### Confidence Scoring System

```python
def calculate_learning_confidence(incident):
    """
    Calculate confidence in learned knowledge.
    
    Factors:
    1. Resolution success rate (1.0 = 100% success)
    2. Number of times pattern seen
    3. Time since resolution
    4. Similarity score
    """
    
    confidence = 0.0
    
    # Base confidence from success rate
    confidence += incident.success_rate * 0.4  # 40% weight
    
    # Confidence from recurrence (proven pattern)
    if incident.occurrence_count >= 5:
        confidence += 0.3
    elif incident.occurrence_count >= 3:
        confidence += 0.2
    elif incident.occurrence_count >= 1:
        confidence += 0.1
    
    # Confidence from resolution age (fresh = better)
    days_ago = (datetime.now() - incident.resolved_at).days
    if days_ago < 7:
        confidence += 0.2
    elif days_ago < 30:
        confidence += 0.1
    
    # Confidence from similarity
    confidence += incident.similarity_score * 0.1  # 10% weight
    
    return min(confidence, 1.0)  # Cap at 1.0
```

**Examples**:
```
Incident A:
  - Success rate: 100% (1/1)
  - Occurrence count: 1
  - Days ago: 2
  - Similarity: 95%
  → Confidence: 0.4 + 0.1 + 0.2 + 0.095 = 0.795 (MEDIUM-HIGH)

Incident B:
  - Success rate: 100% (5/5)
  - Occurrence count: 5
  - Days ago: 10
  - Similarity: 100%
  → Confidence: 0.4 + 0.3 + 0.1 + 0.1 = 0.9 (HIGH)

Incident C:
  - Success rate: 50% (1/2)
  - Occurrence count: 2
  - Days ago: 60
  - Similarity: 80%
  → Confidence: 0.2 + 0.1 + 0.0 + 0.08 = 0.38 (LOW)
```

---

## 🚀 Progressive Pattern Promotion

### When Patterns Become Analyzers

**Threshold for Auto-Promotion**:
```python
def can_auto_promote(pattern_suggestion):
    """
    Determine if pattern is ready for auto-promotion.
    
    Criteria:
    1. Occurrence count >= 5 (proven recurring)
    2. Resolution success rate >= 90% (proven solution)
    3. Human validation = 100% (all reviewed as correct)
    4. No conflicts with existing analyzers
    """
    
    return (
        pattern_suggestion.occurrence_count >= 5 and
        pattern_suggestion.success_rate >= 0.9 and
        pattern_suggestion.human_validation_rate >= 1.0 and
        not pattern_suggestion.has_conflicts
    )
```

**Auto-Promotion Process**:
```python
async def auto_promote_pattern(pattern_suggestion):
    """
    Promote validated pattern to production analyzer.
    
    Steps:
    1. Generate analyzer code from pattern
    2. Create GitOps PR
    3. Run tests
    4. Deploy to production
    """
    
    # 1. Generate analyzer code
    analyzer_code = generate_analyzer_code(
        pattern_name=pattern_suggestion.pattern_name,
        error_patterns=pattern_suggestion.error_patterns,
        diagnosis_category=pattern_suggestion.category,
        recommended_actions=pattern_suggestion.actions
    )
    
    # 2. Create PR
    pr = await create_gitops_pr(
        title=f"Auto-promote pattern: {pattern_suggestion.pattern_name}",
        files={
            f"sre_agent/analyzers/{pattern_suggestion.pattern_name}_analyzer.py": analyzer_code,
            "sre_agent/orchestrator/workflow_engine.py": register_analyzer_code
        },
        description=f"""
        Auto-promoted pattern based on proven resolution:
        
        - Occurrences: {pattern_suggestion.occurrence_count}
        - Success Rate: {pattern_suggestion.success_rate * 100}%
        - Resolved by: {pattern_suggestion.resolved_by}
        - Validation: 100% human-validated
        """
    )
    
    # 3. Tests run automatically in CI/CD
    
    # 4. Notify SRE for final approval
    await notify_sre(
        message=f"Pattern '{pattern_suggestion.pattern_name}' ready for promotion",
        pr_url=pr.url
    )
```

**Example Generated Analyzer**:
```python
class DatabaseConnectionPoolAnalyzer(BaseAnalyzer):
    """
    Auto-generated analyzer for database connection pool issues.
    
    Based on incident #142 resolved by john.doe@company.com
    Proven success rate: 100% (5/5 resolutions)
    """
    
    ERROR_PATTERNS = [
        r"connection\s+timeout.*port\s*5432",
        r"psycopg2\.OperationalError.*timeout",
        r"database.*connection.*pool.*exhausted"
    ]
    
    def can_analyze(self, observation):
        # Check for pattern match
        for pattern in self.ERROR_PATTERNS:
            if re.search(pattern, observation.message, re.IGNORECASE):
                return True
        return False
    
    async def analyze(self, observation):
        # Diagnosis based on learned knowledge
        return Diagnosis(
            category=DiagnosisCategory.APPLICATION_CONFIG_ERROR,
            root_cause="Database connection pool size too low for workload",
            confidence=Confidence.HIGH,
            recommended_tier=2,  # Config change via GitOps
            recommended_actions=[
                "Increase DB_POOL_SIZE to 30 (or 3x current value)",
                "Monitor connection pool usage with metrics",
                "Set alerts for connection pool >80% usage"
            ],
            evidence={
                "learned_pattern": True,
                "original_incident": "incident_142",
                "proven_success_rate": 1.0
            }
        )
```

---

## 🎯 Complete Example: End-to-End Learning

### Timeline: Unknown → Known → Automated

```
════════════════════════════════════════════════════════════════════
DAY 1: Unknown Issue First Occurs
════════════════════════════════════════════════════════════════════

10:00 - Pod crashes: "connection timeout port 5432"
10:01 - Pattern analyzers: No match
10:01 - LLM analyzer: Low confidence
10:02 - Unknown Handler: Stores as unknown-001
10:03 - Creates GitHub Issue #142
10:05 - Slack notification sent to #sre-alerts

════════════════════════════════════════════════════════════════════
DAY 1: SRE Investigates & Fixes
════════════════════════════════════════════════════════════════════

11:00 - John investigates logs
11:15 - Finds: DB pool exhausted (max 10 connections)
11:30 - Applies fix: oc set env deployment/app DB_POOL_SIZE=30
12:00 - Verifies fix works
12:15 - Submits resolution via API:
        POST /api/feedback/resolution
        {
          "unknown_id": "unknown-001",
          "root_cause": "DB pool too small",
          "category": "application_config_error",
          "recommended_actions": ["Increase DB_POOL_SIZE to 30"],
          "resolved_by": "john.doe@company.com"
        }

12:16 - Agent learns:
        ✓ Marks unknown-001 as resolved
        ✓ Creates incident #142 in knowledge base
        ✓ Links pattern "connection timeout port 5432" to solution
        ✓ Stores success rate: 100% (1/1)

════════════════════════════════════════════════════════════════════
DAY 3: Same Issue in Different App
════════════════════════════════════════════════════════════════════

14:00 - Different pod crashes: "connection timeout port 5432"
14:01 - Pattern analyzers: No match
14:01 - LLM analyzer: Searches knowledge base
14:02 - Finds incident #142 (similarity: 95%)
14:02 - Creates diagnosis FROM LEARNED KNOWLEDGE:
        Category: application_config_error
        Root Cause: "DB pool exhausted (based on incident #142)"
        Actions: [from john.doe's solution]
        Confidence: HIGH

14:03 - Tier 2 Handler: Creates GitOps PR
        Change: DB_POOL_SIZE: 10 → 30
        Reference: Based on incident #142

14:15 - SRE reviews PR, approves
14:20 - Fix deployed automatically

MTTR: 20 minutes (vs 2 hours for DAY 1)
Status: Now known issue (not unknown!)

════════════════════════════════════════════════════════════════════
DAY 5: Same Issue Again (3rd occurrence)
════════════════════════════════════════════════════════════════════

09:00 - Another pod crashes: same error
09:01 - Knowledge base: Found incident #142
09:01 - Success rate updated: 100% (2/2)
09:02 - Auto-diagnosed, GitOps PR created
09:10 - Merged and deployed

MTTR: 10 minutes

════════════════════════════════════════════════════════════════════
DAY 10: Same Issue (5th occurrence)
════════════════════════════════════════════════════════════════════

Pattern Discovery Engine (weekly job):
  ✓ Found pattern "connection timeout port 5432"
  ✓ Occurrence count: 5
  ✓ Success rate: 100% (5/5)
  ✓ Creates pattern suggestion:
    Name: database_connection_pool_exhausted
    Status: Ready for auto-promotion

════════════════════════════════════════════════════════════════════
DAY 14: Pattern Auto-Promoted
════════════════════════════════════════════════════════════════════

Learning Engine:
  ✓ Pattern meets criteria (5+ occurrences, 100% success)
  ✓ Generates DatabaseConnectionPoolAnalyzer
  ✓ Creates GitOps PR for new analyzer
  ✓ Tests pass
  ✓ SRE approves
  ✓ Deployed to production

════════════════════════════════════════════════════════════════════
DAY 21: Same Issue (Now Fully Automated)
════════════════════════════════════════════════════════════════════

10:00 - Pod crashes: "connection timeout port 5432"
10:01 - DatabaseConnectionPoolAnalyzer (NEW): MATCH!
10:01 - Auto-diagnosed: application_config_error
10:02 - Tier 2: GitOps PR created automatically
10:05 - Tests pass
10:10 - Auto-merged (if policy allows)
10:15 - Deployed

MTTR: 15 minutes (fully automated!)
Unknown → Known → Automated ✨
```

---

## 📈 Learning Metrics

Track learning effectiveness:

```sql
-- Unknown reduction over time
SELECT 
    DATE(first_seen) as date,
    COUNT(*) as new_unknowns,
    SUM(CASE WHEN resolution_status='resolved' THEN 1 ELSE 0 END) as resolved
FROM unknown_issues
GROUP BY DATE(first_seen)
ORDER BY date;

-- Pattern promotion pipeline
SELECT 
    pattern_name,
    occurrence_count,
    success_rate,
    human_validation_rate,
    auto_promote_ready
FROM pattern_suggestions
ORDER BY occurrence_count DESC;

-- Learning impact
SELECT 
    'Total unknowns' as metric,
    COUNT(*) as value
FROM unknown_issues
UNION ALL
SELECT 
    'Resolved by humans',
    COUNT(*)
FROM unknown_issues
WHERE resolution_status='resolved'
UNION ALL
SELECT 
    'Auto-promoted patterns',
    COUNT(*)
FROM pattern_suggestions
WHERE auto_promoted=true;
```

---

## 🎯 Summary

**How Learning Works**:

1. **Detection**: Unknown Handler catches and stores unknown issues
2. **Manual Fix**: SRE investigates and resolves
3. **Capture**: SRE submits resolution via API (or auto-detected from GitOps)
4. **Application**: Next time same issue → Auto-diagnosed from knowledge base
5. **Promotion**: After 5+ proven successes → Auto-promoted to analyzer

**Key Insight**: Every unknown issue is a **learning opportunity**!

**Result**: Agent continuously gets smarter from human expertise! 🎓

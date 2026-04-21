# Unknown Issue & Anomaly Handling Architecture

## Problem Statement

When the SRE Agent encounters an issue it doesn't recognize:
1. **Current Behavior**: Falls back to LLMAnalyzer → Returns UNKNOWN category → Creates Tier 3 notification
2. **Lost Opportunities**: 
   - No tracking of unknown issues
   - No pattern discovery from unknowns
   - No learning from human resolutions
   - No improvement over time

## Comprehensive Solution: 6-Layer System

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ANOMALY HANDLING PIPELINE                        │
└─────────────────────────────────────────────────────────────────────┘

Observation → Layer 1: Pattern Analyzers (Specific)
                 ↓ (no match)
              Layer 2: LLM Analyzer (AI Fallback)
                 ↓ (fails/low confidence)
              Layer 3: Unknown Issue Handler (Track & Investigate)
                 ↓
              Layer 4: Pattern Discovery (Learn New Patterns)
                 ↓
              Layer 5: Human Feedback Loop (Capture Resolutions)
                 ↓
              Layer 6: Progressive Learning (Auto-improve)
```

---

## Layer 1: Enhanced Analyzer Chain (EXISTING)

**Status**: ✅ Already Implemented

- Specific pattern analyzers: CrashLoopAnalyzer, ImagePullAnalyzer, etc.
- Registered in order of specificity
- LLMAnalyzer registered LAST as fallback

---

## Layer 2: LLM Fallback (EXISTING)

**Status**: ✅ Already Implemented

- LLMAnalyzer with `can_analyze() → True`
- Gathers context (logs, events)
- Attempts AI-powered diagnosis
- Returns DiagnosisCategory.UNKNOWN if uncertain

**Gap**: If LLM fails, returns None → observation is lost

---

## Layer 3: Unknown Issue Handler (NEW)

**Status**: 🔴 TO BE IMPLEMENTED

### Component: `UnknownIssueHandler` (Tier 3 Analyzer)

**Purpose**: Catch ALL observations that no analyzer can diagnose

**Implementation**:
```python
class UnknownIssueHandler(BaseAnalyzer):
    """
    Ultimate fallback analyzer - catches everything.
    
    Features:
    - Never returns None (always creates a diagnosis)
    - Stores unknown issues for pattern discovery
    - Creates enriched investigation templates
    - Tracks recurrence frequency
    """
    
    def can_analyze(self, observation: Observation) -> bool:
        return True  # Catch everything
    
    async def analyze(self, observation: Observation) -> Diagnosis:
        # ALWAYS create a diagnosis (never None)
        # Store in UnknownIssueStore
        # Generate investigation template
        # Return UNKNOWN diagnosis with Tier 3
```

### Component: `UnknownIssueStore` (Database)

**Schema**:
```sql
CREATE TABLE unknown_issues (
    unknown_id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    observation_type TEXT NOT NULL,
    observation_data TEXT NOT NULL,  -- Full observation JSON
    
    -- Context
    namespace TEXT,
    resource_kind TEXT,
    resource_name TEXT,
    error_message TEXT,
    logs TEXT,                       -- Container logs
    events TEXT,                     -- Kubernetes events
    raw_data TEXT,                   -- Full raw data
    
    -- Pattern Discovery
    error_patterns TEXT,             -- Extracted error patterns
    fingerprint TEXT NOT NULL,       -- Hash for deduplication
    
    -- Tracking
    occurrence_count INTEGER DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    
    -- Resolution Tracking
    resolution_status TEXT DEFAULT 'unresolved',  -- unresolved, investigating, resolved
    resolution_method TEXT,          -- manual_fix, automated, ignored
    resolution_notes TEXT,           -- Human-provided notes
    resolved_by TEXT,                -- Username/system
    resolved_at TEXT,
    
    -- Severity Scoring
    severity_score REAL,             -- Auto-calculated severity
    business_impact TEXT,            -- User-provided impact
    
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_unknown_fingerprint ON unknown_issues(fingerprint);
CREATE INDEX idx_unknown_status ON unknown_issues(resolution_status);
CREATE INDEX idx_unknown_recurrence ON unknown_issues(occurrence_count DESC);
```

**Features**:
- Deduplicate by fingerprint
- Track recurrence (how many times seen)
- Store full context for investigation
- Track resolution lifecycle

---

## Layer 4: Pattern Discovery Engine (NEW)

**Status**: 🔴 TO BE IMPLEMENTED

### Component: `PatternDiscoveryEngine`

**Purpose**: Automatically mine new error patterns from unknown issues

**Algorithm**:
```python
class PatternDiscoveryEngine:
    """
    Discovers common patterns in unknown issues.
    
    Techniques:
    1. Frequency Analysis: Find recurring error messages
    2. Text Mining: Extract common keywords/phrases
    3. Regex Generation: Auto-generate error pattern regexes
    4. Clustering: Group similar unknowns
    """
    
    async def discover_patterns(self, min_occurrences: int = 3):
        """
        Find unknown issues that have occurred >= min_occurrences times.
        
        Steps:
        1. Query unknown_issues with occurrence_count >= 3
        2. Extract error messages and logs
        3. Find common patterns using:
           - TF-IDF for keyword extraction
           - N-gram analysis for phrase patterns
           - Regex pattern mining
        4. Generate suggested analyzer rules
        5. Store in pattern_suggestions table
        """
```

**Output**: Pattern Suggestions Table
```sql
CREATE TABLE pattern_suggestions (
    suggestion_id TEXT PRIMARY KEY,
    pattern_type TEXT NOT NULL,      -- error_message, log_pattern, event_pattern
    regex_pattern TEXT NOT NULL,     -- Generated regex
    example_unknowns TEXT,           -- List of unknown_ids this matches
    occurrence_count INTEGER,        -- How many unknowns match
    confidence_score REAL,           -- Pattern quality score
    
    -- Classification
    suggested_category TEXT,         -- Suggested DiagnosisCategory
    suggested_tier INTEGER,          -- Suggested tier (1/2/3)
    suggested_actions TEXT,          -- JSON list of actions
    
    -- Review Status
    review_status TEXT DEFAULT 'pending',  -- pending, approved, rejected
    reviewed_by TEXT,
    reviewed_at TEXT,
    
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

**Scheduled Job**: Run weekly to discover new patterns

---

## Layer 5: Human Feedback Loop (NEW)

**Status**: 🔴 TO BE IMPLEMENTED

### Component: `HumanFeedbackAPI` (REST Endpoints)

**Purpose**: Capture human resolutions and feed back into knowledge base

**API Endpoints**:

```python
@app.post("/api/feedback/resolution")
async def submit_resolution(request: ResolutionFeedback):
    """
    SRE manually resolved an issue - capture the resolution.
    
    Request:
    {
        "unknown_id": "uuid-of-unknown-issue",
        "resolution_method": "manual_fix",
        "resolution_notes": "Increased memory limit from 512Mi to 1Gi",
        "root_cause": "Application memory leak in batch processing",
        "category": "oom_killed",  # Reclassify unknown
        "recommended_actions": [
            "Investigate memory leak in batch processor",
            "Increase memory limit to 1Gi"
        ],
        "resolved_by": "john.doe@company.com"
    }
    
    Actions:
    1. Update unknown_issue record (mark as resolved)
    2. Create IncidentRecord in knowledge store
    3. If pattern is common (occurrence_count > threshold):
       - Suggest new analyzer rule
       - Add to pattern_suggestions
    4. Send to PatternDiscoveryEngine for learning
    """

@app.post("/api/feedback/false-positive")
async def mark_false_positive(request: FalsePositiveFeedback):
    """
    Mark an unknown issue as false positive / noise.
    
    Request:
    {
        "unknown_id": "uuid",
        "reason": "This is normal behavior during deployment"
    }
    
    Actions:
    1. Mark as resolved with resolution_method='ignored'
    2. Add fingerprint to ignore list
    3. Future occurrences of same fingerprint are auto-ignored
    """

@app.get("/api/unknowns/dashboard")
async def get_unknowns_dashboard():
    """
    Dashboard for SRE to review unknown issues.
    
    Returns:
    {
        "summary": {
            "total_unknowns": 42,
            "unresolved": 15,
            "resolved_this_week": 5,
            "top_recurring": [...],  # Most frequent unknowns
            "pattern_suggestions": 3
        },
        "top_unknowns": [
            {
                "unknown_id": "uuid",
                "fingerprint": "hash",
                "occurrence_count": 12,
                "last_seen": "2026-04-21T10:00:00Z",
                "error_message": "...",
                "severity_score": 7.5,
                "investigation_url": "/api/unknowns/uuid"
            }
        ],
        "pattern_suggestions": [...]
    }
    """
```

### Component: Investigation Template Generator

**Purpose**: Create rich investigation templates for unknown issues

**Template Format** (sent to Gitea/GitHub issue):
```markdown
# Unknown Issue Investigation

## 🔍 Detection
- **First Seen**: 2026-04-15 10:30:00 UTC
- **Last Seen**: 2026-04-21 14:20:00 UTC
- **Occurrences**: 12 times
- **Severity Score**: 7.5/10 (auto-calculated based on frequency + severity)

## 📊 Resource Information
- **Namespace**: production
- **Resource**: Pod/my-app-xyz
- **Observation Type**: pod_failure

## 🔴 Error Information
```
Error message: <extracted error>
```

## 📝 Container Logs (Last 50 lines)
```
<logs>
```

## 📢 Kubernetes Events
```
<events>
```

## 🔬 Extracted Patterns
Auto-detected patterns:
- Pattern 1: `connection timeout.*port 5432`
- Pattern 2: `database.*unavailable`

**Possible Category**: Database connection issue (confidence: 60%)

## 💡 Similar Past Incidents
- Incident #42: OOMKilled in same namespace (similarity: 45%)
- Incident #87: Network timeout (similarity: 30%)

## ✅ Resolution Checklist

Please investigate and provide:
- [ ] Root cause analysis
- [ ] Fix applied (if any)
- [ ] Recommended category (oom_killed, application_error, etc.)
- [ ] Recommended tier (1=auto, 2=gitops, 3=manual)
- [ ] Recommended actions for future occurrences

**Submit Resolution**: `POST /api/feedback/resolution`

**Mark as False Positive**: `POST /api/feedback/false-positive`
```

---

## Layer 6: Progressive Learning Engine (NEW)

**Status**: 🔴 TO BE IMPLEMENTED

### Component: `LearningEngine`

**Purpose**: Automatically improve agent over time

**Features**:

1. **Auto-Promote Patterns** (Weekly Job)
   ```python
   async def auto_promote_patterns():
       """
       Promote validated patterns to production analyzers.
       
       Criteria for auto-promotion:
       - Pattern occurs >= 5 times
       - 100% human validation (all reviewed as correct)
       - No conflicts with existing patterns
       
       Actions:
       1. Generate Python code for new analyzer method
       2. Add to existing analyzer (e.g., CrashLoopAnalyzer)
       3. Deploy via GitOps PR
       4. Monitor effectiveness
       """
   ```

2. **Confidence Adjustment**
   ```python
   async def adjust_confidence_scores():
       """
       Adjust analyzer confidence based on outcomes.
       
       If an analyzer consistently produces wrong diagnoses:
       - Lower its confidence score
       - Increase review threshold
       
       If an analyzer is always correct:
       - Increase confidence
       - Enable auto-remediation
       """
   ```

3. **Knowledge Base Enrichment**
   ```python
   async def enrich_knowledge_base():
       """
       Backfill knowledge base with resolved unknowns.
       
       When unknown is resolved by human:
       1. Create IncidentRecord
       2. Add to knowledge store
       3. Future similar issues use this knowledge
       """
   ```

---

## Implementation Phases

### Phase 1: Foundation (Week 1-2)
- [ ] Implement `UnknownIssueHandler` analyzer
- [ ] Create `UnknownIssueStore` database schema
- [ ] Register UnknownIssueHandler as LAST analyzer
- [ ] Test: Verify all observations are diagnosed (never None)

### Phase 2: Tracking & Visibility (Week 3)
- [ ] Implement Unknown Issues Dashboard API
- [ ] Create investigation template generator
- [ ] Add recurrence tracking (deduplication)
- [ ] Enhanced Tier 3 notifications with investigation links

### Phase 3: Pattern Discovery (Week 4)
- [ ] Implement `PatternDiscoveryEngine`
- [ ] Pattern suggestion database schema
- [ ] Weekly discovery job
- [ ] Pattern review UI/API

### Phase 4: Human Feedback Loop (Week 5-6)
- [ ] Implement feedback API endpoints
- [ ] Resolution submission workflow
- [ ] False positive marking
- [ ] Integration with knowledge store

### Phase 5: Progressive Learning (Week 7-8)
- [ ] Auto-promotion system
- [ ] Confidence adjustment algorithm
- [ ] Knowledge base enrichment
- [ ] Analytics and reporting

### Phase 6: Advanced Features (Week 9-12)
- [ ] Anomaly detection (statistical)
- [ ] Behavioral baseline learning
- [ ] Predictive issue detection
- [ ] Auto-remediation for learned patterns

---

## Success Metrics

1. **Coverage**: % of observations that get diagnosed (target: 100%)
2. **Unknown Reduction**: % decrease in unknown issues over time (target: -20% per month)
3. **Pattern Discovery**: # of new patterns discovered and validated (target: 2-3/month)
4. **MTTR for Unknowns**: Time from first occurrence to resolution (target: < 7 days)
5. **Human Feedback Rate**: % of unknowns that get resolved by humans (target: > 50%)
6. **Auto-Promotion Rate**: % of discovered patterns that auto-promote (target: > 30%)

---

## Example Flow: Unknown Issue Lifecycle

```
Day 1: New unknown issue occurs
  ↓
Agent: Pattern analyzers can't match
  ↓
Agent: LLMAnalyzer returns low confidence
  ↓
Agent: UnknownIssueHandler catches it
  ↓
Agent: Stores in unknown_issues (occurrence_count = 1)
  ↓
Agent: Creates enriched Tier 3 investigation issue

Day 2-7: Issue occurs 5 more times
  ↓
Agent: Deduplicates by fingerprint
  ↓
Agent: occurrence_count = 6
  ↓
Agent: Severity score increases (high recurrence)

Day 7: SRE investigates via Dashboard
  ↓
SRE: Identifies root cause (database connection timeout)
  ↓
SRE: Submits resolution via API
  ↓
Agent: Marks as resolved
  ↓
Agent: Creates IncidentRecord in knowledge store

Day 14: PatternDiscoveryEngine runs (weekly)
  ↓
Engine: Finds pattern: "connection timeout.*port 5432" (6 occurrences)
  ↓
Engine: Generates pattern suggestion
  ↓
Engine: Suggests new rule for DatabaseAnalyzer

Day 21: SRE reviews pattern suggestion
  ↓
SRE: Approves pattern
  ↓
LearningEngine: Auto-promotes to DatabaseAnalyzer
  ↓
Agent: Deploys new analyzer via GitOps

Day 30: Same issue occurs again
  ↓
Agent: DatabaseAnalyzer (NEW) matches pattern
  ↓
Agent: Diagnosis: database_connection_timeout (HIGH confidence)
  ↓
Agent: No longer unknown!
```

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        Observation Flow                          │
└──────────────────────────────────────────────────────────────────┘
                              ↓
               ┌──────────────────────────┐
               │  Pattern Analyzers       │
               │  (Specific)              │
               └──────────────────────────┘
                              ↓ (no match)
               ┌──────────────────────────┐
               │  LLM Analyzer            │
               │  (AI Fallback)           │
               └──────────────────────────┘
                              ↓ (fails)
               ┌──────────────────────────┐
               │  Unknown Issue Handler   │──────────────┐
               │  (Ultimate Fallback)     │              │
               └──────────────────────────┘              │
                              │                          │
                              ↓                          ↓
               ┌──────────────────────────┐  ┌──────────────────────┐
               │  Unknown Issue Store     │  │  Investigation       │
               │  (SQLite Database)       │  │  Template Generator  │
               └──────────────────────────┘  └──────────────────────┘
                              │                          │
                              ↓                          ↓
               ┌──────────────────────────┐  ┌──────────────────────┐
               │  Pattern Discovery       │  │  Tier 3 Notification │
               │  Engine (Weekly)         │  │  (GitHub Issue)      │
               └──────────────────────────┘  └──────────────────────┘
                              │
                              ↓
               ┌──────────────────────────┐
               │  Pattern Suggestions     │
               │  (For Human Review)      │
               └──────────────────────────┘
                              ↓
               ┌──────────────────────────┐
               │  Human Feedback API      │
               │  (/api/feedback/...)     │
               └──────────────────────────┘
                              ↓
               ┌──────────────────────────┐
               │  Learning Engine         │
               │  (Auto-Promotion)        │
               └──────────────────────────┘
                              ↓
               ┌──────────────────────────┐
               │  Updated Analyzers       │
               │  (Via GitOps PR)         │
               └──────────────────────────┘
```

---

## Security Considerations

1. **Secret Scrubbing**: All unknown issues must be scrubbed before storage
2. **Access Control**: Dashboard and feedback APIs require authentication
3. **PII Protection**: Logs and events may contain sensitive data
4. **Audit Trail**: All human feedback and pattern promotions are audited
5. **Rate Limiting**: Prevent spam from unknown issue creation

---

## Alternative Approaches Considered

### Approach 1: Fully Manual Review
**Pros**: Simple, human-controlled
**Cons**: Doesn't scale, no auto-learning
**Verdict**: ❌ Rejected

### Approach 2: Pure ML Pattern Discovery
**Pros**: Fully automated
**Cons**: Requires large dataset, hallucination risk
**Verdict**: ❌ Too risky for production

### Approach 3: Hybrid (Chosen)
**Pros**: Human-in-loop safety, progressive automation
**Cons**: More complex to build
**Verdict**: ✅ Selected

---

## Related Systems

- **Incident Store**: Stores successful resolutions
- **Knowledge Retriever**: Searches past incidents
- **Alert Correlator**: Groups related alerts
- **Event Deduplicator**: Prevents duplicate alerts

---

## Future Enhancements

1. **Anomaly Detection** (Statistical)
   - Detect resource usage anomalies (CPU/memory spikes)
   - Baseline normal behavior per application
   - Alert on statistical deviations

2. **Behavioral Learning**
   - Learn normal vs abnormal restart patterns
   - Detect unusual deployment patterns
   - Time-series analysis

3. **Predictive Alerting**
   - Predict issues before they occur
   - Memory leak trend detection
   - Capacity forecasting

4. **Multi-Cluster Learning**
   - Share patterns across clusters
   - Federated pattern discovery
   - Cross-cluster correlation

5. **Integration with AIOps**
   - Integration with Prometheus/Grafana
   - Integration with ServiceNow
   - Integration with PagerDuty

---

## Conclusion

This 6-layer architecture ensures:
- ✅ **No observation is lost** - Unknown Issue Handler catches everything
- ✅ **Continuous learning** - Pattern discovery mines new rules
- ✅ **Human expertise captured** - Feedback loop stores resolutions
- ✅ **Progressive improvement** - Agent gets smarter over time
- ✅ **Full visibility** - Dashboard shows what agent doesn't know
- ✅ **Safety** - Human-in-loop approval for auto-promotions

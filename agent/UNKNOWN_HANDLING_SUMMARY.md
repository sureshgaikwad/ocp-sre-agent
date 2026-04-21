# Unknown Issue Handling - Architecture Summary

## 🎯 Problem We're Solving

**Current Risk**: When the agent encounters an unknown issue type:
- ❌ No tracking → issue is lost
- ❌ No learning → agent stays dumb
- ❌ No improvement → same unknowns recur forever

**Solution**: 6-Layer Anomaly Handling System

---

## 📊 Before vs After

### BEFORE (Current State)

```
Observation
  ↓
Pattern Analyzers → [Match ✓] → Diagnosis
  ↓ [No Match]
LLM Analyzer → [Success ✓] → Diagnosis
  ↓ [Fails or Low Confidence]
Returns None → ❌ OBSERVATION LOST
```

**Problems**:
- Observations can return no diagnosis
- Unknown issues are not tracked
- No learning mechanism
- Agent never gets smarter

### AFTER (With Unknown Handler)

```
Observation
  ↓
Pattern Analyzers → [Match ✓] → Diagnosis
  ↓ [No Match]
LLM Analyzer → [Success ✓] → Diagnosis
  ↓ [Fails or Low Confidence]
Unknown Issue Handler → ✅ ALWAYS SUCCEEDS
  ↓
UNKNOWN Diagnosis (Tier 3)
  ↓
Stored in UnknownIssueStore
  ↓
Pattern Discovery (Weekly)
  ↓
Human Feedback Loop
  ↓
Learning Engine → New Analyzer Rules
  ↓
Agent Gets Smarter ✨
```

**Benefits**:
- ✅ 100% observation coverage
- ✅ All unknowns tracked
- ✅ Pattern discovery
- ✅ Progressive learning
- ✅ Agent improves over time

---

## 🏗️ Complete Architecture (All 6 Layers)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         OBSERVATION FLOW                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 1: Pattern Analyzers (Specific Rules)                        │
│  - CrashLoopAnalyzer                                                │
│  - ImagePullAnalyzer                                                │
│  - AutoscalingAnalyzer                                              │
│  - ... 7 other specific analyzers                                  │
└─────────────────────────────────────────────────────────────────────┘
                              │ [No Match]
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 2: LLM Analyzer (AI Fallback)                                │
│  - Uses LiteLLM for AI-powered diagnosis                           │
│  - Gathers context (logs, events)                                  │
│  - Returns diagnosis or None if uncertain                          │
└─────────────────────────────────────────────────────────────────────┘
                              │ [Fails / Low Confidence]
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 3: Unknown Issue Handler (Ultimate Fallback) ⭐ NEW          │
│  - NEVER returns None (always creates diagnosis)                   │
│  - Stores in UnknownIssueStore database                            │
│  - Generates investigation template                                │
│  - Returns UNKNOWN diagnosis (Tier 3)                              │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ UnknownIssueStore (SQLite Database)                                │
│                                                                     │
│  Table: unknown_issues                                              │
│  ├─ fingerprint (for deduplication)                                │
│  ├─ occurrence_count (tracking recurrence)                         │
│  ├─ severity_score (auto-calculated)                               │
│  ├─ error_patterns (extracted patterns)                            │
│  ├─ logs & events (full context)                                   │
│  └─ resolution_status (unresolved/resolved)                        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Tier 3 Handler: GitHub/Gitea Issue                                 │
│                                                                     │
│  # 🔍 Unknown Issue Investigation                                  │
│  **Severity**: 7.5/10                                              │
│  **Occurrences**: 5 times                                          │
│                                                                     │
│  ## Auto-Detected Patterns:                                        │
│  - `connection timeout.*port 5432`                                 │
│  - `database.*unavailable`                                         │
│                                                                     │
│  ## Container Logs:                                                │
│  [Last 50 lines...]                                                │
│                                                                     │
│  ## Investigation Checklist:                                       │
│  - [ ] Identify root cause                                         │
│  - [ ] Classify category                                           │
│  - [ ] Submit resolution via API                                   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ↓                   ↓
┌─────────────────────────┐  ┌─────────────────────────┐
│ LAYER 4:                │  │ LAYER 5:                │
│ Pattern Discovery       │  │ Human Feedback API      │
│ Engine                  │  │                         │
│ (Weekly Job)            │  │ POST /api/feedback/     │
│                         │  │   resolution            │
│ Finds patterns in       │  │                         │
│ unknown issues:         │  │ SRE teaches agent:      │
│ - Recurring errors      │  │ - Root cause            │
│ - Common keywords       │  │ - Category              │
│ - Regex patterns        │  │ - Recommended actions   │
│                         │  │                         │
│ Generates:              │  │ Creates:                │
│ - Pattern suggestions   │  │ - Incident record       │
│ - Proposed analyzer     │  │ - Knowledge base entry  │
│   rules                 │  │ - Learning signal       │
└─────────────────────────┘  └─────────────────────────┘
                    │                   │
                    └─────────┬─────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 6: Progressive Learning Engine                               │
│                                                                     │
│  1. Auto-Promote Patterns                                          │
│     - Pattern occurs >= 5 times                                    │
│     - 100% human validation                                        │
│     - Generate new analyzer code                                   │
│     - Deploy via GitOps PR                                         │
│                                                                     │
│  2. Knowledge Base Enrichment                                      │
│     - Resolved unknowns → Incident records                         │
│     - Future similar issues use this knowledge                     │
│     - MTTR reduced dramatically                                    │
│                                                                     │
│  3. Confidence Adjustment                                          │
│     - Track analyzer success rates                                 │
│     - Adjust confidence scores                                     │
│     - Improve diagnosis accuracy                                   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ↓
                    ✨ Agent Gets Smarter ✨
```

---

## 📈 Example Lifecycle: Unknown → Known

```
════════════════════════════════════════════════════════════════════
TIMELINE: Unknown Issue Becoming Known
════════════════════════════════════════════════════════════════════

DAY 1: First Occurrence
────────────────────────
🔴 New issue: "Connection timeout to database:5432"
   ├─ Pattern analyzers: No match
   ├─ LLM analyzer: Low confidence
   └─ Unknown Handler: ✓ Catches it
       ├─ Fingerprint: a1b2c3d4e5f6
       ├─ Stores in database
       ├─ occurrence_count: 1
       ├─ severity_score: 6.0
       └─ Creates GitHub issue #142


DAY 2-6: Recurrence Tracking
─────────────────────────────
🔴 Same issue occurs 4 more times
   └─ Unknown Handler: Deduplicates by fingerprint
       ├─ occurrence_count: 5
       ├─ severity_score: 8.5 (increased)
       └─ Updates GitHub issue


DAY 7: Pattern Discovery (Weekly Job)
──────────────────────────────────────
🔍 Pattern Discovery Engine runs
   ├─ Scans unknown_issues table
   ├─ Finds fingerprint a1b2c3 with 5 occurrences
   ├─ Extracts pattern: "connection timeout.*port 5432"
   └─ Creates pattern suggestion:
       Category: database_connection_timeout
       Tier: 3 (manual investigation)
       Regex: /connection\s+timeout.*port\s+5432/i


DAY 8: Human Investigation
───────────────────────────
👨‍💻 SRE John reviews GitHub issue #142
   ├─ Investigates: Database connection pool exhausted
   ├─ Fix: Increased connection pool size + added retry logic
   └─ Submits resolution via API:
       POST /api/feedback/resolution
       {
         "unknown_id": "uuid-123",
         "root_cause": "Database connection pool exhausted during peak traffic",
         "category": "database_connection_timeout",
         "recommended_tier": 2,  # Can be fixed with config change
         "recommended_actions": [
           "Increase connection pool size",
           "Add connection retry logic",
           "Monitor connection pool metrics"
         ]
       }


DAY 9: Knowledge Base Enrichment
─────────────────────────────────
💾 Learning Engine processes John's feedback
   ├─ Creates incident record in knowledge_store
   ├─ Links pattern to solution
   └─ Marks unknown as resolved


DAY 14: Pattern Approval (Next Weekly Cycle)
─────────────────────────────────────────────
✅ SRE reviews pattern suggestion
   ├─ Approves pattern for auto-promotion
   └─ Learning Engine:
       ├─ Generates new analyzer code
       ├─ Creates GitOps PR
       └─ Deploys DatabaseConnectionAnalyzer


DAY 21: Auto-Diagnosis! (Unknown → Known)
──────────────────────────────────────────
🔴 Same issue occurs again
   └─ DatabaseConnectionAnalyzer (NEW): ✓ Matches pattern!
       ├─ Category: database_connection_timeout
       ├─ Confidence: HIGH
       ├─ Tier: 2 (GitOps PR)
       ├─ Root Cause: "Database connection pool exhausted (based on past incident)"
       └─ Recommended Actions: [John's solutions from Day 8]

✨ No longer unknown! MTTR reduced from 7 days → 2 minutes


DAY 30: Full Automation (Unknown → Automated)
──────────────────────────────────────────────
(After pattern proves reliable)
🔴 Same issue occurs again
   └─ DatabaseConnectionAnalyzer: ✓ Matches pattern
       ├─ Tier 2 handler creates GitOps PR automatically
       ├─ PR increases connection pool size
       ├─ Auto-merges after tests pass
       └─ Issue resolved in 5 minutes

🎯 Fully automated!


════════════════════════════════════════════════════════════════════
METRICS: 30-Day Journey
════════════════════════════════════════════════════════════════════

Day 1:  Unknown issue, MTTR: ∞ (manual investigation needed)
Day 8:  Human resolved, MTTR: 7 days (manual investigation)
Day 21: Auto-diagnosed, MTTR: 2 minutes (knowledge base lookup)
Day 30: Auto-remediated, MTTR: 5 minutes (GitOps automation)

Unknown Rate: 100% → 0% (for this issue type)
Agent Coverage: Pattern now in production analyzer
Learning Outcome: Unknown → Known → Automated
```

---

## 🎯 Key Design Principles

### 1. **Zero Data Loss**
```python
# UnknownIssueHandler MUST be registered LAST
workflow_engine.register_analyzer(CrashLoopAnalyzer(mcp_registry))
workflow_engine.register_analyzer(LLMAnalyzer(mcp_registry))
workflow_engine.register_analyzer(UnknownIssueHandler(mcp_registry))  # LAST!

# can_analyze() → Always True (catches everything)
# analyze() → NEVER returns None (always creates diagnosis)
```

### 2. **Human-in-the-Loop Safety**
```
Discovered Pattern → Human Review → Approval → Auto-Promotion

NOT:
Discovered Pattern → Auto-Deploy (❌ too risky)
```

### 3. **Progressive Complexity**
```
Phase 1: Track unknowns (simple)
  ↓
Phase 2: Discover patterns (moderate)
  ↓
Phase 3: Human feedback (interactive)
  ↓
Phase 4: Auto-promotion (advanced)
  ↓
Phase 5: Full automation (expert)
```

### 4. **Graceful Degradation**
```
Analyzer Chain:
  Most Specific (CrashLoopAnalyzer)
    ↓
  Less Specific (LLMAnalyzer)
    ↓
  Generic Fallback (UnknownIssueHandler)

Each layer is a safety net for the one above.
```

---

## 📊 Success Metrics

### Immediate (Phase 1)
- ✅ **100% Observation Coverage** - All observations get diagnosed
- ✅ **Unknown Tracking** - Count of unknown issues visible
- ✅ **Investigation Templates** - Rich context for SREs

### Short-term (Phase 2-3)
- ✅ **Pattern Discovery** - 2-3 new patterns discovered per month
- ✅ **Human Feedback** - 50%+ unknowns get human resolution
- ✅ **Unknown Reduction** - 10-20% decrease in unknown rate per month

### Long-term (Phase 4-6)
- ✅ **Auto-Promotion** - 30%+ discovered patterns auto-promoted
- ✅ **MTTR Improvement** - 50%+ reduction in MTTR for learned issues
- ✅ **Coverage Growth** - Agent handles 95%+ of production issues

---

## 🚀 Implementation Timeline

| Phase | Duration | Effort | Priority |
|-------|----------|--------|----------|
| Phase 1: Unknown Handler | 2 hours | Low | 🔴 CRITICAL |
| Phase 2: Dashboard | 4 hours | Medium | 🟠 HIGH |
| Phase 3: Database Store | 1 day | Medium | 🟡 MEDIUM |
| Phase 4: Feedback API | 1 day | Medium | 🟡 MEDIUM |
| Phase 5: Pattern Discovery | 1 week | High | 🟢 NICE TO HAVE |
| Phase 6: Auto-Promotion | 2 weeks | High | 🟢 NICE TO HAVE |

**Recommendation**: Start with Phase 1 today (2 hours), get immediate value.

---

## ⚡ Quick Start (5 minutes)

```bash
# 1. Register Unknown Issue Handler
# Edit: main.py, add after LLMAnalyzer:
workflow_engine.register_analyzer(UnknownIssueHandler(mcp_registry))

# 2. Restart agent
python main.py

# 3. Verify
# Check logs for: "✅ Registered 9 analyzers" (one more than before)

# 4. Test
curl -X POST http://localhost:8000/trigger-workflow

# 5. Done!
# All observations now get diagnosed (100% coverage)
```

---

## 🎓 Summary

This architecture transforms the agent from **static pattern matcher** to **learning system**:

**Before**: Agent knows what it knows, stays dumb forever
**After**: Agent learns from unknowns, gets smarter over time

**Key Innovation**: UnknownIssueHandler ensures **zero data loss** and creates **learning loop**.

**Result**: Every unknown issue becomes a learning opportunity.

---

## 📚 Related Documents

- [Full Architecture](ARCHITECTURE_UNKNOWN_HANDLING.md) - Complete 6-layer design
- [Quick Start Guide](QUICKSTART_UNKNOWN_HANDLING.md) - Implementation steps
- [Unknown Issue Handler](sre_agent/analyzers/unknown_issue_handler.py) - Code implementation

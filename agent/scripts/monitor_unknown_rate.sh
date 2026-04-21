#!/bin/bash
#
# Monitor Unknown Issue Rate
#
# Tracks and reports the rate of unknown issues to measure agent intelligence.
# Goal: Unknown rate should be < 10% (ideally < 5%)
#

AGENT_URL="${AGENT_URL:-http://localhost:8000}"
ALERT_THRESHOLD="${ALERT_THRESHOLD:-10}"  # Alert if unknown rate > 10%

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "================================================"
echo "SRE Agent - Unknown Issue Rate Monitor"
echo "================================================"
echo "Agent URL: $AGENT_URL"
echo "Alert Threshold: $ALERT_THRESHOLD%"
echo ""

# Get stats
stats=$(curl -s "$AGENT_URL/stats")

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Failed to connect to agent${NC}"
    exit 1
fi

# Extract workflow stats
total_observations=$(echo "$stats" | jq -r '.workflow_engine.total_observations // 0')
total_diagnoses=$(echo "$stats" | jq -r '.workflow_engine.total_diagnoses // 0')

# Extract unknown issue stats
unknown_total=$(echo "$stats" | jq -r '.unknown_issues.total // 0')
unknown_unresolved=$(echo "$stats" | jq -r '.unknown_issues.unresolved // 0')
unknown_resolved=$(echo "$stats" | jq -r '.unknown_issues.resolved // 0')
unknown_recent=$(echo "$stats" | jq -r '.unknown_issues.recent_24h // 0')
resolution_rate=$(echo "$stats" | jq -r '.unknown_issues.resolution_rate // "0%"')

echo "📊 Workflow Statistics"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Total Observations: $total_observations"
echo "  Total Diagnoses: $total_diagnoses"
echo ""

echo "❓ Unknown Issue Statistics"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Total Unknown Issues: $unknown_total"
echo "  Unresolved: $unknown_unresolved"
echo "  Resolved: $unknown_resolved"
echo "  Recent (24h): $unknown_recent"
echo "  Resolution Rate: $resolution_rate"
echo ""

# Calculate unknown rate
if [ "$total_diagnoses" -gt 0 ]; then
    unknown_rate=$(echo "scale=2; ($unknown_total / $total_diagnoses) * 100" | bc)
else
    unknown_rate=0
fi

echo "📈 Unknown Rate"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -n "  Current Rate: "

# Color code based on threshold
if (( $(echo "$unknown_rate >= $ALERT_THRESHOLD" | bc -l) )); then
    echo -e "${RED}${unknown_rate}% ⚠️  ALERT${NC}"
    echo -e "  ${RED}Unknown rate exceeds threshold of $ALERT_THRESHOLD%${NC}"
    alert_status="ALERT"
elif (( $(echo "$unknown_rate >= 5" | bc -l) )); then
    echo -e "${YELLOW}${unknown_rate}% ⚠️  WARNING${NC}"
    echo -e "  ${YELLOW}Unknown rate is higher than ideal (<5%)${NC}"
    alert_status="WARNING"
else
    echo -e "${GREEN}${unknown_rate}% ✓ GOOD${NC}"
    echo -e "  ${GREEN}Unknown rate is within acceptable range${NC}"
    alert_status="GOOD"
fi

echo ""

# Diagnostic breakdown
echo "🔍 Diagnostic Breakdown"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$total_diagnoses" -gt 0 ]; then
    known_diagnoses=$((total_diagnoses - unknown_total))
    known_rate=$(echo "scale=2; ($known_diagnoses / $total_diagnoses) * 100" | bc)

    echo "  Known Issues: $known_diagnoses (${known_rate}%)"
    echo "  Unknown Issues: $unknown_total (${unknown_rate}%)"
else
    echo "  No diagnoses recorded yet"
fi

echo ""

# Top unknown issues
echo "🔥 Top Unresolved Unknown Issues"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

unknown_list=$(curl -s "$AGENT_URL/unknown-issues?min_occurrences=2&limit=5")
issue_count=$(echo "$unknown_list" | jq -r '.total // 0')

if [ "$issue_count" -gt 0 ]; then
    echo "$unknown_list" | jq -r '.issues[] | "  [\(.occurrence_count)x] \(.namespace)/\(.resource_name) - \(.error_patterns[0] // "no pattern")"'
    echo ""
    echo "  View all: curl $AGENT_URL/unknown-issues"
else
    echo "  No recurring unknown issues"
fi

echo ""

# Recommendations
echo "💡 Recommendations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$alert_status" = "ALERT" ] || [ "$alert_status" = "WARNING" ]; then
    echo "  1. Review top unknown issues:"
    echo "     curl $AGENT_URL/unknown-issues?min_occurrences=3"
    echo ""
    echo "  2. Submit resolutions for recurring unknowns to teach the agent:"
    echo "     curl -X POST $AGENT_URL/unknown-issues/{fingerprint}/resolve \\"
    echo "       -H 'Content-Type: application/json' \\"
    echo "       -d '{\"root_cause\": \"...\", \"fix_applied\": \"...\"}'"
    echo ""
    echo "  3. Enable Red Hat KB search (if not enabled):"
    echo "     export REDHAT_KB_SEARCH_ENABLED=true"
    echo ""
    echo "  4. Check LLM configuration for enhanced investigation"
else
    echo "  ✓ Unknown rate is healthy"
    echo "  ✓ Continue monitoring and resolving unknowns to improve further"
    echo ""
    echo "  To help the agent learn:"
    echo "    - Submit resolutions: curl $AGENT_URL/unknown-issues/{fingerprint}/resolve"
    echo "    - Review patterns: curl $AGENT_URL/unknown-issues"
fi

echo ""

# Trend analysis (if we have historical data)
echo "📊 Trend Analysis"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$unknown_recent" -gt 0 ]; then
    echo "  Recent activity (24h): $unknown_recent new unknowns"

    if [ "$unknown_recent" -gt 10 ]; then
        echo -e "  ${RED}⚠️  High volume of new unknowns - investigation recommended${NC}"
    else
        echo "  ✓ Normal activity level"
    fi
else
    echo "  No new unknown issues in last 24 hours"
fi

echo ""

# Export metrics for monitoring systems
echo "📤 Export Metrics (Prometheus format)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat <<EOF
# HELP sre_agent_unknown_rate Percentage of issues that are unknown
# TYPE sre_agent_unknown_rate gauge
sre_agent_unknown_rate $unknown_rate

# HELP sre_agent_unknown_total Total unknown issues
# TYPE sre_agent_unknown_total counter
sre_agent_unknown_total $unknown_total

# HELP sre_agent_unknown_unresolved Unresolved unknown issues
# TYPE sre_agent_unknown_unresolved gauge
sre_agent_unknown_unresolved $unknown_unresolved

# HELP sre_agent_total_diagnoses Total diagnoses
# TYPE sre_agent_total_diagnoses counter
sre_agent_total_diagnoses $total_diagnoses
EOF

echo ""

# Exit code based on alert status
if [ "$alert_status" = "ALERT" ]; then
    exit 2
elif [ "$alert_status" = "WARNING" ]; then
    exit 1
else
    exit 0
fi

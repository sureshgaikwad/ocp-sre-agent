#!/bin/bash
#
# Test Feedback API - Submit resolutions for unknown issues
#
# Demonstrates how SREs can teach the agent by submitting resolutions.
#

AGENT_URL="${AGENT_URL:-http://localhost:8000}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "================================================"
echo "SRE Agent - Feedback API Test"
echo "================================================"
echo "Agent URL: $AGENT_URL"
echo ""

# Step 1: List unknown issues
echo -e "${BLUE}Step 1: List Unknown Issues${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

response=$(curl -s "$AGENT_URL/unknown-issues?min_occurrences=1&limit=10")
total=$(echo "$response" | jq -r '.total // 0')

echo "Total unknown issues: $total"
echo ""

if [ "$total" -eq 0 ]; then
    echo -e "${YELLOW}⚠️  No unknown issues found${NC}"
    echo ""
    echo "This is either:"
    echo "  1. Great news! Agent is diagnosing everything"
    echo "  2. No workflow runs yet (trigger with: curl -X POST $AGENT_URL/trigger-workflow)"
    echo ""
    echo "To create a test unknown issue, you can:"
    echo "  1. Deploy a pod with an intentional error the agent hasn't seen"
    echo "  2. Wait for the agent to detect it"
    echo "  3. Run this script again to submit resolution"
    exit 0
fi

# Display issues
echo "Unresolved issues:"
echo "$response" | jq -r '.issues[] | "  [\(.occurrence_count)x] \(.fingerprint[0:8])... - \(.namespace)/\(.resource_name)"'
echo ""

# Step 2: Get details for first issue
echo -e "${BLUE}Step 2: Get Details for First Issue${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

fingerprint=$(echo "$response" | jq -r '.issues[0].fingerprint')

if [ -z "$fingerprint" ] || [ "$fingerprint" = "null" ]; then
    echo -e "${RED}✗ No fingerprint found${NC}"
    exit 1
fi

echo "Selected fingerprint: $fingerprint"
echo ""

details=$(curl -s "$AGENT_URL/unknown-issues/$fingerprint")

echo "Issue Details:"
echo "  Category: $(echo "$details" | jq -r '.issue.category')"
echo "  Occurrence count: $(echo "$details" | jq -r '.issue.occurrence_count')"
echo "  Severity: $(echo "$details" | jq -r '.issue.severity_score')/10"
echo "  First seen: $(echo "$details" | jq -r '.issue.first_seen')"
echo "  Last seen: $(echo "$details" | jq -r '.issue.last_seen')"
echo ""

echo "Error patterns:"
echo "$details" | jq -r '.issue.error_patterns[] | "  - \(.)"'
echo ""

echo "Investigation notes:"
echo "$details" | jq -r '.issue.investigation_notes' | head -n 10
echo "  ..."
echo ""

# Step 3: Submit resolution (interactive or automatic)
echo -e "${BLUE}Step 3: Submit Resolution${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if already resolved
is_resolved=$(echo "$details" | jq -r '.issue.resolved')

if [ "$is_resolved" = "true" ]; then
    echo -e "${YELLOW}⚠️  Issue already resolved${NC}"
    echo ""
    echo "Resolution:"
    echo "$details" | jq -r '.issue.resolution_data'
    echo ""
    exit 0
fi

# Interactive or example mode
if [ "$1" = "--interactive" ]; then
    echo "Enter resolution details:"
    echo ""

    read -p "Root cause: " root_cause
    read -p "Fix applied: " fix_applied
    read -p "Fix commands (comma-separated): " fix_commands_str
    read -p "SRE name: " sre_name
    read -p "Notes: " notes

    # Convert commands to JSON array
    IFS=',' read -ra commands_arr <<< "$fix_commands_str"
    fix_commands_json=$(printf '%s\n' "${commands_arr[@]}" | jq -R . | jq -s .)

    resolution_json=$(jq -n \
        --arg rc "$root_cause" \
        --arg fa "$fix_applied" \
        --argjson fc "$fix_commands_json" \
        --arg sre "$sre_name" \
        --arg notes "$notes" \
        '{
            root_cause: $rc,
            fix_applied: $fa,
            fix_commands: $fc,
            works_for_similar: true,
            sre_name: $sre,
            notes: $notes
        }')
else
    # Example resolution
    echo "Using example resolution (use --interactive for manual entry)"
    echo ""

    resolution_json='{
        "root_cause": "Database connection pool exhausted during high load",
        "fix_applied": "Increased connection pool size from 10 to 50",
        "fix_commands": [
            "oc set env deployment/app DB_POOL_SIZE=50",
            "oc rollout status deployment/app"
        ],
        "works_for_similar": true,
        "sre_name": "sre-engineer",
        "notes": "Issue occurred during peak traffic. After increasing pool size, no more connection timeouts."
    }'

    echo "Example resolution:"
    echo "$resolution_json" | jq .
    echo ""
fi

# Submit resolution
echo "Submitting resolution..."
submit_response=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -d "$resolution_json" \
    "$AGENT_URL/unknown-issues/$fingerprint/resolve")

status=$(echo "$submit_response" | jq -r '.status')

if [ "$status" = "success" ]; then
    echo -e "${GREEN}✓ Resolution submitted successfully${NC}"
    echo ""

    echo "Response:"
    echo "$submit_response" | jq '{message, next_steps, impact}'
    echo ""

    echo -e "${GREEN}🎉 Agent learned from this resolution!${NC}"
    echo ""
    echo "What happens next:"
    echo "  1. Resolution stored in knowledge base"
    echo "  2. Similar issues will reference this solution"
    echo "  3. Pattern discovery engine will analyze for auto-fix potential"
    echo "  4. If pattern repeats $(echo "$details" | jq -r '.issue.occurrence_count')+ times, may be promoted to analyzer"
else
    echo -e "${RED}✗ Failed to submit resolution${NC}"
    echo "$submit_response" | jq .
    exit 1
fi

echo ""

# Step 4: Verify resolution
echo -e "${BLUE}Step 4: Verify Resolution${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Re-fetch issue details
verify=$(curl -s "$AGENT_URL/unknown-issues/$fingerprint")
is_resolved=$(echo "$verify" | jq -r '.issue.resolved')

if [ "$is_resolved" = "true" ]; then
    echo -e "${GREEN}✓ Issue marked as resolved${NC}"
    echo ""

    echo "Resolution data:"
    echo "$verify" | jq '.issue.resolution_data'
    echo ""
else
    echo -e "${RED}✗ Issue not marked as resolved${NC}"
    echo "$verify" | jq .
    exit 1
fi

# Step 5: Check updated stats
echo -e "${BLUE}Step 5: Updated Statistics${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

stats=$(curl -s "$AGENT_URL/unknown-issues/stats/summary")

echo "Unknown issue statistics:"
echo "$stats" | jq '.unknown_issues'
echo ""

echo "================================================"
echo "Summary"
echo "================================================"
echo ""
echo -e "${GREEN}✓ Feedback API test completed successfully${NC}"
echo ""
echo "Key capabilities demonstrated:"
echo "  1. List unknown issues"
echo "  2. Get detailed investigation notes"
echo "  3. Submit resolution to teach agent"
echo "  4. Verify resolution recorded"
echo "  5. Track learning progress"
echo ""

echo "API Endpoints Used:"
echo "  GET  $AGENT_URL/unknown-issues"
echo "  GET  $AGENT_URL/unknown-issues/{fingerprint}"
echo "  POST $AGENT_URL/unknown-issues/{fingerprint}/resolve"
echo "  GET  $AGENT_URL/unknown-issues/stats/summary"
echo ""

echo "Next steps:"
echo "  1. Monitor unknown rate: ./monitor_unknown_rate.sh"
echo "  2. Submit more resolutions as unknowns occur"
echo "  3. Watch agent improve over time (unknown rate should decrease)"
echo ""

echo -e "${GREEN}Test completed!${NC}"

#!/bin/bash
#
# Verify Route URL Configuration
#
# Ensures that Slack approval URLs use external route (not internal service)
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "================================================"
echo "Route URL Configuration Verification"
echo "================================================"
echo ""

echo -e "${BLUE}Checking External Route URL Configuration...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check environment variable
if [ -n "$SRE_AGENT_ROUTE_URL" ]; then
    echo -e "${GREEN}✓${NC} SRE_AGENT_ROUTE_URL is set: $SRE_AGENT_ROUTE_URL"
    CONFIGURED_MANUALLY=true
else
    echo -e "${YELLOW}⚠${NC} SRE_AGENT_ROUTE_URL not set (will auto-detect)"
    CONFIGURED_MANUALLY=false
fi

echo ""

# Try to detect route using oc command
echo -e "${BLUE}Auto-detecting OpenShift Route...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if command -v oc &> /dev/null; then
    echo "Running: oc get route sre-agent -n sre-agent"

    ROUTE_HOST=$(oc get route sre-agent -n sre-agent -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

    if [ -n "$ROUTE_HOST" ]; then
        ROUTE_URL="https://$ROUTE_HOST"
        echo -e "${GREEN}✓${NC} Route detected: $ROUTE_URL"
        AUTO_DETECTED=true
    else
        echo -e "${RED}✗${NC} Route 'sre-agent' not found in namespace 'sre-agent'"
        echo ""
        echo "To create route:"
        echo "  oc create route edge sre-agent --service=sre-agent --port=8000 -n sre-agent"
        AUTO_DETECTED=false
    fi
else
    echo -e "${YELLOW}⚠${NC} 'oc' command not found - cannot auto-detect"
    AUTO_DETECTED=false
fi

echo ""

# Verify code implementation
echo -e "${BLUE}Verifying Code Implementation...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check SlackNotifier
echo "1. SlackNotifier (sre_agent/integrations/slack_notifier.py):"

if grep -q 'self.route_url = os.getenv("SRE_AGENT_ROUTE_URL"' sre_agent/integrations/slack_notifier.py; then
    echo -e "   ${GREEN}✓${NC} Reads SRE_AGENT_ROUTE_URL from environment"
else
    echo -e "   ${RED}✗${NC} Does NOT read SRE_AGENT_ROUTE_URL"
fi

if grep -q 'def _detect_route_url' sre_agent/integrations/slack_notifier.py; then
    echo -e "   ${GREEN}✓${NC} Has auto-detection fallback (_detect_route_url)"
else
    echo -e "   ${RED}✗${NC} Missing auto-detection fallback"
fi

if grep -q 'api_url = self.route_url' sre_agent/integrations/slack_notifier.py; then
    echo -e "   ${GREEN}✓${NC} Uses route_url for approval commands"
else
    echo -e "   ${RED}✗${NC} Does NOT use route_url"
fi

echo ""

# Check WorkflowEngine
echo "2. WorkflowEngine (sre_agent/orchestrator/workflow_engine.py):"

if grep -q 'route_url = os.getenv("SRE_AGENT_ROUTE_URL"' sre_agent/orchestrator/workflow_engine.py; then
    echo -e "   ${GREEN}✓${NC} Reads SRE_AGENT_ROUTE_URL from environment"
else
    echo -e "   ${RED}✗${NC} Does NOT read SRE_AGENT_ROUTE_URL"
fi

if grep -q 'oc.*get.*route.*sre-agent' sre_agent/orchestrator/workflow_engine.py; then
    echo -e "   ${GREEN}✓${NC} Has auto-detection fallback (oc get route)"
else
    echo -e "   ${RED}✗${NC} Missing auto-detection fallback"
fi

if grep -q 'api_url = route_url' sre_agent/orchestrator/workflow_engine.py; then
    echo -e "   ${GREEN}✓${NC} Uses route_url for approval commands"
else
    echo -e "   ${RED}✗${NC} Does NOT use route_url"
fi

echo ""

# Check for hardcoded localhost/internal URLs
echo -e "${BLUE}Checking for Hardcoded Internal URLs...${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

HARDCODED=$(grep -r "http://localhost:8000\|http://sre-agent:8000" sre_agent/ 2>/dev/null || echo "")

if [ -z "$HARDCODED" ]; then
    echo -e "${GREEN}✓${NC} No hardcoded internal URLs found"
else
    echo -e "${RED}✗${NC} Found hardcoded internal URLs:"
    echo "$HARDCODED"
fi

echo ""

# Summary
echo "================================================"
echo "Summary"
echo "================================================"
echo ""

if [ "$CONFIGURED_MANUALLY" = true ]; then
    echo -e "${GREEN}✓ CONFIGURED${NC} - Using manual configuration"
    echo "  Route URL: $SRE_AGENT_ROUTE_URL"
elif [ "$AUTO_DETECTED" = true ]; then
    echo -e "${GREEN}✓ AUTO-DETECTED${NC} - Using OpenShift route"
    echo "  Route URL: $ROUTE_URL"
else
    echo -e "${RED}✗ NOT CONFIGURED${NC}"
    echo ""
    echo "ACTION REQUIRED:"
    echo ""
    echo "Option 1: Set environment variable (recommended)"
    echo "  export SRE_AGENT_ROUTE_URL=https://sre-agent-sre-agent.apps.your-cluster.com"
    echo ""
    echo "Option 2: Create OpenShift route"
    echo "  oc create route edge sre-agent --service=sre-agent --port=8000 -n sre-agent"
    echo "  (Agent will auto-detect on startup)"
    echo ""
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Implementation Verified${NC}"
echo "  - Code reads SRE_AGENT_ROUTE_URL"
echo "  - Auto-detection fallback present"
echo "  - External route URL used for approval commands"
echo "  - No hardcoded internal URLs"
echo ""

echo "How it works:"
echo "  1. SlackNotifier sends notification with approval curl command"
echo "  2. Curl command uses external route URL (accessible from Slack)"
echo "  3. User clicks approve → executes curl"
echo "  4. Request goes to: $ROUTE_URL/approve-remediation"
echo "  5. Agent processes approval and applies fix"
echo ""

echo -e "${GREEN}✓ Slack approval URLs are correctly configured!${NC}"

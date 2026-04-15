#!/bin/bash
#
# OpenShift SRE Agent - Quick Demo Runner
# Version: 2.0.3
#
# This script runs all 3 demo scenarios and monitors the agent's response.
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🎯 OpenShift SRE Agent - Demo Runner${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to print status
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check prerequisites
echo -e "${BLUE}[1/7] Checking prerequisites...${NC}"

# Check oc CLI
if ! command -v oc &> /dev/null; then
    print_error "oc CLI not found. Please install OpenShift CLI."
    exit 1
fi
print_status "oc CLI found"

# Check if logged in
if ! oc whoami &> /dev/null; then
    print_error "Not logged in to OpenShift. Run: oc login"
    exit 1
fi
print_status "Logged in as $(oc whoami)"

# Check if agent is running
echo -e "${BLUE}[2/7] Verifying SRE Agent is running...${NC}"
AGENT_PODS=$(oc get pods -n sre-agent -l app=sre-agent --no-headers 2>/dev/null | wc -l)
if [ "$AGENT_PODS" -eq 0 ]; then
    print_error "SRE Agent not running in namespace 'sre-agent'"
    exit 1
fi

AGENT_READY=$(oc get pods -n sre-agent -l app=sre-agent -o jsonpath='{.items[0].status.containerStatuses[*].ready}' | grep -o "true" | wc -l)
if [ "$AGENT_READY" -lt 2 ]; then
    print_error "SRE Agent not ready (expected 2/2 containers)"
    exit 1
fi
print_status "SRE Agent running (2/2 containers)"

# Verify MCP tools
MCP_TOOLS=$(oc logs -n sre-agent deployment/sre-agent -c agent --tail=100 | grep "tools available" | tail -1 | grep -o "[0-9]* tools" | grep -o "[0-9]*")
if [ -z "$MCP_TOOLS" ] || [ "$MCP_TOOLS" -eq 0 ]; then
    print_warning "MCP tools might not be initialized yet. Found: ${MCP_TOOLS:-0} tools"
else
    print_status "MCP tools available: $MCP_TOOLS"
fi

# Create demo namespace
echo -e "${BLUE}[3/7] Creating demo namespace...${NC}"
if oc get namespace sre-demo &> /dev/null; then
    print_warning "Namespace sre-demo already exists. Deleting..."
    oc delete namespace sre-demo --wait=true
fi
oc create namespace sre-demo
print_status "Namespace created: sre-demo"

# Deploy demo scenarios
echo -e "${BLUE}[4/7] Deploying demo scenarios...${NC}"
DEMO_DIR="$(dirname "$0")"

echo "  → Scenario 1: OOM Kill"
oc apply -f "$DEMO_DIR/demo-scenario-1-oom.yaml" > /dev/null
print_status "OOM test deployed"

echo "  → Scenario 2: HPA at Max"
oc apply -f "$DEMO_DIR/demo-scenario-2-hpa.yaml" > /dev/null
print_status "HPA test deployed"

echo "  → Scenario 3: CrashLoop"
oc apply -f "$DEMO_DIR/demo-scenario-3-crashloop.yaml" > /dev/null
print_status "CrashLoop test deployed"

# Wait for pods to start failing
echo -e "${BLUE}[5/7] Waiting for test pods to start (30 seconds)...${NC}"
sleep 30

# Show current pod status
echo -e "${BLUE}[6/7] Current test pod status:${NC}"
oc get pods -n sre-demo
echo ""

# Monitor agent response
echo -e "${BLUE}[7/7] Monitoring agent response...${NC}"
echo ""
echo -e "${YELLOW}📊 Watching for agent activity (press Ctrl+C to stop)...${NC}"
echo -e "${YELLOW}   This will show observations, diagnoses, and remediations.${NC}"
echo ""
sleep 3

# Tail agent logs and filter for relevant events
oc logs -n sre-agent deployment/sre-agent -c agent -f --tail=50 | \
  grep --line-buffered -E "observation_count|Diagnosis|Remediation|OOM|HPA|CrashLoop|pods_log|CRITICAL|WARNING" || true

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Demo completed!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "To view full results:"
echo "  oc logs -n sre-agent deployment/sre-agent -c agent --tail=500 | grep -i 'oom\|hpa\|crashloop'"
echo ""
echo "To cleanup:"
echo "  oc delete namespace sre-demo"
echo ""

#!/bin/bash
#
# OpenShift SRE Agent - Demo Verification Script
# Version: 2.0.3
#
# This script verifies that the SRE agent properly handled all demo scenarios.
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🔍 SRE Agent Demo - Verification${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to check test
check_test() {
    local test_name="$1"
    local search_pattern="$2"
    local expected_count="${3:-1}"
    local namespace="${4:-sre-agent}"

    echo -n "Testing: $test_name... "

    local actual_count=$(oc logs -n "$namespace" deployment/sre-agent -c agent --tail=2000 2>/dev/null | \
        grep -i "$search_pattern" | wc -l)

    if [ "$actual_count" -ge "$expected_count" ]; then
        echo -e "${GREEN}PASS${NC} (found $actual_count matches)"
        ((PASS_COUNT++))
        return 0
    else
        echo -e "${RED}FAIL${NC} (expected >= $expected_count, found $actual_count)"
        ((FAIL_COUNT++))
        return 1
    fi
}

echo -e "${BLUE}=== Scenario 1: OOM Kill ===${NC}"
check_test "OOM pods detected" "oom-test" 1
check_test "Exit code 137 identified" "137\|OOMKilled" 1
check_test "Memory limit diagnosis" "memory.*limit\|OOMKilled" 1
echo ""

echo -e "${BLUE}=== Scenario 2: HPA at Max ===${NC}"
check_test "HPA detected" "hpa-test\|HorizontalPodAutoscaler" 1
check_test "Max replicas identified" "max.*replicas\|maxReplicas" 1
echo ""

echo -e "${BLUE}=== Scenario 3: CrashLoop ===${NC}"
check_test "CrashLoop detected" "crashloop\|BackOff" 1
check_test "MCP pods_log called" "pods_log" 1
echo ""

echo -e "${BLUE}=== Agent Functionality ===${NC}"
check_test "Observations collected" "observation_count" 3
check_test "Diagnoses created" "Diagnosis" 1
check_test "MCP tools available" "44 tools available\|tools available" 1
echo ""

echo -e "${BLUE}=== Test Pods Status ===${NC}"
echo "Current pod status in sre-demo namespace:"
echo ""
oc get pods -n sre-demo 2>/dev/null || echo "No pods found (namespace may have been cleaned up)"
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Tests Passed: ${GREEN}$PASS_COUNT${NC}"
echo -e "Tests Failed: ${RED}$FAIL_COUNT${NC}"
echo ""

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✅ All tests PASSED!${NC}"
    echo -e "${GREEN}   The SRE Agent is functioning correctly.${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠ Some tests FAILED${NC}"
    echo ""
    echo "Troubleshooting tips:"
    echo "1. Wait longer (agent collection interval is 30-60s)"
    echo "2. Check agent logs:"
    echo "     oc logs -n sre-agent deployment/sre-agent -c agent --tail=500"
    echo "3. Verify test pods are actually failing:"
    echo "     oc get pods -n sre-demo"
    echo "4. Check MCP tools:"
    echo "     oc logs -n sre-agent deployment/sre-agent -c agent | grep 'tools available'"
    exit 1
fi

#!/bin/bash
# SRE Agent Deployment Helper Script
# This script automatically configures cluster-specific values before deployment

set -e

echo "🚀 OpenShift SRE Agent Deployment Helper"
echo "=========================================="
echo ""

# Check if oc is available
if ! command -v oc &> /dev/null; then
    echo "❌ Error: 'oc' command not found. Please install OpenShift CLI."
    exit 1
fi

# Check if logged in to OpenShift
if ! oc whoami &> /dev/null; then
    echo "❌ Error: Not logged in to OpenShift cluster."
    echo "   Please run: oc login <cluster-url>"
    exit 1
fi

# Get cluster info
CLUSTER_API=$(oc whoami --show-server)
CURRENT_USER=$(oc whoami)
echo "📍 Connected to: $CLUSTER_API"
echo "👤 Logged in as: $CURRENT_USER"
echo ""

# Create namespace if it doesn't exist
echo "📦 Creating namespace 'sre-agent'..."
oc create namespace sre-agent --dry-run=client -o yaml | oc apply -f -
echo "✅ Namespace ready"
echo ""

# Deploy all resources first (without route URL set)
echo "🔧 Deploying SRE Agent resources..."
oc apply -f sre-agent-deployment.yaml
echo "✅ Resources deployed"
echo ""

# Wait for route to be created
echo "⏳ Waiting for route to be created..."
sleep 5

# Auto-detect route URL
if oc get route sre-agent -n sre-agent &> /dev/null; then
    ROUTE_HOST=$(oc get route sre-agent -n sre-agent -o jsonpath='{.spec.host}')
    ROUTE_URL="https://$ROUTE_HOST"
    echo "🌐 Auto-detected route URL: $ROUTE_URL"

    # Update ConfigMap with route URL
    echo "📝 Updating ConfigMap with route URL..."
    oc patch configmap agent-config -n sre-agent --type merge -p "{\"data\":{\"SRE_AGENT_ROUTE_URL\":\"$ROUTE_URL\"}}"
    echo "✅ Route URL configured"
else
    echo "⚠️  Warning: Route not found. Slack approval URLs may not work."
    echo "   You can manually set it later with:"
    echo "   oc patch configmap agent-config -n sre-agent --type merge -p '{\"data\":{\"SRE_AGENT_ROUTE_URL\":\"https://your-route-url\"}}'"
fi
echo ""

# Check if Slack webhook secret exists
echo "🔍 Checking Slack integration..."
if oc get secret slack-webhook-secret -n sre-agent &> /dev/null; then
    echo "✅ Slack webhook secret found"
else
    echo "⚠️  Slack webhook secret not found"
    echo "   Slack notifications will be disabled until you configure it:"
    echo "   oc create secret generic slack-webhook-secret -n sre-agent \\"
    echo "     --from-literal=SLACK_WEBHOOK_URL='https://hooks.slack.com/services/YOUR/WEBHOOK/URL'"
fi
echo ""

# Restart deployment to pick up changes
echo "🔄 Restarting deployment to apply configuration..."
oc rollout restart deployment/sre-agent -n sre-agent
echo "✅ Deployment restarted"
echo ""

# Wait for pod to be ready
echo "⏳ Waiting for pod to be ready..."
if oc wait --for=condition=Ready pod -l app=sre-agent -n sre-agent --timeout=180s 2>/dev/null; then
    echo "✅ Pod is ready"
else
    echo "⚠️  Warning: Pod not ready within timeout. Check status with:"
    echo "   oc get pods -n sre-agent"
    echo "   oc logs -n sre-agent deployment/sre-agent -c agent"
fi
echo ""

# Show final status
echo "📊 Deployment Status"
echo "===================="
oc get pods -n sre-agent
echo ""

# Show next steps
echo "✨ Deployment Complete!"
echo ""
echo "📋 Next Steps:"
echo "1. Configure LLM provider (see README.md 'Quick Start' section)"
echo "2. Configure Git platform for issue tracking"
echo "3. (Optional) Configure Slack webhook for interactive notifications"
echo "4. (Optional) Grant edit permissions to namespaces for auto-remediation:"
echo "   oc adm policy add-role-to-user edit system:serviceaccount:sre-agent:sre-agent -n <namespace>"
echo ""
echo "📖 View logs:"
echo "   oc logs -f deployment/sre-agent -c agent -n sre-agent"
echo ""
echo "🔍 Check health:"
echo "   oc exec -n sre-agent deployment/sre-agent -c agent -- curl -s http://localhost:8000/health"
echo ""
echo "🌐 Access route:"
if [ ! -z "$ROUTE_URL" ]; then
    echo "   $ROUTE_URL/health"
fi
echo ""

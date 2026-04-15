#!/bin/bash
#
# Build and push SRE Agent container image
#

set -e

IMAGE_REGISTRY=${IMAGE_REGISTRY:-"quay.io"}
IMAGE_ORG=${IMAGE_ORG:-"sureshgaikwad"}
IMAGE_NAME="ocp-sre-agent"
IMAGE_TAG=${IMAGE_TAG:-"2.0.1"}

FULL_IMAGE="${IMAGE_REGISTRY}/${IMAGE_ORG}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building SRE Agent container image..."
echo "Image: ${FULL_IMAGE}"

# Get script directory and move to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "Project root: $PROJECT_ROOT"

# Build with podman or docker
if command -v podman &> /dev/null; then
    BUILDER="podman"
elif command -v docker &> /dev/null; then
    BUILDER="docker"
else
    echo "Error: Neither podman nor docker found"
    exit 1
fi

echo "Using builder: ${BUILDER}"

# Build image
${BUILDER} build -t ${FULL_IMAGE} -f Dockerfile .

echo ""
echo "Image built successfully!"
echo "To push to registry:"
echo "  ${BUILDER} login ${IMAGE_REGISTRY}"
echo "  ${BUILDER} push ${FULL_IMAGE}"
echo ""
echo "Or use internal OpenShift registry:"
echo "  oc new-build --name=sre-agent --binary --strategy=docker -n sre-agent"
echo "  oc start-build sre-agent --from-dir=. --follow -n sre-agent"

#!/bin/bash
#
# Build and push SRE Agent container image
#

set -e

IMAGE_REGISTRY=${IMAGE_REGISTRY:-"quay.io"}
IMAGE_ORG=${IMAGE_ORG:-"sureshgaikwad"}
IMAGE_NAME="ocp-sre-agent"
IMAGE_TAG=${IMAGE_TAG:-"2.1.0"}

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
echo "Building image: ${FULL_IMAGE}"
${BUILDER} build -t ${FULL_IMAGE} -f Dockerfile .

# Also tag as latest
LATEST_IMAGE="${IMAGE_REGISTRY}/${IMAGE_ORG}/${IMAGE_NAME}:latest"
echo "Tagging as: ${LATEST_IMAGE}"
${BUILDER} tag ${FULL_IMAGE} ${LATEST_IMAGE}

echo ""
echo "Image built successfully!"
echo ""

# Push to registry if --push flag is provided
if [ "$1" = "--push" ]; then
    echo "Pushing to registry..."
    echo "Image: ${FULL_IMAGE}"
    echo "Also pushing: ${LATEST_IMAGE}"
    echo ""

    # Check if logged in
    if ! ${BUILDER} login ${IMAGE_REGISTRY} --get-login &> /dev/null; then
        echo "Not logged in to ${IMAGE_REGISTRY}"
        echo "Logging in..."
        ${BUILDER} login ${IMAGE_REGISTRY}
    fi

    echo "Pushing ${FULL_IMAGE}..."
    ${BUILDER} push ${FULL_IMAGE}

    echo "Pushing ${LATEST_IMAGE}..."
    ${BUILDER} push ${LATEST_IMAGE}

    echo ""
    echo "✅ Images pushed successfully!"
    echo "  - ${FULL_IMAGE}"
    echo "  - ${LATEST_IMAGE}"
else
    echo "Images tagged locally. To push to registry:"
    echo "  ./deploy/build-and-push.sh --push"
    echo ""
    echo "Or manually:"
    echo "  ${BUILDER} login ${IMAGE_REGISTRY}"
    echo "  ${BUILDER} push ${FULL_IMAGE}"
    echo "  ${BUILDER} push ${LATEST_IMAGE}"
fi

echo ""
echo "Or use internal OpenShift registry:"
echo "  oc new-build --name=sre-agent --binary --strategy=docker -n sre-agent"
echo "  oc start-build sre-agent --from-dir=. --follow -n sre-agent"

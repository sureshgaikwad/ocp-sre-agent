# SRE Agent Container Image
# Using Red Hat Universal Base Image (UBI) 9 with Python 3.11
FROM registry.access.redhat.com/ubi9/python-311:latest

LABEL maintainer="SRE Team" \
      description="OpenShift SRE Agent - Autonomous monitoring and remediation" \
      version="2.1.0" \
      io.k8s.description="Autonomous SRE agent for OpenShift cluster monitoring and remediation" \
      io.k8s.display-name="OpenShift SRE Agent" \
      io.openshift.tags="openshift,sre,monitoring,remediation,multi-git,learning"

# Switch to root for installations
USER 0

# Install system dependencies using dnf
# Note: git, sqlite, tar, gzip are already in base image
# Use --allowerasing for curl to replace curl-minimal
RUN dnf install -y --allowerasing curl && dnf clean all

# Note: oc CLI not installed - agent uses MCP tools for OpenShift interaction
# If needed in future, use architecture-specific download:
# aarch64: https://mirror.openshift.com/pub/openshift-v4/aarch64/clients/ocp/stable/openshift-client-linux.tar.gz
# x86_64: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz

# Set working directory
WORKDIR /opt/app-root/src

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY sre_agent/ ./sre_agent/
COPY mcp_client.py .
COPY main.py .

# Create data directory for databases
RUN mkdir -p /data && \
    chmod 775 /data && \
    chown -R 1001:0 /data /opt/app-root/src

# Switch to non-root user (default UBI user)
USER 1001

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Run application
CMD ["python", "main.py"]

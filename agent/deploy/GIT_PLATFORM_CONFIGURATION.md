# Git Platform Configuration Guide

The SRE Agent supports **GitHub**, **GitLab**, and **Gitea** for creating issues and pull requests.

This guide shows you how to configure each platform.

---

## 🎯 Quick Start

### 1. Choose Your Platform

The agent can create issues and PRs in:
- ✅ **GitHub** (github.com or GitHub Enterprise)
- ✅ **GitLab** (gitlab.com or self-hosted)
- ✅ **Gitea** (self-hosted)

### 2. Create a Repository

Create a dedicated repository for cluster issues:
- GitHub: `https://github.com/my-org/cluster-issues`
- GitLab: `https://gitlab.com/my-group/cluster-issues`
- Gitea: `https://gitea.company.com/my-org/cluster-issues`

### 3. Generate Access Token

See platform-specific instructions below.

### 4. Update Configuration

Edit the deployment ConfigMap and Secret (see examples below).

---

## 📘 GitHub Configuration

### Step 1: Create GitHub Repository

```bash
# Via GitHub CLI
gh repo create my-org/cluster-issues --public

# Or via web UI: https://github.com/new
```

### Step 2: Generate Personal Access Token (PAT)

**For Personal Accounts**:
1. Go to https://github.com/settings/tokens
2. Click "Generate new token" → "Fine-grained token" (recommended)
3. Configure:
   - **Token name**: `sre-agent-token`
   - **Expiration**: 90 days (or custom)
   - **Repository access**: Only select repositories → `cluster-issues`
   - **Permissions**:
     - Issues: **Read and write**
     - Pull requests: **Read and write**
     - Contents: **Read and write** (for PR file changes)
4. Click "Generate token"
5. **Copy the token** (starts with `ghp_`)

**For Organizations**:
1. Go to Organization Settings → Developer settings → Personal access tokens
2. Follow same steps as above
3. Grant organization access

**Classic Token** (alternative):
1. Go to https://github.com/settings/tokens
2. Generate new token (classic)
3. Select scopes: `repo` (full control of private repositories)
4. Copy token

### Step 3: Update Deployment Configuration

**ConfigMap** (`agent-config`):
```yaml
# Edit ConfigMap
oc edit configmap agent-config -n sre-agent

# Set:
GIT_PLATFORM: "github"
GIT_SERVER_URL: "https://github.com"  # Or https://github.company.com for Enterprise
GIT_ORGANIZATION: "my-org"  # Your GitHub organization or username
GIT_REPOSITORY: "cluster-issues"
GIT_DEFAULT_BRANCH: "main"
```

**Secret** (`git-api-secret`):
```bash
# Create or update secret
oc create secret generic git-api-secret \
  --from-literal=GIT_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx" \
  -n sre-agent --dry-run=client -o yaml | oc apply -f -

# Restart agent to pick up changes
oc rollout restart deployment/sre-agent -n sre-agent
```

### Step 4: Verify

```bash
# Check logs
oc logs deployment/sre-agent -n sre-agent -c agent | grep "GitHub"

# Expected: "Tier 3 handler initialized with github integration"
```

---

## 🦊 GitLab Configuration

### Step 1: Create GitLab Project

```bash
# Via GitLab CLI (glab)
glab repo create cluster-issues --public

# Or via web UI: https://gitlab.com/projects/new
```

### Step 2: Generate Personal Access Token

**For gitlab.com or Self-Hosted**:
1. Go to User Settings → Access Tokens
   - gitlab.com: https://gitlab.com/-/profile/personal_access_tokens
   - Self-hosted: `https://gitlab.company.com/-/profile/personal_access_tokens`
2. Configure:
   - **Token name**: `sre-agent-token`
   - **Expiration**: Set appropriate date
   - **Scopes**:
     - ✅ `api` (full API access)
3. Click "Create personal access token"
4. **Copy the token** (starts with `glpat-`)

**For Groups/Projects**:
1. Go to Group/Project Settings → Access Tokens
2. Create project access token with `api` scope

### Step 3: Update Deployment Configuration

**ConfigMap**:
```yaml
# Edit ConfigMap
oc edit configmap agent-config -n sre-agent

# Set:
GIT_PLATFORM: "gitlab"
GIT_SERVER_URL: "https://gitlab.com"  # Or https://gitlab.company.com for self-hosted
GIT_ORGANIZATION: "my-group"  # Your GitLab group or username
GIT_REPOSITORY: "cluster-issues"
GIT_DEFAULT_BRANCH: "main"
```

**Secret**:
```bash
# Create or update secret
oc create secret generic git-api-secret \
  --from-literal=GIT_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx" \
  -n sre-agent --dry-run=client -o yaml | oc apply -f -

# Restart agent
oc rollout restart deployment/sre-agent -n sre-agent
```

### Step 4: Verify

```bash
# Check logs
oc logs deployment/sre-agent -n sre-agent -c agent | grep "GitLab"

# Expected: "Tier 3 handler initialized with gitlab integration"
```

---

## 🌿 Gitea Configuration

### Step 1: Create Gitea Repository

Via Gitea web UI: `https://gitea.company.com/repo/create`

### Step 2: Generate API Token

1. Go to User Settings → Applications
   - `https://gitea.company.com/user/settings/applications`
2. Generate New Token:
   - **Token Name**: `sre-agent-token`
   - **Permissions**: Select all (or minimum: issue, repository)
3. Click "Generate Token"
4. **Copy the token**

### Step 3: Update Deployment Configuration

**ConfigMap**:
```yaml
# Edit ConfigMap
oc edit configmap agent-config -n sre-agent

# Set:
GIT_PLATFORM: "gitea"
GIT_SERVER_URL: "https://gitea.company.com"
GIT_ORGANIZATION: "my-org"  # Your Gitea organization or username
GIT_REPOSITORY: "cluster-issues"
GIT_DEFAULT_BRANCH: "main"
```

**Secret**:
```bash
# Create or update secret
oc create secret generic git-api-secret \
  --from-literal=GIT_TOKEN="your-gitea-token" \
  -n sre-agent --dry-run=client -o yaml | oc apply -f -

# Restart agent
oc rollout restart deployment/sre-agent -n sre-agent
```

**Note**: Gitea uses the MCP protocol, so ensure MCP Gitea server is configured.

---

## 🧪 Testing

### Test Issue Creation (Tier 3)

Create a test pod with invalid image:
```bash
oc run test-invalid --image=nginx:nonexistent-tag -n sre-agent

# Wait 2-3 minutes
sleep 180

# Check agent logs
oc logs deployment/sre-agent -n sre-agent -c agent | grep "Issue created"

# Expected output:
# "Issue created in github: #123"
# "url": "https://github.com/my-org/cluster-issues/issues/123"
```

### Verify Issue in Git Platform

**GitHub**:
```bash
# Via CLI
gh issue list --repo my-org/cluster-issues

# Via web
open https://github.com/my-org/cluster-issues/issues
```

**GitLab**:
```bash
# Via CLI
glab issue list --repo my-group/cluster-issues

# Via web
open https://gitlab.com/my-group/cluster-issues/-/issues
```

**Gitea**:
```bash
# Via web
open https://gitea.company.com/my-org/cluster-issues/issues
```

---

## 🔍 Troubleshooting

### Issue: "Failed to create issue: 401 Unauthorized"

**Cause**: Invalid or expired token

**Fix**:
```bash
# Regenerate token from Git platform
# Update secret
oc create secret generic git-api-secret \
  --from-literal=GIT_TOKEN="new-token" \
  -n sre-agent --dry-run=client -o yaml | oc apply -f -

oc rollout restart deployment/sre-agent -n sre-agent
```

### Issue: "Failed to create issue: 403 Forbidden"

**Cause**: Token doesn't have required permissions

**Fix**:
- **GitHub**: Token needs `repo` scope (or `public_repo` for public repos)
- **GitLab**: Token needs `api` scope
- **Gitea**: Token needs issue and repository permissions

### Issue: "Failed to create issue: 404 Not Found"

**Cause**: Repository doesn't exist or wrong organization/repo name

**Fix**:
```bash
# Verify repository exists
# GitHub
gh repo view my-org/cluster-issues

# GitLab
glab repo view my-group/cluster-issues

# Update ConfigMap with correct org/repo
oc edit configmap agent-config -n sre-agent
```

### Issue: "ValueError: organization parameter is required"

**Cause**: `GIT_ORGANIZATION` not set in ConfigMap

**Fix**:
```bash
oc edit configmap agent-config -n sre-agent
# Add: GIT_ORGANIZATION: "my-org"

oc rollout restart deployment/sre-agent -n sre-agent
```

---

## 🔐 Security Best Practices

### Token Security

1. **Use Fine-Grained Tokens** (GitHub):
   - Limit to specific repositories
   - Set expiration dates
   - Use minimum required permissions

2. **Rotate Tokens Regularly**:
   - Set 90-day expiration
   - Automate rotation with external secrets operator

3. **Never Commit Tokens**:
   - ✅ Use Kubernetes Secrets
   - ❌ Never put tokens in ConfigMaps
   - ❌ Never commit to Git

### Least Privilege

**Minimum permissions needed**:
- **Issues**: Read and write
- **Pull Requests**: Read and write (for Tier 2)
- **Contents**: Read and write (for Tier 2 file changes)

Don't grant admin or delete permissions.

---

## 📊 Multi-Platform Support Summary

| Feature | GitHub | GitLab | Gitea |
|---------|--------|--------|-------|
| **Issue Creation** | ✅ | ✅ | ✅ |
| **PR/MR Creation** | ✅ | ✅ | ✅ |
| **File Modification** | ✅ | ✅ | ✅ |
| **Branch Creation** | ✅ | ✅ | ✅ |
| **Public Cloud** | github.com | gitlab.com | N/A |
| **Self-Hosted** | GitHub Enterprise | GitLab CE/EE | Gitea |
| **API Authentication** | PAT/Fine-grained | PAT/Project token | API Token |
| **Implementation** | REST API v3 | REST API v4 | MCP Tools |

---

## 🎓 Examples

### Example 1: GitHub Enterprise

```yaml
# ConfigMap
GIT_PLATFORM: "github"
GIT_SERVER_URL: "https://github.company.com"
GIT_ORGANIZATION: "platform-team"
GIT_REPOSITORY: "openshift-issues"
GIT_DEFAULT_BRANCH: "main"

# Secret
GIT_TOKEN: "ghp_xxxxxxxxxxxxxxxxxxxx"
```

### Example 2: Self-Hosted GitLab

```yaml
# ConfigMap
GIT_PLATFORM: "gitlab"
GIT_SERVER_URL: "https://gitlab.company.com"
GIT_ORGANIZATION: "sre-team"
GIT_REPOSITORY: "cluster-incidents"
GIT_DEFAULT_BRANCH: "main"

# Secret
GIT_TOKEN: "glpat-xxxxxxxxxxxxxxxxxxxx"
```

### Example 3: Public GitHub

```yaml
# ConfigMap
GIT_PLATFORM: "github"
GIT_SERVER_URL: "https://github.com"
GIT_ORGANIZATION: "my-username"
GIT_REPOSITORY: "cluster-issues"
GIT_DEFAULT_BRANCH: "main"

# Secret
GIT_TOKEN: "ghp_xxxxxxxxxxxxxxxxxxxx"
```

---

## ✅ Verification Checklist

After configuration, verify:

- [ ] ConfigMap has correct `GIT_PLATFORM` value
- [ ] ConfigMap has correct `GIT_SERVER_URL`
- [ ] ConfigMap has correct `GIT_ORGANIZATION` and `GIT_REPOSITORY`
- [ ] Secret `git-api-secret` contains valid `GIT_TOKEN`
- [ ] Agent pod restarted after changes
- [ ] Agent logs show platform initialization (check for "initialized with {platform} integration")
- [ ] Test issue creation works
- [ ] Issue appears in Git platform repository
- [ ] Issue has correct labels and formatting

---

**Version**: 2.0.2
**Last Updated**: 2026-04-14

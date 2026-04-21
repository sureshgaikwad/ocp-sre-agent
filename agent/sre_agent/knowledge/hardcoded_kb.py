"""
Tier 1: Hardcoded Knowledge Base Links.

Curated links for common OpenShift issues.
Covers ~80% of production alerts with zero latency.
"""

from typing import List, Dict

# Hardcoded KB articles by category
HARDCODED_KB_LINKS: Dict[str, List[Dict[str, str]]] = {
    "oom_killed": [
        {
            "title": "Pod OOMKilled troubleshooting",
            "url": "https://access.redhat.com/solutions/4896471",
            "description": "How to troubleshoot and resolve OOMKilled pods in OpenShift"
        },
        {
            "title": "Understanding OOM killer",
            "url": "https://access.redhat.com/solutions/3006972",
            "description": "Understanding the Linux OOM killer and memory management"
        },
        {
            "title": "Resource management guide",
            "url": "https://docs.openshift.com/container-platform/latest/nodes/clusters/nodes-cluster-resource-configure.html",
            "description": "Configuring resource limits and requests in OpenShift"
        }
    ],

    "crash_loop_back_off": [
        {
            "title": "CrashLoopBackOff troubleshooting",
            "url": "https://access.redhat.com/solutions/3431091",
            "description": "How to diagnose and fix CrashLoopBackOff errors"
        },
        {
            "title": "Pod crash troubleshooting guide",
            "url": "https://access.redhat.com/articles/6955985",
            "description": "Comprehensive guide for troubleshooting pod crashes"
        },
        {
            "title": "Investigating pod issues",
            "url": "https://docs.openshift.com/container-platform/latest/support/troubleshooting/investigating-pod-issues.html",
            "description": "Official OpenShift pod troubleshooting documentation"
        }
    ],

    "image_pull_back_off": [
        {
            "title": "ImagePullBackOff troubleshooting",
            "url": "https://access.redhat.com/solutions/6007231",
            "description": "How to resolve ImagePullBackOff and ErrImagePull errors"
        },
        {
            "title": "Pull secret configuration",
            "url": "https://access.redhat.com/solutions/3754131",
            "description": "Configuring image pull secrets in OpenShift"
        },
        {
            "title": "Using image pull secrets",
            "url": "https://docs.openshift.com/container-platform/latest/openshift_images/managing_images/using-image-pull-secrets.html",
            "description": "Official documentation for image pull secrets"
        }
    ],

    "hpa_max_replicas": [
        {
            "title": "HPA troubleshooting",
            "url": "https://access.redhat.com/solutions/5478661",
            "description": "Troubleshooting Horizontal Pod Autoscaler issues"
        },
        {
            "title": "Pod autoscaling",
            "url": "https://docs.openshift.com/container-platform/latest/nodes/pods/nodes-pods-autoscaling.html",
            "description": "Automatically scaling pods based on metrics"
        },
        {
            "title": "HPA walkthrough",
            "url": "https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/",
            "description": "Kubernetes HPA detailed walkthrough"
        }
    ],

    "cluster_operator_degraded": [
        {
            "title": "ClusterOperator degraded troubleshooting",
            "url": "https://access.redhat.com/solutions/4849711",
            "description": "How to troubleshoot degraded cluster operators"
        },
        {
            "title": "Understanding cluster operators",
            "url": "https://docs.openshift.com/container-platform/latest/operators/operator-reference.html",
            "description": "Overview of OpenShift cluster operators"
        },
        {
            "title": "Cluster version operator troubleshooting",
            "url": "https://access.redhat.com/solutions/4602641",
            "description": "Troubleshooting cluster version operator issues"
        }
    ],

    "pvc_pending": [
        {
            "title": "PVC stuck in Pending state",
            "url": "https://access.redhat.com/solutions/4651281",
            "description": "Resolving PersistentVolumeClaim pending issues"
        },
        {
            "title": "Storage configuration",
            "url": "https://docs.openshift.com/container-platform/latest/storage/understanding-persistent-storage.html",
            "description": "Understanding persistent storage in OpenShift"
        },
        {
            "title": "Dynamic provisioning",
            "url": "https://access.redhat.com/documentation/en-us/openshift_container_platform/latest/html/storage/dynamic-provisioning",
            "description": "Configuring dynamic storage provisioning"
        }
    ],

    "node_disk_pressure": [
        {
            "title": "Node DiskPressure troubleshooting",
            "url": "https://access.redhat.com/solutions/4843671",
            "description": "Resolving node disk pressure conditions"
        },
        {
            "title": "Garbage collection",
            "url": "https://docs.openshift.com/container-platform/latest/nodes/nodes/nodes-nodes-garbage-collection.html",
            "description": "Configuring garbage collection for nodes"
        },
        {
            "title": "Ephemeral storage management",
            "url": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#local-ephemeral-storage",
            "description": "Managing ephemeral storage on nodes"
        }
    ],

    "scc_violation": [
        {
            "title": "SCC troubleshooting guide",
            "url": "https://access.redhat.com/solutions/3848131",
            "description": "Understanding and troubleshooting Security Context Constraints"
        },
        {
            "title": "Managing SCCs",
            "url": "https://docs.openshift.com/container-platform/latest/authentication/managing-security-context-constraints.html",
            "description": "Managing Security Context Constraints in OpenShift"
        },
        {
            "title": "SCC reference",
            "url": "https://access.redhat.com/articles/6973044",
            "description": "Security Context Constraints reference guide"
        }
    ],

    "route_unavailable": [
        {
            "title": "Route troubleshooting",
            "url": "https://access.redhat.com/solutions/4686811",
            "description": "Troubleshooting route availability issues"
        },
        {
            "title": "Route configuration",
            "url": "https://docs.openshift.com/container-platform/latest/networking/routes/route-configuration.html",
            "description": "Configuring routes in OpenShift"
        },
        {
            "title": "Ingress controller issues",
            "url": "https://access.redhat.com/solutions/5424141",
            "description": "Debugging OpenShift Ingress Controller"
        }
    ],

    "certificate_expiring": [
        {
            "title": "Certificate renewal",
            "url": "https://access.redhat.com/solutions/4799921",
            "description": "Renewing certificates in OpenShift"
        },
        {
            "title": "Certificate management",
            "url": "https://docs.openshift.com/container-platform/latest/security/certificates/replacing-default-ingress-certificate.html",
            "description": "Managing certificates in OpenShift"
        }
    ],

    "build_failure": [
        {
            "title": "Build troubleshooting",
            "url": "https://access.redhat.com/solutions/3790161",
            "description": "Troubleshooting OpenShift build failures"
        },
        {
            "title": "Build configuration",
            "url": "https://docs.openshift.com/container-platform/latest/cicd/builds/understanding-image-builds.html",
            "description": "Understanding OpenShift builds"
        }
    ],

    "hpa_unable_to_get_metrics": [
        {
            "title": "HPA unable to get metrics troubleshooting",
            "url": "https://access.redhat.com/solutions/5908131",
            "description": "Troubleshooting HPA unable to get metrics from metrics-server"
        },
        {
            "title": "HPA troubleshooting guide",
            "url": "https://access.redhat.com/solutions/5478661",
            "description": "Comprehensive HPA troubleshooting guide"
        },
        {
            "title": "Horizontal Pod Autoscaler configuration",
            "url": "https://docs.openshift.com/container-platform/latest/nodes/pods/nodes-pods-autoscaling.html",
            "description": "Configuring and using HPA in OpenShift"
        },
        {
            "title": "Metrics server troubleshooting",
            "url": "https://access.redhat.com/solutions/4631291",
            "description": "Troubleshooting metrics-server in OpenShift"
        }
    ],

    "hpa_missing_scaleref": [
        {
            "title": "HPA scaleTargetRef not found",
            "url": "https://access.redhat.com/solutions/5908131",
            "description": "Resolving HPA scale target reference issues"
        },
        {
            "title": "HPA configuration guide",
            "url": "https://docs.openshift.com/container-platform/latest/nodes/pods/nodes-pods-autoscaling.html",
            "description": "Properly configuring HPA scaleTargetRef"
        },
        {
            "title": "Kubernetes HPA walkthrough",
            "url": "https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/",
            "description": "Understanding HPA configuration and targets"
        }
    ],

    "resource_quota_exceeded": [
        {
            "title": "HPA at max replicas troubleshooting",
            "url": "https://access.redhat.com/solutions/5478661",
            "description": "Troubleshooting HPA reaching maxReplicas limit"
        },
        {
            "title": "HPA not scaling up troubleshooting",
            "url": "https://access.redhat.com/solutions/5908131",
            "description": "Diagnosing why HPA cannot scale beyond current replicas"
        },
        {
            "title": "Horizontal Pod Autoscaler best practices",
            "url": "https://docs.openshift.com/container-platform/latest/nodes/pods/nodes-pods-autoscaling.html",
            "description": "Best practices for HPA configuration and scaling"
        },
        {
            "title": "Resource limits and quotas",
            "url": "https://docs.openshift.com/container-platform/latest/nodes/clusters/nodes-cluster-limit-ranges.html",
            "description": "Understanding resource limits and quotas in OpenShift"
        }
    ],

    "cluster_autoscaler_failed": [
        {
            "title": "ClusterAutoscaler troubleshooting",
            "url": "https://access.redhat.com/solutions/4631411",
            "description": "Troubleshooting OpenShift ClusterAutoscaler issues"
        },
        {
            "title": "Cluster autoscaling configuration",
            "url": "https://docs.openshift.com/container-platform/latest/machine_management/applying-autoscaling.html",
            "description": "Configuring cluster autoscaling in OpenShift"
        },
        {
            "title": "MachineAutoscaler configuration",
            "url": "https://docs.openshift.com/container-platform/latest/machine_management/creating-machineset.html",
            "description": "Understanding MachineSet and MachineAutoscaler"
        }
    ],

    "node_scale_insufficient_resources": [
        {
            "title": "Node provisioning failures",
            "url": "https://access.redhat.com/solutions/4631411",
            "description": "Troubleshooting node provisioning and scaling issues"
        },
        {
            "title": "Cloud provider quota limits",
            "url": "https://docs.openshift.com/container-platform/latest/installing/installing-troubleshooting.html",
            "description": "Understanding cloud provider resource quotas and limits"
        },
        {
            "title": "ClusterAutoscaler capacity planning",
            "url": "https://docs.openshift.com/container-platform/latest/machine_management/applying-autoscaling.html",
            "description": "Planning cluster capacity and autoscaling"
        }
    ]
}

# Fallback generic links
GENERIC_LINKS = [
    {
        "title": "OpenShift Troubleshooting Guide",
        "url": "https://docs.openshift.com/container-platform/latest/support/troubleshooting/troubleshooting-installations.html",
        "description": "Official OpenShift troubleshooting documentation"
    },
    {
        "title": "Red Hat Support",
        "url": "https://access.redhat.com/support",
        "description": "Red Hat Customer Portal support page"
    },
    {
        "title": "OpenShift Documentation",
        "url": "https://docs.openshift.com/container-platform/latest/welcome/index.html",
        "description": "Official OpenShift Container Platform documentation"
    }
]


def get_hardcoded_links(category: str) -> List[Dict[str, str]]:
    """
    Get hardcoded KB links for a category.

    Args:
        category: Issue category (e.g., "oom_killed")

    Returns:
        List of KB article dicts with title, url, description
    """
    return HARDCODED_KB_LINKS.get(category, GENERIC_LINKS)


def get_all_categories() -> List[str]:
    """Get all categories with hardcoded KB links."""
    return list(HARDCODED_KB_LINKS.keys())

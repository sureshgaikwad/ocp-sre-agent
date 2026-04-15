"""
🔴 SECURITY CRITICAL MODULE 🔴

Secret scrubbing utility to prevent sensitive data leakage in logs, LLM prompts,
and external systems. This module MUST be used before:
- Sending logs to LLM for analysis
- Writing to audit logs
- Creating issues in Gitea/GitHub
- Any external communication

Defense in depth: Multiple regex patterns with high recall to catch secrets.
"""

import re
from typing import Pattern
from enum import Enum


class SecretType(Enum):
    """Types of secrets detected and scrubbed."""
    PASSWORD = "password"
    API_KEY = "api_key"
    TOKEN = "token"
    SSH_KEY = "ssh_key"
    CERTIFICATE = "certificate"
    BASE64_SECRET = "base64_secret"
    AWS_KEY = "aws_key"
    BEARER_TOKEN = "bearer_token"
    DATABASE_URL = "database_url"
    PRIVATE_KEY = "private_key"


class SecretPattern:
    """Container for secret detection patterns."""

    def __init__(self, pattern: str, secret_type: SecretType, description: str):
        self.pattern: Pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        self.secret_type = secret_type
        self.description = description


# Comprehensive list of secret patterns
SECRET_PATTERNS = [
    # Passwords in various formats
    SecretPattern(
        r'(?:password|passwd|pwd)[\s]*[:=][\s]*["\']?([^\s"\']{3,})["\']?',
        SecretType.PASSWORD,
        "Password in key=value format"
    ),
    SecretPattern(
        r'--password[=\s]+["\']?([^\s"\']{3,})["\']?',
        SecretType.PASSWORD,
        "Password as CLI flag"
    ),
    SecretPattern(
        r'MYSQL_PASSWORD[\s]*[:=][\s]*["\']?([^\s"\']{3,})["\']?',
        SecretType.PASSWORD,
        "MySQL password environment variable"
    ),
    SecretPattern(
        r'POSTGRES_PASSWORD[\s]*[:=][\s]*["\']?([^\s"\']{3,})["\']?',
        SecretType.PASSWORD,
        "PostgreSQL password environment variable"
    ),

    # API Keys and Tokens
    SecretPattern(
        r'(?:api[_-]?key|apikey)[\s]*[:=][\s]*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
        SecretType.API_KEY,
        "API key in key=value format"
    ),
    SecretPattern(
        r'(?:access[_-]?token|accesstoken)[\s]*[:=][\s]*["\']?([a-zA-Z0-9_\-\.]{20,})["\']?',
        SecretType.TOKEN,
        "Access token"
    ),
    SecretPattern(
        r'(?:secret[_-]?key|secretkey)[\s]*[:=][\s]*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
        SecretType.API_KEY,
        "Secret key"
    ),
    SecretPattern(
        r'Authorization:\s*Bearer\s+([a-zA-Z0-9_\-\.]{20,})',
        SecretType.BEARER_TOKEN,
        "Bearer token in Authorization header"
    ),

    # AWS Keys
    SecretPattern(
        r'(?:AKIA|A3T|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}',
        SecretType.AWS_KEY,
        "AWS Access Key ID"
    ),
    SecretPattern(
        r'aws_secret_access_key[\s]*[:=][\s]*["\']?([a-zA-Z0-9/+=]{40})["\']?',
        SecretType.AWS_KEY,
        "AWS Secret Access Key"
    ),

    # SSH Private Keys
    SecretPattern(
        r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----',
        SecretType.SSH_KEY,
        "SSH/RSA private key (PEM format)"
    ),
    SecretPattern(
        r'-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----[\s\S]*?-----END\s+OPENSSH\s+PRIVATE\s+KEY-----',
        SecretType.SSH_KEY,
        "OpenSSH private key"
    ),
    SecretPattern(
        r'-----BEGIN\s+EC\s+PRIVATE\s+KEY-----[\s\S]*?-----END\s+EC\s+PRIVATE\s+KEY-----',
        SecretType.SSH_KEY,
        "EC private key"
    ),
    SecretPattern(
        r'-----BEGIN\s+DSA\s+PRIVATE\s+KEY-----[\s\S]*?-----END\s+DSA\s+PRIVATE\s+KEY-----',
        SecretType.SSH_KEY,
        "DSA private key"
    ),

    # Certificates
    SecretPattern(
        r'-----BEGIN\s+CERTIFICATE-----[\s\S]*?-----END\s+CERTIFICATE-----',
        SecretType.CERTIFICATE,
        "X.509 Certificate"
    ),

    # Database Connection Strings
    SecretPattern(
        r'(?:mysql|postgresql|mongodb|redis)://[^:]+:([^@]+)@',
        SecretType.DATABASE_URL,
        "Database connection string with password"
    ),

    # GitHub/GitLab tokens
    SecretPattern(
        r'gh[pousr]_[A-Za-z0-9_]{36,}',
        SecretType.TOKEN,
        "GitHub personal access token"
    ),
    SecretPattern(
        r'glpat-[A-Za-z0-9_\-]{20,}',
        SecretType.TOKEN,
        "GitLab personal access token"
    ),

    # Generic base64 secrets (in YAML/JSON data fields)
    SecretPattern(
        r'(?:token|secret|key|password|credential)[\s]*[:=][\s]*["\']?([A-Za-z0-9+/]{40,}={0,2})["\']?',
        SecretType.BASE64_SECRET,
        "Base64-encoded secret"
    ),

    # Kubernetes secrets (base64 encoded values in YAML)
    SecretPattern(
        r'data:\s*\n\s+[a-zA-Z0-9_-]+:\s+([A-Za-z0-9+/]{20,}={0,2})',
        SecretType.BASE64_SECRET,
        "Kubernetes Secret data field"
    ),

    # JWT tokens
    SecretPattern(
        r'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*',
        SecretType.TOKEN,
        "JWT token"
    ),

    # OpenShift/Kubernetes service account tokens
    SecretPattern(
        r'(?:serviceaccount|sa)[_-]?token[\s]*[:=][\s]*["\']?([a-zA-Z0-9_\-\.]{100,})["\']?',
        SecretType.TOKEN,
        "Service account token"
    ),

    # Private keys in environment variables
    SecretPattern(
        r'PRIVATE[_-]KEY[\s]*[:=][\s]*["\']?([a-zA-Z0-9/+=]{40,})["\']?',
        SecretType.PRIVATE_KEY,
        "Private key in environment variable"
    ),
]


class SecretScrubber:
    """
    Main secret scrubbing class.

    Thread-safe and can be used as a singleton or instantiated per-use.
    """

    REDACTION_TEXT = "***REDACTED***"
    REDACTION_WITH_TYPE = "***REDACTED-{type}***"

    @classmethod
    def scrub(cls, text: str, show_type: bool = False) -> str:
        """
        Scrub secrets from text.

        Args:
            text: Input text that may contain secrets
            show_type: If True, include secret type in redaction (e.g., ***REDACTED-PASSWORD***)

        Returns:
            Text with all secrets replaced by redaction markers

        Example:
            >>> text = "password: myS3cret123"
            >>> SecretScrubber.scrub(text)
            'password: ***REDACTED***'
        """
        if not text:
            return text

        scrubbed = text

        for pattern in SECRET_PATTERNS:
            if show_type:
                replacement = cls.REDACTION_WITH_TYPE.format(type=pattern.secret_type.value.upper())
            else:
                replacement = cls.REDACTION_TEXT

            # Replace the matched secret, preserving context
            # Use a function to handle group-based replacements
            def replace_secret(match):
                # If the pattern has groups (parentheses), replace the captured group
                if match.groups():
                    # Replace each captured group with redaction
                    result = match.group(0)
                    for i, group in enumerate(match.groups(), 1):
                        if group:
                            result = result.replace(group, replacement)
                    return result
                else:
                    # No groups, replace entire match
                    return replacement

            scrubbed = pattern.pattern.sub(replace_secret, scrubbed)

        return scrubbed

    @classmethod
    def scrub_dict(cls, data: dict, show_type: bool = False) -> dict:
        """
        Recursively scrub secrets from dictionary values.

        Args:
            data: Dictionary that may contain secrets in values
            show_type: If True, include secret type in redaction

        Returns:
            New dictionary with scrubbed values
        """
        if not isinstance(data, dict):
            return data

        scrubbed = {}
        for key, value in data.items():
            if isinstance(value, str):
                scrubbed[key] = cls.scrub(value, show_type)
            elif isinstance(value, dict):
                scrubbed[key] = cls.scrub_dict(value, show_type)
            elif isinstance(value, list):
                scrubbed[key] = [
                    cls.scrub(item, show_type) if isinstance(item, str)
                    else cls.scrub_dict(item, show_type) if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                scrubbed[key] = value

        return scrubbed

    @classmethod
    def has_secrets(cls, text: str) -> bool:
        """
        Check if text contains any secrets without modifying it.

        Args:
            text: Text to check

        Returns:
            True if secrets are detected, False otherwise
        """
        if not text:
            return False

        for pattern in SECRET_PATTERNS:
            if pattern.pattern.search(text):
                return True

        return False

    @classmethod
    def get_secret_types(cls, text: str) -> set[SecretType]:
        """
        Identify which types of secrets are present in text.

        Args:
            text: Text to analyze

        Returns:
            Set of SecretType enums found in text
        """
        if not text:
            return set()

        found_types = set()
        for pattern in SECRET_PATTERNS:
            if pattern.pattern.search(text):
                found_types.add(pattern.secret_type)

        return found_types


# Convenience function for quick scrubbing
def scrub_secrets(text: str, show_type: bool = False) -> str:
    """
    Convenience function to scrub secrets from text.

    This is a shorthand for SecretScrubber.scrub()
    """
    return SecretScrubber.scrub(text, show_type)


if __name__ == "__main__":
    # Demo/testing
    test_cases = [
        "password: myS3cret123",
        "API_KEY=sk-1234567890abcdefghijklmnopqrstuvwxyz",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123",
        "mysql://user:p@ssw0rd@localhost/db",
        "AKIA1234567890ABCDEF",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----",
    ]

    print("Secret Scrubber Demo\n" + "="*60)
    for test in test_cases:
        scrubbed = SecretScrubber.scrub(test, show_type=True)
        print(f"Original: {test[:50]}...")
        print(f"Scrubbed: {scrubbed}")
        print(f"Detected: {SecretScrubber.get_secret_types(test)}")
        print("-" * 60)

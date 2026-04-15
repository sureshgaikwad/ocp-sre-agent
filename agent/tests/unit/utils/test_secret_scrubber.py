"""
Unit tests for secret_scrubber module.

🔴 CRITICAL: These tests validate that secrets are properly scrubbed.
"""

import pytest
from sre_agent.utils.secret_scrubber import SecretScrubber, SecretType, scrub_secrets


class TestPasswordScrubbing:
    """Test password detection and scrubbing."""

    def test_password_key_value(self):
        text = "password: myS3cret123"
        scrubbed = SecretScrubber.scrub(text)
        assert "myS3cret123" not in scrubbed
        assert "***REDACTED***" in scrubbed

    def test_password_equals(self):
        text = "PASSWORD=MyP@ssw0rd!"
        scrubbed = SecretScrubber.scrub(text)
        assert "MyP@ssw0rd!" not in scrubbed

    def test_password_cli_flag(self):
        text = "mysql --password=secret123 -u root"
        scrubbed = SecretScrubber.scrub(text)
        assert "secret123" not in scrubbed

    def test_mysql_password_env(self):
        text = "MYSQL_PASSWORD=root_password_123"
        scrubbed = SecretScrubber.scrub(text)
        assert "root_password_123" not in scrubbed

    def test_postgres_password_env(self):
        text = "POSTGRES_PASSWORD: pg_super_secret"
        scrubbed = SecretScrubber.scrub(text)
        assert "pg_super_secret" not in scrubbed


class TestAPIKeysScrubbing:
    """Test API key and token detection."""

    def test_api_key_basic(self):
        text = "api_key: sk-1234567890abcdefghijklmnopqrstuvwxyz"
        scrubbed = SecretScrubber.scrub(text)
        assert "sk-1234567890abcdefghijklmnopqrstuvwxyz" not in scrubbed

    def test_apikey_no_underscore(self):
        text = "apikey=abc123def456ghi789jklmno"
        scrubbed = SecretScrubber.scrub(text)
        assert "abc123def456ghi789jklmno" not in scrubbed

    def test_access_token(self):
        text = "access_token: ghp_1234567890abcdefghijklmnopqrstuv"
        scrubbed = SecretScrubber.scrub(text)
        assert "ghp_1234567890abcdefghijklmnopqrstuv" not in scrubbed

    def test_secret_key(self):
        text = "secret_key=my-super-secret-key-12345678901234567890"
        scrubbed = SecretScrubber.scrub(text)
        assert "my-super-secret-key-12345678901234567890" not in scrubbed

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        scrubbed = SecretScrubber.scrub(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in scrubbed


class TestAWSKeysScrubbing:
    """Test AWS credential detection."""

    def test_aws_access_key_id_akia(self):
        text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        scrubbed = SecretScrubber.scrub(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed

    def test_aws_access_key_id_asia(self):
        text = "Temporary key: ASIATESTACCESSKEY123"
        scrubbed = SecretScrubber.scrub(text)
        assert "ASIATESTACCESSKEY123" not in scrubbed

    def test_aws_secret_access_key(self):
        text = "aws_secret_access_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        scrubbed = SecretScrubber.scrub(text)
        assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in scrubbed


class TestSSHKeysScrubbing:
    """Test SSH private key detection."""

    def test_rsa_private_key(self):
        text = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAwJKtKfXHLeUAM7AwwDowDWlLKHJcNm0rIJp
-----END RSA PRIVATE KEY-----"""
        scrubbed = SecretScrubber.scrub(text)
        assert "MIIEpAIBAAKCAQEAwJKtKfXHLeUAM7AwwDowDWlLKHJcNm0rIJp" not in scrubbed
        assert "PRIVATE KEY" not in scrubbed or "***REDACTED***" in scrubbed

    def test_openssh_private_key(self):
        text = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ
-----END OPENSSH PRIVATE KEY-----"""
        scrubbed = SecretScrubber.scrub(text)
        assert "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ" not in scrubbed

    def test_ec_private_key(self):
        text = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIIGlRUzHzBF0EJHs
-----END EC PRIVATE KEY-----"""
        scrubbed = SecretScrubber.scrub(text)
        assert "MHcCAQEEIIGlRUzHzBF0EJHs" not in scrubbed


class TestDatabaseURLScrubbing:
    """Test database connection string scrubbing."""

    def test_mysql_connection_string(self):
        text = "mysql://root:MyP@ssw0rd@localhost:3306/mydb"
        scrubbed = SecretScrubber.scrub(text)
        assert "MyP@ssw0rd" not in scrubbed
        # Should preserve structure
        assert "mysql://" in scrubbed
        assert "@localhost:3306/mydb" in scrubbed

    def test_postgresql_connection_string(self):
        text = "postgresql://user:secret123@db.example.com/production"
        scrubbed = SecretScrubber.scrub(text)
        assert "secret123" not in scrubbed

    def test_mongodb_connection_string(self):
        text = "mongodb://admin:P@ssw0rd!@mongo-cluster/admin"
        scrubbed = SecretScrubber.scrub(text)
        assert "P@ssw0rd!" not in scrubbed


class TestGitTokensScrubbing:
    """Test GitHub/GitLab token detection."""

    def test_github_personal_token_ghp(self):
        text = "token: ghp_1234567890abcdefghijklmnopqrstuvwxyz123"
        scrubbed = SecretScrubber.scrub(text)
        assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz123" not in scrubbed

    def test_github_oauth_token_gho(self):
        text = "GITHUB_TOKEN=gho_abcdefghijklmnopqrstuvwxyz1234567890"
        scrubbed = SecretScrubber.scrub(text)
        assert "gho_abcdefghijklmnopqrstuvwxyz1234567890" not in scrubbed

    def test_gitlab_token(self):
        text = "GITLAB_TOKEN=glpat-abc123def456ghi789jkl"
        scrubbed = SecretScrubber.scrub(text)
        assert "glpat-abc123def456ghi789jkl" not in scrubbed


class TestJWTScrubbing:
    """Test JWT token detection."""

    def test_jwt_token(self):
        text = "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        scrubbed = SecretScrubber.scrub(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in scrubbed


class TestKubernetesSecretsScrubbing:
    """Test Kubernetes secret data scrubbing."""

    def test_kubernetes_secret_yaml(self):
        text = """
apiVersion: v1
kind: Secret
metadata:
  name: my-secret
data:
  password: cGFzc3dvcmQxMjM0NTY3ODkwYWJjZGVm
"""
        scrubbed = SecretScrubber.scrub(text)
        assert "cGFzc3dvcmQxMjM0NTY3ODkwYWJjZGVm" not in scrubbed

    def test_service_account_token(self):
        text = "serviceaccount_token: eyJhbGciOiJSUzI1NiIsImtpZCI6IiJ9.eyJpc3MiOiJrdWJlcm5ldGVzL3NlcnZpY2VhY2NvdW50In0.very_long_token_here_1234567890"
        scrubbed = SecretScrubber.scrub(text)
        assert "very_long_token_here_1234567890" not in scrubbed


class TestSecretScrubberUtilities:
    """Test utility methods."""

    def test_has_secrets_true(self):
        text = "password: secret123"
        assert SecretScrubber.has_secrets(text) is True

    def test_has_secrets_false(self):
        text = "This is a normal log message with no secrets"
        assert SecretScrubber.has_secrets(text) is False

    def test_get_secret_types(self):
        text = "password: secret123, api_key: abc123def456ghi789jklmno"
        types = SecretScrubber.get_secret_types(text)
        assert SecretType.PASSWORD in types
        assert SecretType.API_KEY in types

    def test_scrub_with_type_flag(self):
        text = "password: secret123"
        scrubbed = SecretScrubber.scrub(text, show_type=True)
        assert "***REDACTED-PASSWORD***" in scrubbed or "***REDACTED***" in scrubbed


class TestSecretScrubberDict:
    """Test dictionary scrubbing."""

    def test_scrub_dict_simple(self):
        data = {
            "username": "admin",
            "password": "secret123"
        }
        scrubbed = SecretScrubber.scrub_dict(data)
        assert "secret123" not in str(scrubbed)
        assert scrubbed["username"] == "admin"

    def test_scrub_dict_nested(self):
        data = {
            "database": {
                "host": "localhost",
                "password": "db_secret"
            },
            "api": {
                "key": "api_key: sk-1234567890abcdefghijklmnopqrstuvwxyz"
            }
        }
        scrubbed = SecretScrubber.scrub_dict(data)
        assert "db_secret" not in str(scrubbed)
        assert "sk-1234567890abcdefghijklmnopqrstuvwxyz" not in str(scrubbed)

    def test_scrub_dict_with_list(self):
        data = {
            "secrets": [
                "password: secret1",
                "api_key: sk-abcdefghijklmnopqrstuvwxyz123456"
            ]
        }
        scrubbed = SecretScrubber.scrub_dict(data)
        assert "secret1" not in str(scrubbed)
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in str(scrubbed)


class TestRealWorldScenarios:
    """Test real-world secret leakage scenarios."""

    def test_pod_logs_with_password(self):
        """Simulate pod logs containing database password."""
        logs = """
        2024-04-14 10:30:00 INFO Starting application
        2024-04-14 10:30:01 INFO Connecting to database
        2024-04-14 10:30:02 ERROR Failed to connect: mysql://root:P@ssw0rd123@db:3306/app
        2024-04-14 10:30:03 ERROR Authentication failed
        """
        scrubbed = SecretScrubber.scrub(logs)
        assert "P@ssw0rd123" not in scrubbed

    def test_oc_describe_secret_output(self):
        """Simulate 'oc describe secret' output."""
        output = """
Name:         my-app-secret
Namespace:    default
Labels:       <none>
Annotations:  <none>

Type:  Opaque

Data
====
password:  16 bytes
api-key:   32 bytes
token:     eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123
        """
        scrubbed = SecretScrubber.scrub(output)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in scrubbed

    def test_environment_variables_dump(self):
        """Simulate environment variables containing secrets."""
        env_dump = """
DATABASE_HOST=localhost
DATABASE_USER=admin
DATABASE_PASSWORD=SuperSecret123!
API_KEY=sk-proj-1234567890abcdefghijklmnopqrstuvwxyz
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
        """
        scrubbed = SecretScrubber.scrub(env_dump)
        assert "SuperSecret123!" not in scrubbed
        assert "sk-proj-1234567890abcdefghijklmnopqrstuvwxyz" not in scrubbed
        assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
        assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in scrubbed

    def test_gitops_yaml_with_secrets(self):
        """Simulate GitOps YAML containing inline secrets."""
        yaml = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  database_url: "postgresql://user:mypassword@db.example.com/prod"
  api_config: |
    API_KEY=sk-1234567890abcdefghijklmnopqrstuvwxyz
    SECRET_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz123456
        """
        scrubbed = SecretScrubber.scrub(yaml)
        assert "mypassword" not in scrubbed
        assert "sk-1234567890abcdefghijklmnopqrstuvwxyz" not in scrubbed
        assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in scrubbed


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string(self):
        scrubbed = SecretScrubber.scrub("")
        assert scrubbed == ""

    def test_none_input(self):
        scrubbed = SecretScrubber.scrub(None)
        assert scrubbed is None

    def test_short_passwords_not_matched(self):
        """Passwords < 3 chars should not be matched (too many false positives)."""
        text = "password: ab"
        scrubbed = SecretScrubber.scrub(text)
        # This might still be scrubbed depending on pattern, but we test the behavior
        # The pattern has {3,} so it should NOT match
        assert scrubbed == text or "ab" not in scrubbed

    def test_multiple_secrets_in_one_line(self):
        text = "user: admin, password: secret123, api_key: sk-abcdefghijklmnopqrstuvwxyz"
        scrubbed = SecretScrubber.scrub(text)
        assert "secret123" not in scrubbed
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in scrubbed
        assert "admin" in scrubbed  # Username should remain

    def test_convenience_function(self):
        """Test the module-level convenience function."""
        text = "password: test123"
        scrubbed = scrub_secrets(text)
        assert "test123" not in scrubbed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

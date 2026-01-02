# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.x.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in ReOS, please report it responsibly.

### How to Report

**DO NOT** open a public GitHub issue for security vulnerabilities.

Instead, please report vulnerabilities by:

1. **Email**: Send details to [security@example.com] (replace with actual contact)
2. **GitHub Security Advisories**: Use the "Report a vulnerability" button in the Security tab

### What to Include

Please include the following in your report:

- Description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Suggested fix (if any)
- Your contact information for follow-up

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Fix Timeline**: Depends on severity, typically 30-90 days
- **Disclosure**: Coordinated with reporter

## Security Model

### Design Principles

ReOS is designed with security in mind:

1. **Local-First**: All data stays on your machine by default
2. **No Cloud Calls**: Zero network traffic to external services (except local Ollama)
3. **Metadata-Only**: File content is never captured without explicit opt-in
4. **Sandboxed Tools**: All file operations are path-validated to prevent escapes

### Threat Model

#### In Scope

- Path traversal attacks via tool inputs
- Injection attacks in LLM prompts
- Sensitive data exposure in logs/database
- Privilege escalation via systemd service
- Cross-site scripting in Tauri WebView

#### Out of Scope

- Physical access attacks
- Malicious Ollama server (you control your local LLM)
- Operating system vulnerabilities
- Supply chain attacks on dependencies (we use standard tooling)

### Security Controls

#### Path Sandboxing

All file operations go through `safe_repo_path()`:

```python
def safe_repo_path(repo_root: Path, relative_path: str) -> Path:
    """Validate and resolve path within repo boundaries."""
    resolved = (repo_root / relative_path).resolve()
    if not resolved.is_relative_to(repo_root):
        raise ToolError("Path escapes repository boundary")
    return resolved
```

#### Content Opt-In

File content and diffs require explicit opt-in:

```python
# Metadata only by default
git_summary(repo_path, include_diff=False)

# Content only with explicit flag
git_summary(repo_path, include_diff=True)  # User must opt-in
```

#### Audit Logging

All tool calls and mutations are logged:

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    before_state TEXT,
    after_state TEXT
);
```

### Hardening Recommendations

For production use, we recommend:

#### systemd Hardening

The provided service file includes:

```ini
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=read-only
ProtectSystem=strict
ReadWritePaths=%h/.local/share/reos %h/.config/reos %h/.cache/reos
```

#### Tauri CSP

Configure Content-Security-Policy in `tauri.conf.json`:

```json
{
  "app": {
    "security": {
      "csp": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
    }
  }
}
```

#### Network Isolation

ReOS only needs to connect to local Ollama. You can firewall it:

```bash
# Allow only localhost
iptables -A OUTPUT -p tcp -d 127.0.0.1 --dport 11434 -j ACCEPT
iptables -A OUTPUT -p tcp -m owner --uid-owner reos -j DROP
```

## Known Limitations

1. **SQLite Encryption**: Database is not encrypted at rest. Use full-disk encryption.
2. **Log Sensitivity**: Logs may contain file paths. Secure log directory permissions.
3. **LLM Privacy**: Prompts go to local Ollama. Ensure Ollama isn't forwarding to cloud.

## Security Updates

Security updates are released as patch versions and announced via:

- GitHub Releases
- Security Advisories
- CHANGELOG.md

## Acknowledgments

We thank the following for responsible disclosures:

- (No disclosures yet)

---

Thank you for helping keep ReOS secure!

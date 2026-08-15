# Security Policy

## Reporting Vulnerabilities

If you discover a potential security vulnerability in Codex Local Coding Agent, please report it responsibly:
- Email security reports to the maintainers or open a private security advisory on GitHub.
- Do not disclose vulnerabilities in public issues or discussions until a fix has been released.

---

## Security Model & Sandbox Guarantees

Codex Local Coding Agent is designed specifically to mitigate risks associated with untrusted local model outputs:

1. **No Arbitrary Shell Execution**: Local models are never granted general terminal or shell access. Only predefined, allowlisted commands in the `TaskEnvelope` checks can be triggered.
2. **File Allowlisting & Directory Traversal Protection**: All paths are resolved strictly within the registered workspace boundary. Any attempt to use absolute paths or parent directory traversal (`..`) is blocked.
3. **Bounded Memory & Stream Buffering**: Output streams and file reads are bounded to prevent memory exhaustion or Denial of Service (DoS).
4. **Isolated Process Execution**: Benchmark evaluation and external runner checks run in separate, resource-limited child processes.
5. **Automatic Rollback**: If a patch fails validation or post-apply checks, disk changes are automatically reverted.

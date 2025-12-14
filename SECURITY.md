## Security Policy

### Supported versions

Security fixes are provided for the **latest** version on the default branch.

### Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, report privately by opening a GitHub Security Advisory:

- Go to the repository’s **Security** tab → **Advisories** → **New draft security advisory**

Include as much of the following as possible:

- A clear description of the issue and potential impact
- Steps to reproduce (proof-of-concept if available)
- Affected configuration (Docker vs local, DB backend, etc.)
- Logs / stack traces (redact tokens and any sensitive data)
- Suggested fix (if you have one)

### Sensitive data

IssueBridge stores GitLab access tokens in its database. Treat the database file/volume as **sensitive** and protect it appropriately.

---
name: cyber-audit
description: Perform a read-only security audit of a local repository and its running services, including secrets, dependencies, exposed ports, authentication boundaries, and unsafe operational paths. Use for security reviews, API-key exposure checks, or pre-deployment audits.
---

# Cyber Audit

This is diagnostic only. Do not install, remove, rotate, publish, or deploy anything during the audit.

## Audit sequence

1. Read repository instructions and identify runtime entry points.
2. Search tracked source and configuration for hard-coded credentials, private keys, tokens, unsafe debug output, and permissive CORS/auth bypasses. Do not print secret values.
3. Inspect dependency manifests and lockfiles for audit commands and suspicious additions.
4. Inspect running processes/listeners only when relevant; distinguish loopback from externally reachable services.
5. Trace authentication and authorization from route to service/database boundary.
6. Report each finding with severity, evidence path/line, impact, and a safe remediation suggestion.

## Scalper-specific checks

- Confirm the system uses Binance/public market data only and does not contain a live order path.
- Confirm API keys are not required by paper-trading or public-data flows and are absent from logs/configuration.
- Verify paper balance/reset and trade-state endpoints cannot mutate real exchange accounts.
- Check SQL paths for write authorization, injection, and unsafe dynamic identifiers.
- Check frontend/backend CORS, error responses, and log redaction around symbols, balances, and provider responses.
- Treat `BUY_BLOCKED` as a rejected candidate, never as an opened position.

## Output

Use: scope, evidence, findings ordered by severity, verified non-findings, commands run, and remaining validation gaps. If a finding is confirmed, stop at the report unless the user explicitly requests a remediation change.

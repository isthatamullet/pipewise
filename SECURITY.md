# Security Policy

Pipewise is pre-1.0 (`0.x`). The maintainer takes security seriously; this
document describes how to report a vulnerability and what to expect in
response.

## Supported Versions

| Version              | Supported        |
|----------------------|------------------|
| Latest released v0.x | ✅               |
| `main` branch        | ✅ (best effort) |
| Older v0.x releases  | ❌ no backports  |

Once pipewise reaches v1.0, this table will be updated to reflect a longer
support window for the previous major version.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security reports.** Public
disclosure before a fix is available puts other adopters at risk.

### Preferred channel

- **GitHub Security Advisories** — [Report a vulnerability](https://github.com/isthatamullet/pipewise/security/advisories/new). This is a private, encrypted channel managed by GitHub; the report is visible only to you and the maintainers until an advisory is published.

### Fallback

- Email: [security@pipewise.dev](mailto:security@pipewise.dev) (subject line prefix: `pipewise security`).
  Email is unencrypted in transit; for sensitive details (proof-of-concept code, exploit payloads), prefer the GitHub Security Advisories channel above.

### What to include

A good report helps triage and remediation move faster. Where applicable, include:

- **Pipewise version** (`pipewise --version` or the git SHA if running from source)
- **Python version** and operating system
- **Reproduction steps** — minimal config, dataset shape, or sequence of actions that demonstrates the issue
- **Impact** — what the vulnerability allows an attacker to do, and against what trust boundary
- **Suggested fix or mitigation**, if you have one

## Response Timeline

These are best-effort targets, not service-level guarantees. Pipewise is
maintained by a single person at this stage; response times during weekends,
holidays, or extended absences may be longer.

| Stage              | Target                                                      |
|--------------------|-------------------------------------------------------------|
| Acknowledgment     | within 5 business days                                      |
| Initial assessment | within 10 business days                                     |
| Fix or mitigation  | depends on severity; communicated as part of the assessment |

We may ship a mitigation or workaround before a complete fix is available
when severity warrants it.

## Coordinated Disclosure

Please refrain from publicly discussing a potential vulnerability until a
fix or mitigation is available. We will:

1. Acknowledge your report and confirm receipt
2. Investigate, assess severity, and develop a fix
3. Coordinate a disclosure timeline with you
4. Credit you (by name or alias, as you prefer) when the advisory is published

If a vulnerability requires more time to fix than we anticipated, we'll keep
you informed and agree on a revised disclosure timeline in good faith.

## Out of Scope

The following are not considered security vulnerabilities for the purposes of
this policy. They are still welcome as bug reports via standard GitHub issues:

- Bugs in evaluation logic, scorer behavior, or report formatting that don't
  involve a trust boundary
- Performance issues
- Issues in adapters that ship outside the `pipewise/` package (adapters live
  in their own pipeline repos and have their own maintainers)
- Issues in third-party dependencies that don't materially affect pipewise's
  behavior — please report those upstream

## Why This Policy Is Brief

Pipewise is a pure evaluation library — it reads `PipelineRun` JSON, runs
scorers, and writes reports. It does not execute user code, run untrusted
network requests, persist secrets, or expose remote endpoints. The trust
boundary is correspondingly narrow, so this policy is correspondingly short.
If pipewise's surface expands in a way that warrants a more detailed trust
model (e.g., a hosted service, a sandboxed scorer execution mode), this
document will expand with it.

# AGENTS.md

## Vision

This project exists to let a human enter and leave an automated browser flow without breaking the flow, adding value where automation is weak or blocked: authentication, CAPTCHA, consent, approval, recovery, and other interactive steps.

Human intervention is a capability, not the final limit. The project should evolve toward advanced automation, including automated handling of difficult interactive steps where technically and legally appropriate.

## Guardrails

- Preserve browser/profile/session continuity across human and machine control transitions.
- A human must be able to take over, act, and hand control back without corrupting or restarting the workflow.
- Automation may expand over time, but it must not weaken isolation or expose private/internal destinations unintentionally.
- Sensitive actions such as credentials, OTPs, tokens, and approvals may become automated only through explicit, deliberate mechanisms with clear security boundaries.
- Keep the project generic and self-hosted. Do not couple its architecture to OpenClaw, Gallivanter, or one specific automation client.
- Prefer capabilities that improve the bridge between human interaction and automation over unrelated browser-platform features.

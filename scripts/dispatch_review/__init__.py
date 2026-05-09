"""Pre-push dispatch review package.

Invoked by ``.githooks/pre-push`` via ``scripts/pre_push_review.py`` to run
an LLM-based first-sieve review of dispatch markdown files before they
reach the Codex Connector. Codex remains the final-line authority; this
package only reduces round count by catching mechanically-detectable
violations of the institutional self-consistency rules.

See ``docs/audits/2026-05-09-infra-pre-push-dispatch-review-hook-dispatch.md``
for the design rationale and ``docs/audit-protocol/dispatch-review-rules.md``
for the rule set the LLM applies.
"""

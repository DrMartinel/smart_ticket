// What the triage pipeline's decisions mean, in a reviewer's words. The codes
// are core-api's `Branch` and `ReasonCode` (apps/tickets/utils/router.py).

export const BRANCH_LABEL: Record<string, string> = {
  auto_reply: "Answered automatically",
  auto_route: "Routed automatically",
  hitl: "Sent to a person",
  clarify: "Asked the requester to clarify",
  escalate: "Escalated",
  block: "Blocked",
};

export const REASON_TEXT: Record<string, string> = {
  injection_detected: "The message tries to give the assistant instructions (prompt injection), so it was not processed.",
  pii_critical: "It contains highly sensitive personal data, so only a person may handle it.",
  pii_mask_failed: "Personal data could not be removed reliably, so only a person may read it.",
  schema_invalid: "The AI's answer was malformed, so nothing it proposed was used.",
  mass_incident: "Many similar tickets arrived at once: this looks like an incident affecting many people.",
  retrieval_below_floor: "No knowledge-base page matched the question well enough to answer it.",
  kb_not_authorized: "The matching page is not approved for automatic answers.",
  quote_invalid: "The answer quoted text that is not in the cited page.",
  quote_source_not_in_topk: "The answer cited a page the search did not rank among the best matches.",
  negation_mismatch: "The answer contradicts the page it cites (a 'do' became a 'don't').",
  rerank_disagrees: "The answer cites a different page than the one the ranking model chose.",
  rerank_low_confidence: "The ranking model was not sure enough which page answers this.",
  trust_below_auto_threshold: "Confidence was too low to answer automatically.",
  trust_below_route_threshold: "Confidence was too low to route automatically.",
  category_low_confidence: "The AI was not sure which category this belongs to.",
  clarify_security: "It is security-related, so a person asks any clarifying question.",
  clarify_options_not_shown: "The AI wanted to offer pages it was never shown.",
  clarify_round_cap: "The requester was already asked once; a person takes it from here.",
  ai_engine_unavailable: "The AI service was unavailable, so it went straight to a person.",
  embedding_unavailable: "The search service was unavailable, so it went straight to a person.",
  budget_exceeded: "Today's AI budget is used up, so it went straight to a person.",
  all_llm_down: "The language model was unavailable, so it went straight to a person.",
  circuit_open: "The AI service was paused after repeated failures.",
  all_checks_passed: "Every check passed.",
};

export const INTENT_LABEL: Record<string, string> = {
  auto_reply: "Answer from a help page",
  route_to_team: "Route to a team",
  runbook: "Run a runbook (needs approval)",
  insufficient_context: "Not enough information to act",
  clarify: "Ask the requester which page they mean",
};

export const QUEUE_LABEL: Record<string, string> = {
  pii_verify: "Personal data check",
  low_confidence: "Low confidence",
  injection: "Prompt injection",
  mask_failed: "Masking failed",
  runbook_approval: "Runbook approval",
  clarification: "Clarification",
};

export function reasonText(code: string): string {
  return REASON_TEXT[code] ?? code.replaceAll("_", " ");
}

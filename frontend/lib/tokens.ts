export type StatusTone = "good" | "warning" | "bad" | "neutral";

export const statusTokens: Record<StatusTone, { pill: string; surface: string; icon: string }> = {
  good: { pill: "status-good", surface: "surface-good", icon: "text-teal" },
  warning: { pill: "status-warning", surface: "surface-warning", icon: "text-amber" },
  bad: { pill: "status-bad", surface: "surface-bad", icon: "text-danger" },
  neutral: { pill: "status-neutral", surface: "surface-neutral", icon: "text-slate" }
};

export function statusTone(status: string): StatusTone {
  if (["complete", "published", "validated", "reviewer_approved", "ready_for_submission", "ready"].includes(status)) return "good";
  if (["failed", "rejected", "reviewer_rejected", "red"].includes(status.toLowerCase())) return "bad";
  if (["needs_review", "processing", "uploaded", "yellow", "blocked", "warning"].includes(status.toLowerCase())) return "warning";
  return "neutral";
}

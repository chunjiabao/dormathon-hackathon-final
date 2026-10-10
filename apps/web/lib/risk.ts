import type { Forecast } from "./types";

export const RISK: Record<
  Forecast["budget_risk"],
  { label: string; tone: "default" | "warning" | "danger" | "success"; help: string }
> = {
  high_confidence_overrun: {
    label: "Overrun likely",
    tone: "danger",
    help: "Even the lower bound of the forecast interval exceeds the budget.",
  },
  projected_overrun: {
    label: "Projected overrun",
    tone: "danger",
    help: "The central month-end forecast exceeds the budget (lower bound does not).",
  },
  possible_overrun: {
    label: "Possible overrun",
    tone: "warning",
    help: "The central forecast is within budget, but the upper bound exceeds it.",
  },
  within_budget: { label: "Within budget", tone: "success", help: "Even the upper bound is within budget." },
  unknown: { label: "Unknown", tone: "default", help: "Not enough history for a forecast yet." },
};

import {
  Activity,
  BarChart3,
  FlaskConical,
  Gauge,
  LineChart,
  MessageSquare,
  Settings,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };

export const NAV_ITEMS: NavItem[] = [
  { href: "/overview", label: "Overview", icon: Gauge },
  { href: "/predictions", label: "Predictions", icon: LineChart },
  { href: "/anomalies", label: "Anomalies", icon: TriangleAlert },
  { href: "/decisions", label: "Decision Lab", icon: FlaskConical },
  { href: "/usage", label: "Usage Explorer", icon: BarChart3 },
  { href: "/evaluation", label: "Evaluation", icon: Activity },
  { href: "/demo/chat", label: "Demo Chatbot", icon: MessageSquare },
  { href: "/settings", label: "Settings", icon: Settings },
];

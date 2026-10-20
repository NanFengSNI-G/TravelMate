export type Page =
  "home" | "assistant" | "plans" | "orders" | "support" | "knowledge";
export type RunStatus =
  "QUEUED" | "RUNNING" | "WAITING" | "DONE" | "FAILED" | "CANCELLED";
export interface User {
  id: string;
  name: string;
  role: "user" | "admin";
}
export interface RequestData {
  intent:
    | "orders"
    | "plans"
    | "chat"
    | "policy"
    | "search"
    | "plan"
    | "book"
    | "change"
    | "cancel"
    | "support"
    | "repair"
    | "admin_write";
  question?: string;
  resolved_question?: string | null;
  departure?: string;
  destination?: string;
  start?: string | null;
  end?: string | null;
  people?: number;
  budget_cents?: number;
  resource_ids?: string[];
  resource_kinds?: ("flight" | "hotel")[];
  option_id?: string;
  order_id?: string;
  plan_id?: string;
  case_id?: string;
  admin_action?: Record<string, unknown>;
}
export interface Evidence {
  node_id: string;
  revision_id: string;
  source: string;
  section: string;
  text: string;
  score: number;
}
export interface EvidenceBundle {
  status: string;
  evidence: Evidence[];
  snapshot: string[];
}
export interface Resource {
  id: string;
  kind: "flight" | "hotel";
  name: string;
  supplier?: string;
  product?: string;
  price: number;
  details: {
    departure?: string;
    destination?: string;
    date?: string;
    max_people?: number;
  };
}
export interface Candidate extends Resource {
  amount: number;
  slots: string[];
  quantity: number;
}
export interface PlanOption {
  option_id?: string;
  label: string;
  resource_ids: string[];
  amount?: number;
  start: string;
  end: string;
  people?: number;
  budget_cents?: number;
  scope?: string;
  evidence?: EvidenceBundle;
  days?: { date: string; activity: string }[];
  explanation?: string;
  evidence_ids?: string[];
}
export interface Plan {
  id: string;
  options: PlanOption[];
  created?: number;
}
export interface Repair {
  options: PlanOption[];
  unresolved: string[];
  diff?: { before: PlanOption[]; after: PlanOption[] };
}
export interface Order {
  id: string;
  resource: string;
  status: string;
  amount: number;
  quantity: number;
  version: number;
  slots: string[];
}
export interface Action {
  kind: string;
  data?: any;
  quote?: string;
  order?: string;
  fee?: number;
}
export interface Proposal {
  id: string;
  version: number;
  actions: Action[];
  evidence: Evidence[];
  expires: number;
}
export interface ActionPreview {
  subject?: string;
  kind: string;
  valid: boolean;
  name?: string;
  resource_kind?: string;
  resource_id?: string;
  amount?: number;
  quantity?: number;
  slots?: string[];
  details?: Resource["details"];
  fee?: number;
  difference?: number;
  data?: any;
}
export interface Operation {
  status: string;
  order?: string;
  fee?: number;
  amount?: number;
  difference?: number;
  message?: string;
  case_id?: string;
}
export interface Run {
  id: string;
  conversation_id: string;
  status: RunStatus;
  cancel_requested?: boolean;
  payload: RequestData;
  created_at?: number;
  activity?: {
    id: string;
    node: string;
    label: string;
    tools: { label: string; count: number }[];
  }[];
  preview: ActionPreview[];
  error?: string;
  result: {
    approval?: { proposal: Proposal };
    evidence?: EvidenceBundle;
    customer?: { answer: string };
    results?: Record<string, { candidates: Candidate[]; answer?: string }>;
    plan?: Plan;
    repair?: Repair;
    operations?: Operation[];
    case_id?: string;
    message?: string;
    policy_choices?: { id: string; name: string; kind: string }[];
    decision?: string;
    knowledge?: { revision: string };
  };
}
export interface ChatEntry {
  text: string;
  created_at?: number;
  run: Run | null;
}
export interface Conversation {
  id: string;
  title: string;
  preview: string;
  message_count: number;
  updated_at: number;
}
export interface Case {
  id: string;
  customer: string;
  context: { request?: RequestData; customer?: { answer?: string } };
  status: string;
  assigned?: string;
  replies: { by: string; text: string; role?: string }[];
}
export interface Revision {
  id: string;
  document: string;
  supplier: string;
  product: string;
  source: string;
  status: string;
  valid_from: string;
  valid_to: string;
  error?: string;
  rules: { cancel_fee_cents: number };
}
export type Submit = (
  text: string,
  request?: RequestData,
  newConversation?: boolean,
) => Promise<boolean>;

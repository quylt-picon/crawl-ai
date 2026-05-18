import { create } from "zustand";
import type {
  CompletionEvent,
  LogEvent,
  ManualResult,
  ProgressEvent,
  StepId,
  StepStatus,
} from "@/types/events";

export const STEP_ORDER: StepId[] = [
  "crawl_homepage",
  "analyze_ui",
  "search_product",
  "filter_results",
  "open_product_page",
  "expand_sections",
  "find_manual",
  "finalize",
];

export const STEP_LABELS: Record<StepId, string> = {
  crawl_homepage: "Crawl homepage",
  analyze_ui: "Analyze UI",
  search_product: "Search product",
  filter_results: "Filter results",
  open_product_page: "Open product page",
  expand_sections: "Expand tabs & sections",
  find_manual: "Find user manual",
  finalize: "Finalize result",
};

export interface StepState {
  id: StepId;
  status: StepStatus;
  message?: string;
  timestamp?: string;
  data?: Record<string, unknown> | null;
}

export interface TimelineEntry {
  id: string;
  kind: "progress" | "log";
  step?: StepId;
  status?: StepStatus;
  level?: "info" | "warning" | "error" | "debug";
  message: string;
  timestamp: string;
  data?: Record<string, unknown> | null;
}

interface WorkflowState {
  jobId: string | null;
  running: boolean;
  steps: Record<StepId, StepState>;
  timeline: TimelineEntry[];
  manual: ManualResult | null;
  error: string | null;
  resetAndStart: (jobId: string) => void;
  applyProgress: (event: ProgressEvent) => void;
  applyLog: (event: LogEvent) => void;
  applyCompletion: (event: CompletionEvent) => void;
  setError: (err: string) => void;
}

const emptySteps = (): Record<StepId, StepState> =>
  Object.fromEntries(
    STEP_ORDER.map((id) => [id, { id, status: "pending" as StepStatus }])
  ) as Record<StepId, StepState>;

let entryCounter = 0;
const nextId = () => `${Date.now()}-${++entryCounter}`;

export const useWorkflow = create<WorkflowState>((set) => ({
  jobId: null,
  running: false,
  steps: emptySteps(),
  timeline: [],
  manual: null,
  error: null,

  resetAndStart: (jobId) =>
    set({
      jobId,
      running: true,
      steps: emptySteps(),
      timeline: [],
      manual: null,
      error: null,
    }),

  applyProgress: (event) =>
    set((state) => {
      const prev = state.steps[event.step];
      // Keep the richest data we've seen for this step (a SUCCESS event has
      // more detail than the preceding RUNNING one).
      const mergedData = event.data ?? prev?.data ?? null;
      return {
        steps: {
          ...state.steps,
          [event.step]: {
            id: event.step,
            status: event.status,
            message: event.message,
            timestamp: event.timestamp,
            data: mergedData,
          },
        },
        timeline: [
          ...state.timeline,
          {
            id: nextId(),
            kind: "progress",
            step: event.step,
            status: event.status,
            message: event.message,
            timestamp: event.timestamp,
            data: event.data ?? null,
          },
        ],
      };
    }),

  applyLog: (event) =>
    set((state) => ({
      timeline: [
        ...state.timeline,
        {
          id: nextId(),
          kind: "log",
          step: event.step ?? undefined,
          level: event.level,
          message: event.message,
          timestamp: event.timestamp,
        },
      ],
    })),

  applyCompletion: (event) =>
    set({
      running: false,
      manual: event.success
        ? {
            type: event.manual_type ?? "not_found",
            url: event.manual_url ?? null,
            content: null, // populated via /result on demand
          }
        : { type: "not_found", url: null, content: null },
      error: event.error ?? null,
    }),

  setError: (err) => set({ running: false, error: err }),
}));

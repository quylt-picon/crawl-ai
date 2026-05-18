import { useCallback, useEffect, useRef } from "react";
import { getResult, startSearch, type SearchInput } from "@/lib/api";
import { openEventStream } from "@/lib/sse";
import { useWorkflow } from "@/store/workflow";

export function useCrawlJob() {
  const store = useWorkflow();
  const closeRef = useRef<(() => void) | null>(null);

  useEffect(() => () => closeRef.current?.(), []);

  const submit = useCallback(
    async (input: SearchInput) => {
      closeRef.current?.();
      try {
        const { job_id } = await startSearch(input);
        store.resetAndStart(job_id);

        closeRef.current = openEventStream(job_id, {
          onProgress: store.applyProgress,
          onLog: store.applyLog,
          onCompletion: async (event) => {
            store.applyCompletion(event);
            // Fetch the full result so we can show inline/HTML manual content.
            if (event.success) {
              try {
                const final = await getResult(job_id);
                useWorkflow.setState({ manual: final.manual });
              } catch {
                /* keep what we have */
              }
            }
          },
          onError: () => {
            // EventSource auto-reconnects; only flag persistent failures.
          },
        });
      } catch (err) {
        store.setError(err instanceof Error ? err.message : String(err));
      }
    },
    [store]
  );

  return { submit };
}

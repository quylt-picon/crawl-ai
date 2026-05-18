import type {
  CompletionEvent,
  LogEvent,
  ProgressEvent,
} from "@/types/events";

export interface SSEHandlers {
  onProgress?: (event: ProgressEvent) => void;
  onLog?: (event: LogEvent) => void;
  onCompletion?: (event: CompletionEvent) => void;
  onError?: (err: unknown) => void;
}

/**
 * Open an SSE connection to `/api/crawl/stream/{jobId}`.
 *
 * The stream is terminated permanently on:
 *   - a `completion` event (success OR failure — both stop the stream)
 *   - a hard network error (EventSource.readyState === CLOSED)
 *   - the returned disposer being called
 *
 * Once terminated, no further events are dispatched and EventSource will not
 * attempt to reconnect — important for failure paths where the server has
 * closed the channel and reconnects would block on an empty queue.
 */
export function openEventStream(jobId: string, handlers: SSEHandlers): () => void {
  const source = new EventSource(`/api/crawl/stream/${jobId}`);
  let terminated = false;

  const terminate = () => {
    if (terminated) return;
    terminated = true;
    source.close();
  };

  source.addEventListener("progress", (e) => {
    if (terminated) return;
    try {
      handlers.onProgress?.(JSON.parse((e as MessageEvent).data));
    } catch (err) {
      handlers.onError?.(err);
    }
  });
  source.addEventListener("log", (e) => {
    if (terminated) return;
    try {
      handlers.onLog?.(JSON.parse((e as MessageEvent).data));
    } catch (err) {
      handlers.onError?.(err);
    }
  });
  source.addEventListener("completion", (e) => {
    if (terminated) return;
    try {
      handlers.onCompletion?.(JSON.parse((e as MessageEvent).data));
    } catch (err) {
      handlers.onError?.(err);
    } finally {
      // success=true or success=false — either way the workflow is done.
      terminate();
    }
  });
  source.onerror = (err) => {
    if (terminated) return;
    // EventSource auto-reconnects on transient errors; only escalate when
    // the connection is permanently closed.
    if (source.readyState === EventSource.CLOSED) {
      handlers.onError?.(err);
      terminate();
    }
  };

  return terminate;
}

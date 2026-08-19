export interface SseHandlers {
  onEvent: (event: { event: string; seq: number; text?: string; status?: string }) => void;
  onError?: (error: unknown) => void;
}

export function connectTaskEvents(
  taskId: string,
  token: string,
  fromSeq: number,
  handlers: SseHandlers,
  signal: AbortSignal,
): { stop: () => void } {
  let lastSeq = fromSeq;
  let stopped = false;

  async function loop() {
    while (!stopped && !signal.aborted) {
      try {
        const response = await fetch(`/api/v1/tasks/${taskId}/events?from_seq=${lastSeq}`, {
          headers: { Authorization: `Bearer ${token}` },
          signal,
        });
        if (!response.ok || !response.body) throw new Error('sse failed');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!stopped) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split('\n\n');
          buffer = chunks.pop() ?? '';
          for (const chunk of chunks) {
            const dataLine = chunk.split('\n').find((line) => line.startsWith('data: '));
            if (!dataLine) continue;
            const payload = JSON.parse(dataLine.slice(6)) as {
              event: string;
              seq: number;
              text?: string;
              status?: string;
              blocked?: boolean;
              scope_key?: string;
            };
            lastSeq = payload.seq;
            handlers.onEvent(payload);
            if (payload.event === 'task.finished') {
              stopped = true;
              return;
            }
          }
        }
      } catch (error) {
        if (stopped || signal.aborted) return;
        handlers.onError?.(error);
        await new Promise((resolve) => setTimeout(resolve, 800));
      }
    }
  }

  void loop();
  return {
    stop() {
      stopped = true;
    },
  };
}

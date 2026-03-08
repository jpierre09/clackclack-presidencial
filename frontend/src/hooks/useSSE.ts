import { useEffect, useRef } from "react";

interface EventPayload {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export function useSSE(onEvent: (event: EventPayload) => void) {
  const callbackRef = useRef(onEvent);

  useEffect(() => {
    callbackRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    const source = new EventSource("/api/events");

    source.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as EventPayload;
        callbackRef.current(parsed);
      } catch {
        // Ignore malformed events.
      }
    };

    source.onerror = () => {
      // Browser auto-reconnect handles transient network errors.
    };

    return () => {
      source.close();
    };
  }, []);
}

import { useEffect, useRef, useState } from "react";
import type { JobEvent } from "./types";

/** Live log qua SSE. Tự kết nối lại (EventSource gửi Last-Event-ID). Giữ tối đa `max` dòng. */
export function useEventStream(url: string | null, onEvent?: (e: JobEvent) => void, max = 1000) {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  cb.current = onEvent;

  useEffect(() => {
    if (!url) return;
    setEvents([]);
    const es = new EventSource(url, { withCredentials: true });
    const seen = new Set<string>();
    let buffer: JobEvent[] = [];
    let timer: number | undefined;
    const flush = () => {
      timer = undefined;
      const batch = buffer;
      buffer = [];
      setEvents((prev) => {
        const next = prev.concat(batch);
        return next.length > max ? next.slice(next.length - max) : next;
      });
    };
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("log", (msg) => {
      const ev = JSON.parse((msg as MessageEvent).data) as JobEvent;
      if (seen.has(ev.id)) return;
      seen.add(ev.id);
      buffer.push(ev);
      cb.current?.(ev);
      if (timer === undefined) timer = window.setTimeout(flush, 120);
    });
    return () => {
      es.close();
      if (timer !== undefined) clearTimeout(timer);
      setConnected(false);
    };
  }, [url, max]);

  return { events, connected };
}

import { useEffect, useState } from "react";
import { fetchHealth, type ApiHealthResponse } from "@/services/api";

const DEFAULT_POLL_MS = 60_000;

export function useRuntimeHealth(pollMs = DEFAULT_POLL_MS) {
  const [health, setHealth] = useState<ApiHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const snapshot = await fetchHealth();
      if (!cancelled) {
        setHealth(snapshot);
        setLoading(false);
      }
    };

    void load();
    const timer = window.setInterval(() => {
      void load();
    }, pollMs);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pollMs]);

  return { health, loading };
}

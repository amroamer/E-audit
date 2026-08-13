import { useEffect, useState } from "react";
import type { AiSource } from "./ai";

export function useReport(id?: string, rev?: number) {
  const [text, setText] = useState("");
  const [source, setSource] = useState<AiSource | null>(null);
  useEffect(() => {
    if (!id) return;
    setText("");
    setSource(null);
    const es = new EventSource(`/api/cases/${id}/report`);
    es.addEventListener("token", (e) => setText((t) => t + (e as MessageEvent).data));
    es.addEventListener("fallback", () => setText(""));                 // clear partial
    es.addEventListener("done", (e) => {
      setSource((e as MessageEvent).data as AiSource);
      es.close();
    });
    es.onerror = () => {
      es.close();
      setSource((s) => s ?? "stream-error");                           // no perpetual spinner
    };
    return () => es.close();
  }, [id, rev]);
  return { text, streaming: source === null, source };
}

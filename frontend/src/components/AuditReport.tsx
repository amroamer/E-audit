import type { ReactNode } from "react";
import { useReport } from "../ai/useStream";
import VerifyBadge from "./VerifyBadge";

const bold = (s: string) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

function renderMd(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = (k: string) => {
    if (list.length) {
      out.push(
        <ul key={"u" + k}>
          {list.map((l, i) => (
            <li key={i} dangerouslySetInnerHTML={{ __html: bold(l) }} />
          ))}
        </ul>,
      );
      list = [];
    }
  };
  text.split("\n").forEach((ln, k) => {
    if (ln.startsWith("## ")) {
      flush("h" + k);
      out.push(<h4 key={k}>{ln.slice(3)}</h4>);
    } else if (ln.startsWith("- ")) {
      list.push(ln.slice(2));
    } else if (ln.trim() === "") {
      flush("b" + k);
    } else {
      flush("p" + k);
      out.push(<p key={k} dangerouslySetInnerHTML={{ __html: bold(ln) }} />);
    }
  });
  flush("end");
  return out;
}

export default function AuditReport({ id, rev }: { id?: string; rev?: number }) {
  const { text, streaming, source } = useReport(id, rev);
  return (
    <div className="panel ai-panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">AI</span>
          <h2>Draft audit report</h2>
        </div>
        <VerifyBadge source={source} />
      </div>
      <div className="ai-body md">
        {text ? renderMd(text) : <span className="muted">Drafting…</span>}
        {streaming && <span className="cursor">▍</span>}
      </div>
    </div>
  );
}

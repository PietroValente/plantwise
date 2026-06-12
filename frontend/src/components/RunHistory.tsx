import { documentDownloadUrl } from "../api";
import type { DocumentInfo, Run } from "../types";

interface Props {
  runs: Run[];
  documents: DocumentInfo[];
  openRunIds: Set<string>;
  onOpenRun: (run: Run) => void;
}

const STATUS_COLOR: Record<Run["status"], string> = {
  running: "text-solar",
  completed: "text-led",
  failed: "text-alert",
};

const DOC_TAG: Record<string, string> = { pdf: "PDF", xlsx: "XLS", docx: "DOC" };

function SectionTitle({ children }: { children: string }) {
  return (
    <h2 className="mb-2.5 flex items-center gap-2 font-display text-[11px] font-semibold uppercase tracking-[0.25em] text-dim">
      <span className="inline-block h-px w-4 bg-solar" />
      {children}
    </h2>
  );
}

export default function RunHistory({ runs, documents, openRunIds, onOpenRun }: Props) {
  return (
    <div className="flex h-full flex-col gap-7 overflow-y-auto px-4 py-5">
      <section>
        <SectionTitle>run log</SectionTitle>
        <ul className="space-y-1.5">
          {runs.length === 0 && (
            <li className="font-mono text-[11px] text-faint">— no runs recorded —</li>
          )}
          {runs.map((r) => (
            <li key={r.run_id}>
              <button
                onClick={() => onOpenRun(r)}
                className={`w-full border-l-2 px-2.5 py-2 text-left transition hover:bg-raise/70 ${
                  openRunIds.has(r.run_id)
                    ? "border-solar bg-raise/50"
                    : "border-line bg-transparent"
                }`}
              >
                <div className="mb-1 flex items-center justify-between font-mono text-[9.5px] uppercase tracking-wider">
                  <span className={`flex items-center gap-1.5 ${STATUS_COLOR[r.status]}`}>
                    <span className={`led ${r.status === "running" ? "led--pulse" : ""}`} />
                    {r.status}
                  </span>
                  <span className="text-faint tabular-nums">
                    {new Date(r.created_at).toLocaleTimeString([], { hour12: false })}
                  </span>
                </div>
                <div className="line-clamp-2 text-[12px] leading-snug text-dim">
                  {r.prompt}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <SectionTitle>exports</SectionTitle>
        <ul className="space-y-1">
          {documents.length === 0 && (
            <li className="font-mono text-[11px] text-faint">— no documents generated —</li>
          )}
          {documents.map((d) => (
            <li key={d.id}>
              <a
                href={documentDownloadUrl(d.id)}
                className="group flex items-center gap-2 px-1.5 py-1 transition hover:bg-raise/70"
                title={d.filename}
              >
                <span className="border border-line px-1 py-0.5 font-mono text-[8.5px] tracking-wider text-volt group-hover:border-volt">
                  {DOC_TAG[d.doc_type] ?? "FILE"}
                </span>
                <span className="truncate font-mono text-[11.5px] text-dim group-hover:text-solar">
                  {d.filename}
                </span>
              </a>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

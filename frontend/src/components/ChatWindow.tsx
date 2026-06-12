import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, streamRun, withUserParam } from "../api";
import type { ChatEntry, LoginUser, ToolEvent } from "../types";

interface Props {
  user: LoginUser | undefined;
  entries: ChatEntry[];
  onEntriesChange: (update: (prev: ChatEntry[]) => ChatEntry[]) => void;
  onRunFinished: () => void;
}

/** Suggestions match what the operator's scope can actually answer: financial
 * prompts would just hit the RLS wall for energy-only users. */
function suggestionsFor(user: LoginUser | undefined): string[] {
  if (user?.access_scope === "energy+financial") {
    return [
      "How much energy did each plant produce in March 2026?",
      "Top cost categories in March — make me an Excel",
      "Estimate March revenue and produce a PDF report",
    ];
  }
  return [
    "How much energy did each plant produce in March 2026?",
    "Which plant had the best irradiance-to-output ratio?",
    "Daily production trend for March — make me an Excel",
  ];
}

function patchEntry(
  onEntriesChange: Props["onEntriesChange"],
  runId: string,
  patch: Partial<ChatEntry>,
) {
  onEntriesChange((prev) =>
    prev.map((e) => (e.runId === runId ? { ...e, ...patch } : e)),
  );
}

const TOOL_LABEL: Record<string, string> = {
  sql_query: "SQL",
  python_exec: "PYTHON",
  generate_pdf: "PDF",
  generate_excel: "XLSX",
  generate_word: "DOCX",
};

function Telemetry({ ev }: { ev: ToolEvent }) {
  const started = ev.kind === "tool_start";
  return (
    <details className="group border-l-2 border-line pl-2.5 transition hover:border-volt">
      <summary className="flex cursor-pointer select-none items-center gap-2 py-0.5 font-mono text-[11px]">
        <span className={started ? "text-volt" : "text-led"}>
          {started ? "▸" : "✓"}
        </span>
        <span className="uppercase tracking-wider text-dim group-hover:text-ink">
          {TOOL_LABEL[ev.tool] ?? ev.tool}
        </span>
        <span className="text-faint">{started ? "dispatch" : "return"}</span>
      </summary>
      <pre className="my-1 max-h-44 overflow-auto whitespace-pre-wrap break-all bg-abyss/70 p-2 font-mono text-[10.5px] leading-relaxed text-dim">
        {ev.detail}
      </pre>
    </details>
  );
}

function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      components={{
        a: ({ href, children }) => (
          <a href={withUserParam(href ?? "")} target="_blank" rel="noreferrer">
            {children}
          </a>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

function EntryView({ entry, index }: { entry: ChatEntry; index: number }) {
  return (
    <div className="anim-rise space-y-3" style={{ animationDelay: `${Math.min(index, 4) * 60}ms` }}>
      {/* operator transmission */}
      <div className="ml-auto w-fit max-w-[85%]">
        <div className="mb-1 text-right font-mono text-[9px] uppercase tracking-[0.25em] text-faint">
          operator
        </div>
        <div className="border-r-2 border-solar bg-raise/80 px-4 py-2.5 text-sm text-ink shadow-[0_0_24px_rgb(255_182_39/0.05)]">
          {entry.prompt}
        </div>
      </div>

      {/* agent console card */}
      <div className="w-fit min-w-[260px] max-w-[94%]">
        <div className="mb-1 flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.25em] text-faint">
          <span
            className={`led ${entry.status === "running" ? "led--pulse text-solar" : entry.status === "failed" ? "text-alert" : "text-led"}`}
          />
          agent · run {entry.runId.slice(0, 8)}
        </div>
        <div className="brackets border border-line bg-panel/90 px-4 py-3">
          {entry.tools.length > 0 && (
            <div className="mb-2.5 space-y-0.5">
              {entry.tools.map((t, i) => (
                <Telemetry key={i} ev={t} />
              ))}
            </div>
          )}
          {entry.status === "running" && (
            <div className="whitespace-pre-wrap break-words font-mono text-[12.5px] leading-relaxed text-dim">
              {entry.liveText || "establishing link"}
              <span className="cursor-block" />
            </div>
          )}
          {entry.status !== "running" && entry.finalText && (
            <div className="md text-ink">
              <Markdown text={entry.finalText} />
            </div>
          )}
          {entry.status === "failed" && (
            <div className="mt-2 border-l-2 border-alert bg-alert/10 px-2.5 py-1.5 font-mono text-[11px] text-alert">
              RUN FAILED — {entry.error ?? "unknown error"}
            </div>
          )}
          {entry.status === "completed" && !entry.finalText && (
            <div className="font-mono text-xs text-faint">completed with no text output</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ChatWindow({ user, entries, onEntriesChange, onRunFinished }: Props) {
  const [prompt, setPrompt] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const entriesRef = useRef(entries);
  entriesRef.current = entries;

  // One EventSource per running entry; reconnects after refresh too.
  useEffect(() => {
    const cleanups: (() => void)[] = [];
    for (const e of entries) {
      if (e.status === "running" && !activeStreams.has(e.runId)) {
        activeStreams.add(e.runId);
        const stop = streamRun(
          e.runId,
          (patch) => {
            patchEntry(onEntriesChange, e.runId, patch);
            if (patch.status && patch.status !== "running") {
              activeStreams.delete(e.runId);
              onRunFinished();
            }
          },
          () => entriesRef.current.find((x) => x.runId === e.runId)!,
        );
        cleanups.push(() => {
          stop();
          activeStreams.delete(e.runId);
        });
      }
    }
    return () => cleanups.forEach((fn) => fn());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries.map((e) => `${e.runId}:${e.status}`).join(",")]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [entries]);

  async function submit(text?: string) {
    const p = (text ?? prompt).trim();
    if (!p || sending) return;
    setSending(true);
    try {
      const run = await api.createRun(p);
      onEntriesChange((prev) => [
        ...prev,
        {
          runId: run.run_id,
          prompt: p,
          status: "running",
          liveText: "",
          finalText: "",
          tools: [],
          error: null,
        },
      ]);
      setPrompt("");
    } catch (err) {
      alert(`failed to start run: ${err}`);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="flex-1 space-y-7 overflow-y-auto px-5 py-6">
        {entries.length === 0 && (
          <div className="mx-auto mt-20 max-w-lg text-center">
            <div className="anim-rise font-mono text-[11px] uppercase tracking-[0.3em] text-faint">
              channel open — awaiting instruction
            </div>
            <div className="mt-6 flex flex-col items-center gap-2">
              {suggestionsFor(user).map((s, i) => (
                <button
                  key={s}
                  onClick={() => submit(s)}
                  className="anim-rise w-fit border border-line bg-panel/70 px-3.5 py-1.5 font-mono text-xs text-dim transition hover:border-solar hover:text-solar hover:shadow-[0_0_16px_rgb(255_182_39/0.1)]"
                  style={{ animationDelay: `${120 + i * 90}ms` }}
                >
                  ▸ {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {entries.map((e, i) => (
          <EntryView key={e.runId} entry={e} index={i} />
        ))}
      </div>

      <div className="border-t border-line bg-panel/90 p-3 backdrop-blur-sm">
        <div className="flex items-end gap-2">
          <span className="pb-2.5 font-mono text-sm text-solar">▸</span>
          <textarea
            className="max-h-36 min-h-[2.6rem] flex-1 resize-y border border-line bg-raise/80 px-3 py-2 font-mono text-[13px] text-ink placeholder:text-faint focus:border-solar focus:outline-none focus:shadow-[0_0_20px_rgb(255_182_39/0.07)]"
            placeholder="query the fleet… energy, irradiance, costs, revenue, reports"
            value={prompt}
            rows={1}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <button
            onClick={() => submit()}
            disabled={sending || !prompt.trim()}
            className="border border-solar bg-solar/10 px-5 py-2 font-display text-xs font-semibold uppercase tracking-[0.2em] text-solar transition hover:bg-solar hover:text-abyss disabled:cursor-not-allowed disabled:opacity-30"
          >
            send
          </button>
        </div>
        <p className="mt-1.5 pl-5 font-mono text-[10px] text-faint">
          runs continue server-side — refresh or navigate away and reattach anytime
        </p>
      </div>
    </div>
  );
}

// Module-level registry so re-renders don't double-subscribe a run.
const activeStreams = new Set<string>();

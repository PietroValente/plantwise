import { useCallback, useEffect, useState } from "react";
import { api, getStoredUserId, setStoredUserId } from "./api";
import ChatWindow from "./components/ChatWindow";
import RunHistory from "./components/RunHistory";
import UserSelector from "./components/UserSelector";
import type { ChatEntry, DocumentInfo, LoginUser, Run } from "./types";

function SunMark({ size = 26 }: { size?: number }) {
  return (
    <svg
      className="sun-mark"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
    >
      <circle cx="12" cy="12" r="4.2" fill="var(--color-solar)" />
      {Array.from({ length: 8 }, (_, i) => {
        const a = (i * Math.PI) / 4;
        const x1 = 12 + Math.cos(a) * 6.8;
        const y1 = 12 + Math.sin(a) * 6.8;
        const x2 = 12 + Math.cos(a) * 9.6;
        const y2 = 12 + Math.sin(a) * 9.6;
        return (
          <line
            key={i}
            x1={x1} y1={y1} x2={x2} y2={y2}
            stroke="var(--color-solar)"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        );
      })}
    </svg>
  );
}

/** Fake-login as a switchboard: one card per user, grouped by company. */
function Welcome({
  users,
  loading,
  onSelect,
}: {
  users: LoginUser[];
  loading: boolean;
  onSelect: (id: string) => void;
}) {
  const companies = [...new Set(users.map((u) => u.company_id))];
  return (
    <div className="relative z-10 mx-auto flex max-w-3xl flex-1 flex-col items-center justify-center px-6">
      <div className="anim-rise mb-2 flex items-center gap-3">
        <SunMark size={40} />
        <h2 className="font-display text-4xl font-bold uppercase tracking-[0.18em] text-ink">
          Plantwise
        </h2>
      </div>
      <p className="anim-rise mb-10 font-mono text-xs uppercase tracking-[0.3em] text-dim" style={{ animationDelay: "80ms" }}>
        solar operations console
      </p>

      {loading && (
        <div className="anim-rise flex items-center gap-2.5 border border-line bg-panel/80 px-5 py-3 font-mono text-xs uppercase tracking-[0.2em] text-dim">
          <span className="led led--pulse" />
          connecting to backend…
        </div>
      )}

      <div className="grid w-full gap-6 sm:grid-cols-2">
        {companies.map((cid, ci) => (
          <section
            key={cid}
            className="anim-rise brackets border border-line bg-panel/80 p-5 backdrop-blur-sm"
            style={{ animationDelay: `${160 + ci * 110}ms` }}
          >
            <h3 className="mb-4 font-display text-sm font-semibold uppercase tracking-[0.2em] text-solar">
              {users.find((u) => u.company_id === cid)?.company_name}
            </h3>
            <div className="space-y-2.5">
              {users.filter((u) => u.company_id === cid).map((u) => (
                <button
                  key={u.user_id}
                  onClick={() => onSelect(u.user_id)}
                  className="group flex w-full items-center justify-between border border-line bg-raise/60 px-3.5 py-2.5 text-left transition hover:border-solar hover:bg-raise hover:shadow-[0_0_18px_rgb(255_182_39/0.12)]"
                >
                  <span>
                    <span className="block font-mono text-sm text-ink group-hover:text-solar">
                      {u.role}
                    </span>
                    <span className="block font-mono text-[10px] text-faint">{u.email}</span>
                  </span>
                  <span
                    className={`font-mono text-[10px] uppercase tracking-wider ${
                      u.access_scope === "energy+financial" ? "text-solar" : "text-led"
                    }`}
                  >
                    {u.access_scope}
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>

      <p className="anim-rise mt-10 max-w-md text-center font-mono text-[11px] leading-relaxed text-faint" style={{ animationDelay: "420ms" }}>
        Identity here is a demo selector — tenancy and the financial-data
        boundary are enforced by PostgreSQL row-level security, not by this screen.
      </p>
    </div>
  );
}

export default function App() {
  const [users, setUsers] = useState<LoginUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [userId, setUserId] = useState<string | null>(getStoredUserId());
  const [runs, setRuns] = useState<Run[]>([]);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [entries, setEntries] = useState<ChatEntry[]>([]);

  // Retry until the backend is reachable: on a cold `docker compose up` the
  // first request can land before the API is ready, and a silent failure here
  // would leave the operator dropdown empty until a manual reload.
  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    function load() {
      api
        .listUsers()
        .then((us) => {
          if (cancelled) return;
          setUsers(us);
          setUsersLoading(false);
        })
        .catch((err) => {
          console.error(err);
          if (cancelled) return;
          if (attempt >= 10) {
            setUsersLoading(false);
            return;
          }
          attempt += 1;
          setTimeout(load, Math.min(1000 * attempt, 5000));
        });
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshSidebar = useCallback(() => {
    if (!getStoredUserId()) return;
    api.listRuns().then(setRuns).catch(console.error);
    api.listDocuments().then(setDocuments).catch(console.error);
  }, []);

  // Switching user = switching tenant: everything user-specific resets, and
  // any running runs of the new user auto-reattach to their streams.
  useEffect(() => {
    setEntries([]);
    setRuns([]);
    setDocuments([]);
    if (!userId) return;
    api
      .listRuns()
      .then((rs) => {
        setRuns(rs);
        const running = rs.filter((r) => r.status === "running");
        setEntries(
          running.map((r) => ({
            runId: r.run_id,
            prompt: r.prompt,
            status: "running" as const,
            liveText: "",
            finalText: "",
            tools: [],
            error: null,
          })),
        );
      })
      .catch(console.error);
    api.listDocuments().then(setDocuments).catch(console.error);
  }, [userId]);

  function selectUser(id: string) {
    setStoredUserId(id);
    setUserId(id);
  }

  function openRun(run: Run) {
    setEntries((prev) => {
      if (prev.some((e) => e.runId === run.run_id)) return prev;
      return [
        ...prev,
        {
          runId: run.run_id,
          prompt: run.prompt,
          // Mark running so ChatWindow attaches a stream; completed runs
          // replay their stored chunks and then close.
          status: "running",
          liveText: "",
          finalText: "",
          tools: [],
          error: run.error,
        },
      ];
    });
  }

  return (
    <div className="relative flex h-full flex-col">
      <header className="relative z-10 flex items-center justify-between bg-panel/90 px-4 py-2.5 backdrop-blur-sm">
        <div className="flex items-center gap-2.5">
          <SunMark />
          <div>
            <h1 className="font-display text-base font-bold uppercase leading-none tracking-[0.22em] text-ink">
              Plantwise
            </h1>
            <span className="font-mono text-[9px] uppercase tracking-[0.28em] text-faint">
              solar ops console
            </span>
          </div>
        </div>
        <UserSelector users={users} loading={usersLoading} selected={userId} onSelect={selectUser} />
      </header>
      <div className="scanline relative z-10" />

      {!userId ? (
        <Welcome users={users} loading={usersLoading} onSelect={selectUser} />
      ) : (
        <div className="relative z-10 flex min-h-0 flex-1">
          <main className="min-w-0 flex-1">
            <ChatWindow
              user={users.find((u) => u.user_id === userId)}
              entries={entries}
              onEntriesChange={setEntries}
              onRunFinished={refreshSidebar}
            />
          </main>
          <aside className="hidden w-80 shrink-0 border-l border-line bg-panel/60 md:block">
            <RunHistory
              runs={runs}
              documents={documents}
              openRunIds={new Set(entries.map((e) => e.runId))}
              onOpenRun={openRun}
            />
          </aside>
        </div>
      )}
    </div>
  );
}

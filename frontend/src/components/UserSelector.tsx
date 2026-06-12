import type { LoginUser } from "../types";

interface Props {
  users: LoginUser[];
  loading: boolean;
  selected: string | null;
  onSelect: (userId: string) => void;
}

/** The fake login (Decision 3): pick a user, stored in localStorage, sent as
 * X-User-ID. The real boundary is RLS server-side. */
export default function UserSelector({ users, loading, selected, onSelect }: Props) {
  const current = users.find((u) => u.user_id === selected);
  return (
    <div className="flex items-center gap-3">
      {current && (
        <span
          className={`hidden items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider sm:flex ${
            current.access_scope === "energy+financial" ? "text-solar" : "text-led"
          }`}
          title="Access scope gates financial data at the database layer (RLS)"
        >
          <span className="led" />
          {current.access_scope}
        </span>
      )}
      <label className="flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-faint">
          operator
        </span>
        {loading ? (
          <span className="flex items-center gap-2 border border-line bg-raise px-3 py-1.5 font-mono text-xs text-dim">
            <span className="led led--pulse" />
            connecting…
          </span>
        ) : (
          <select
            className="cursor-pointer border border-line bg-raise px-3 py-1.5 font-mono text-xs text-ink transition hover:border-solar focus:border-solar focus:outline-none"
            value={selected ?? ""}
            onChange={(e) => onSelect(e.target.value)}
            title="Switch operator"
          >
            <option value="" disabled>
              — select operator —
            </option>
            {users.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.company_name} / {u.role}
              </option>
            ))}
          </select>
        )}
      </label>
    </div>
  );
}

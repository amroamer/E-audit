import { NavLink } from "react-router-dom";

/** The lifecycle, in order. A case is worked left to right: understand who this is and what
 *  we already hold, decide what to ask for and chase it, then reconcile and conclude. */
const TABS = [
  { to: "/intake", label: "Intake", hint: "Who they are, what arrived" },
  { to: "", label: "Dossier", hint: "What ZATCA already holds" },
  { to: "/casework", label: "Casework", hint: "Request, response, gaps" },
  { to: "/reconciliation", label: "Reconciliation", hint: "What qualifies, and what it means" },
];

export default function CaseTabs({ id }: { id: string }) {
  return (
    <div className="casetabs">
      {TABS.map((t) => (
        <NavLink
          key={t.label}
          to={`/cases/${id}${t.to}`}
          end={t.to === ""}
          className={({ isActive }) => "casetab" + (isActive ? " active" : "")}
        >
          <b>{t.label}</b>
          <small>{t.hint}</small>
        </NavLink>
      ))}
    </div>
  );
}

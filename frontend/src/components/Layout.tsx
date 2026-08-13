import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

const NAV = [
  { to: "/", label: "Overview", end: true, icon: "▣" },
  { to: "/cases/CASE-2025-0481", label: "Reconciliation", end: false, icon: "▦" },
  { to: "/rules", label: "Rulebook", end: false, icon: "▤" },
];
const SOON = ["Case queue", "Draft reports", "Auditor approval"];

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <span className="mark">ZC</span>
          <span>
            <b>ZATCA</b>
            <small>VAT Audit Agent</small>
          </span>
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => "navlink" + (isActive ? " active" : "")}
            >
              <span className="ic">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
          <div className="navgroup">Coming next</div>
          {SOON.map((s) => (
            <span key={s} className="navlink disabled">
              <span className="ic">◦</span>
              {s}
            </span>
          ))}
        </nav>
        <div className="side-foot">Phase 0 · Foundation</div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

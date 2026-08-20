import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Overview from "./pages/Overview";
import Rules from "./pages/Rules";
import Reconciliation from "./pages/Reconciliation";
import Dossier from "./pages/Dossier";
import Casework from "./pages/Casework";
import Intake from "./pages/Intake";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        {/* a case is worked in lifecycle order: what we hold → what we ask for → what it means */}
        <Route path="/cases/:id" element={<Dossier />} />
        <Route path="/cases/:id/intake" element={<Intake />} />
        <Route path="/cases/:id/casework" element={<Casework />} />
        <Route path="/cases/:id/reconciliation" element={<Reconciliation />} />
        <Route path="/rules" element={<Rules />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

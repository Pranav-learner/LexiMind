// Reusable Verification Inspector panel (Phase 6, Module 3). Renders a VerificationReport:
// status + confidence breakdown, claim→evidence mapping, contradictions, citation validation,
// warnings/recommendations, and structured reasoning metadata. Used both inside the Agent Workspace
// (verification tab) and the standalone Verification Inspector page.
import { useState } from "react";
import {
  CLAIM_STATUS_COLOR, STATUS_META, confidenceColor,
  type VerificationReport,
} from "../../api/verification";
import "../../styles/verification.css";

type Sub = "overview" | "claims" | "evidence" | "contradictions" | "citations" | "reasoning";

export default function VerificationPanel({ report }: { report: VerificationReport }) {
  const [sub, setSub] = useState<Sub>("overview");
  const meta = STATUS_META[report.status] ?? STATUS_META.warning;
  const conf = report.confidence;

  return (
    <div className="vf-panel">
      <div className="vf-head">
        <span className="vf-status" style={{ background: meta.color }}>{meta.icon} {meta.label}</span>
        <div className="vf-conf-badge">
          <span className="vf-conf-num" style={{ color: confidenceColor(conf.overall) }}>
            {Math.round(conf.overall * 100)}%
          </span>
          <span className="vf-conf-lbl">confidence · {conf.band}</span>
        </div>
        <span className="vf-mode">mode: {report.mode}</span>
      </div>

      <div className="vf-counts">
        <Count label="claims" n={report.claims_total} />
        <Count label="supported" n={report.counts.supported} color="#10b981" />
        <Count label="weak" n={report.counts.weakly_supported} color="#f59e0b" />
        <Count label="unsupported" n={report.counts.unsupported} color="#ef4444" />
        <Count label="conflicting" n={report.counts.conflicting} color="#dc2626" />
        <Count label="contradictions" n={report.contradictions.length} color="#dc2626" />
      </div>

      <nav className="vf-tabs">
        {(["overview", "claims", "evidence", "contradictions", "citations", "reasoning"] as Sub[]).map((s) => (
          <button key={s} className={sub === s ? "is-active" : ""} onClick={() => setSub(s)}>{s}</button>
        ))}
      </nav>

      {sub === "overview" && (
        <div className="vf-body">
          <p className="vf-explain">{conf.explanation}</p>
          <h5>Confidence signals</h5>
          <div className="vf-signals">
            {conf.signals.map((s) => (
              <div className="vf-signal" key={s.name}>
                <span className="vf-signal-name">{s.name.replace(/_/g, " ")}</span>
                <div className="vf-bar"><div className="vf-bar-fill"
                  style={{ width: `${Math.round(s.value * 100)}%`, background: confidenceColor(s.value) }} /></div>
                <span className="vf-signal-val">{Math.round(s.value * 100)}%</span>
                <span className="vf-signal-w">×{s.weight.toFixed(2)}</span>
              </div>
            ))}
          </div>
          {report.warnings.length > 0 && (
            <><h5>Warnings</h5><ul className="vf-warn">{report.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}</ul></>
          )}
          {report.recommendations.length > 0 && (
            <><h5>Recommendations</h5><ul className="vf-rec">{report.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul></>
          )}
          {report.review_notes.length > 0 && (
            <><h5>Self-review</h5><ul className="vf-notes">{report.review_notes.map((r, i) => <li key={i}>{r}</li>)}</ul></>
          )}
        </div>
      )}

      {sub === "claims" && (
        <div className="vf-body">
          <p className="vf-muted">Each extracted claim mapped to its supporting evidence.</p>
          <ul className="vf-claims">
            {report.claim_verdicts.map((v) => (
              <li key={v.claim.id}>
                <span className="vf-claim-status" style={{ background: CLAIM_STATUS_COLOR[v.status] }}>
                  {v.status.replace(/_/g, " ")}
                </span>
                <span className="vf-claim-text">{v.claim.text}</span>
                <span className="vf-claim-meta">
                  support {Math.round(v.support_score * 100)}%
                  {v.matched_evidence.length > 0 && ` · evidence ${v.matched_evidence.map((i) => `[${i}]`).join(" ")}`}
                  {v.claim.citation_indices.length > 0 && ` · cites ${v.claim.citation_indices.map((i) => `[${i}]`).join(" ")}`}
                </span>
                {v.rationale && <span className="vf-claim-why">{v.rationale}</span>}
              </li>
            ))}
            {report.claim_verdicts.length === 0 && <li className="vf-muted">No claims extracted.</li>}
          </ul>
        </div>
      )}

      {sub === "evidence" && (
        <div className="vf-body">
          <ul className="vf-evidence-tree">
            {report.evidence.map((e) => (
              <li key={e.index}>
                <span className="vf-ev-idx">[{e.index}]</span>
                <span className="vf-ev-mod">{e.modality}</span>
                <span className="vf-ev-text">{e.text}</span>
                <span className="vf-ev-meta">
                  {e.title ?? e.document_id ?? "source"}
                  {e.page_number != null ? ` · p${e.page_number}` : ""}
                  {e.timespan ? ` · ${e.timespan}` : ""} · score {e.score.toFixed(2)}
                </span>
              </li>
            ))}
            {report.evidence.length === 0 && <li className="vf-muted">No evidence.</li>}
          </ul>
        </div>
      )}

      {sub === "contradictions" && (
        <div className="vf-body">
          {report.contradictions.length === 0 && <p className="vf-muted">No contradictions detected.</p>}
          <ul className="vf-contra">
            {report.contradictions.map((c, i) => (
              <li key={i} className={`sev-${c.severity}`}>
                <span className="vf-contra-head">{c.kind.replace(/_/g, " ")} · {c.severity} · {c.reason}</span>
                <span className="vf-contra-desc">{c.description}</span>
                <div className="vf-contra-pair">
                  <div>{c.left_ref != null ? `[${c.left_ref}] ` : ""}{c.left}</div>
                  <div>{c.right_ref != null ? `[${c.right_ref}] ` : ""}{c.right}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {sub === "citations" && (
        <div className="vf-body">
          {report.citation_issues.length === 0 && <p className="vf-muted">All citations valid.</p>}
          <ul className="vf-cite-issues">
            {report.citation_issues.map((c, i) => (
              <li key={i} className={`sev-${c.severity}`}>
                <span className="vf-cite-type">{c.issue_type}</span>
                <span className="vf-cite-detail">{c.detail}</span>
              </li>
            ))}
          </ul>
          {report.missing_evidence.length > 0 && (
            <><h5>Claims missing evidence</h5>
              <ul className="vf-missing">{report.missing_evidence.map((m, i) => <li key={i}>{m}</li>)}</ul></>
          )}
        </div>
      )}

      {sub === "reasoning" && (
        <div className="vf-body">
          <p className="vf-muted">Structured reasoning metadata (no chain-of-thought).</p>
          <pre className="vf-json">{JSON.stringify(report.explanations, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

function Count({ label, n, color }: { label: string; n: number; color?: string }) {
  return (
    <div className="vf-count">
      <span className="vf-count-n" style={color ? { color } : undefined}>{n}</span>
      <span className="vf-count-l">{label}</span>
    </div>
  );
}

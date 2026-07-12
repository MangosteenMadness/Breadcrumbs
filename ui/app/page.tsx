"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import {
  F,
  E,
  byId,
  COL,
  LABEL,
  STEPS,
  HIST,
  type DuplicationResult,
  type Finding,
} from "@/lib/data";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

/* ---- stream item model ---- */
type StreamItem =
  | { kind: "user"; id: number; text: string }
  | { kind: "think"; id: number; revealed: number; done: boolean }
  | { kind: "answer"; id: number; res: DuplicationResult }
  | { kind: "error"; id: number; msg: string };

async function callCheckDuplication(
  hypothesis_text: string,
  forcedId?: string,
): Promise<DuplicationResult> {
  const res = await fetch("/api/check_duplication", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hypothesis_text, forcedId }),
  });
  if (!res.ok) throw new Error("Breadcrumbs API error " + res.status);
  return res.json();
}

export default function Home() {
  const [items, setItems] = useState<StreamItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const [highlight, setHighlight] = useState<string[]>([]);

  const streamRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(0);
  const nextId = () => ++idRef.current;

  // keep the stream pinned to the bottom as it grows
  useEffect(() => {
    const s = streamRef.current;
    if (s) s.scrollTop = s.scrollHeight;
  }, [items]);

  // questions grouped by category for the "Explore MOSAIC" sidebar
  const groups = useMemo(() => {
    const g: Record<string, Finding[]> = {};
    F.forEach((f) => {
      (g[f.cat] = g[f.cat] || []).push(f);
    });
    return Object.entries(g);
  }, []);

  const patch = (id: number, next: Partial<StreamItem>) =>
    setItems((prev) => prev.map((it) => (it.id === id ? ({ ...it, ...next } as StreamItem) : it)));

  async function ask(text: string, forcedId?: string) {
    if (busy) return;
    setBusy(true);
    setHighlight([]);

    setItems((prev) => [...prev, { kind: "user", id: nextId(), text }]);
    await wait(400);

    const thinkId = nextId();
    setItems((prev) => [...prev, { kind: "think", id: thinkId, revealed: 0, done: false }]);

    // fire the call and animate in parallel — real backend latency just fills the animation
    const pending = callCheckDuplication(text, forcedId).catch(
      (err) => ({ __error: String(err) }) as unknown as DuplicationResult,
    );

    for (let i = 0; i < STEPS.length; i++) {
      await wait(500);
      patch(thinkId, { revealed: i + 1 });
    }

    const res = await pending;
    patch(thinkId, { revealed: STEPS.length, done: true });

    const err = (res as unknown as { __error?: string }).__error;
    if (err) {
      setItems((prev) => [...prev, { kind: "error", id: nextId(), msg: err }]);
      setHighlight([]);
    } else {
      setItems((prev) => [...prev, { kind: "answer", id: nextId(), res }]);
      setHighlight((res.matches ?? []).map((mm) => mm.id).filter((id) => byId[id]));
    }
    setBusy(false);
  }

  const submit = () => {
    const t = input.trim();
    if (!t) return;
    setInput("");
    ask(t);
  };

  const gstatus = highlight.length
    ? `// ${highlight.length} marker${highlight.length > 1 ? "s" : ""} on your path`
    : "// your org's explored ground";

  return (
    <div className="app">
      {/* ================= SIDEBAR ================= */}
      <aside className="col side">
        <div className="brand">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path
              d="M3 20 C7 14, 5 9, 11 6 S 19 5, 21 3"
              stroke="#9BA694"
              strokeWidth="2"
              strokeDasharray="2 5"
              strokeLinecap="round"
            />
            <circle cx="3" cy="20" r="2.4" fill="#657262" />
            <circle cx="11" cy="6" r="3" fill="#C6862B" />
            <circle cx="21" cy="3" r="2.4" fill="#A7AFA2" />
          </svg>
          Breadcrumbs
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="brand-logo" src="/owkin-logo.svg" alt="Owkin" />
        </div>

        <div className="side-sub">Session history</div>
        <div>
          {HIST.map((h, i) => (
            <div className="hist" key={i}>
              <div className="ht">{h.t}</div>
              <div className="hm">{h.m}</div>
            </div>
          ))}
        </div>

        <div className="side-sub">Explore MOSAIC</div>
        <div>
          {groups.map(([cat, list]) => (
            <div className="qgroup" key={cat}>
              <div className="qg-lab">{cat}</div>
              {list.map((f) => (
                <button
                  className="qbtn"
                  key={f.id}
                  onClick={() => {
                    setInput("");
                    ask(f.q, f.id);
                  }}
                >
                  {f.q.length > 92 ? f.q.slice(0, 92) + "…" : f.q}
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* ================= CHAT ================= */}
      <main className="col chat">
        <div className="chat-head">
          <h2>Retrace</h2>
          <div className="sesstag">
            <i />New session · Dr. Chen · nothing in context
          </div>
        </div>

        <div className="stream" ref={streamRef}>
          {items.length === 0 && (
            <div className="empty">
              <h3>Ask before you run.</h3>
              <p>
                Breadcrumbs checks your organization&apos;s own trail first — including what
                colleagues abandoned — before it checks the published world.
              </p>
            </div>
          )}

          {items.map((it) => {
            if (it.kind === "user") {
              return (
                <div className="msg user" key={it.id}>
                  <div className="bub">{it.text}</div>
                </div>
              );
            }
            if (it.kind === "think") return <ThinkBlock key={it.id} item={it} />;
            if (it.kind === "error") {
              return (
                <div className="msg" key={it.id}>
                  <div className="ans">
                    <div className="verdict open">
                      <span className="vm" />
                      Couldn&apos;t reach the trail
                    </div>
                    <div className="card openp">
                      <div className="q">The Breadcrumbs server didn&apos;t respond.</div>
                      <div className="e mono" style={{ fontSize: 12 }}>
                        {it.msg}
                      </div>
                    </div>
                  </div>
                </div>
              );
            }
            return <AnswerBlock key={it.id} res={it.res} />;
          })}
        </div>

        <div className="composer">
          <div className="cwrap">
            <input
              className="cin"
              placeholder="Ask a research question…"
              autoComplete="off"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
            />
            <button className="cbtn" onClick={submit} disabled={busy}>
              Retrace
            </button>
          </div>
        </div>
      </main>

      {/* ================= GRAPH ================= */}
      <aside className="col gcol">
        <div className="gh">
          <h3>The trail</h3>
          <span className="gc">22 markers</span>
        </div>
        <div className="gsub">{gstatus}</div>

        <TrailGraph highlight={highlight} onPick={(f) => ask(f.q, f.id)} />

        <div className="legend">
          <div className="lrow">
            <span className="d" style={{ background: "#657262" }} />
            confirmed finding
          </div>
          <div className="lrow">
            <span className="d" style={{ background: "#C6862B" }} />
            matches your question
          </div>
          <div className="lrow">
            <span className="d" style={{ background: "#3E7A5E" }} />
            in progress right now
          </div>
          <div className="lrow">
            <span className="d" style={{ background: "#A7AFA2" }} />
            abandoned — dead end
          </div>
        </div>

        <div className="stats">
          <div className="stat">
            <b>19</b>
            <span>confirmed</span>
          </div>
          <div className="stat">
            <b>2</b>
            <span>in flight</span>
          </div>
          <div className="stat">
            <b>2</b>
            <span>dead ends</span>
          </div>
        </div>
      </aside>
    </div>
  );
}

/* ---------------- thinking block ---------------- */
function ThinkBlock({ item }: { item: Extract<StreamItem, { kind: "think" }> }) {
  return (
    <div className="msg">
      <div className="think">
        <div className="think-h">
          {item.done ? <span className="dot" /> : <span className="spin" />}
          {item.done ? "TRAIL RETRACED" : "RETRACING YOUR STEPS…"}
        </div>
        <div>
          {STEPS.slice(0, item.revealed).map((s, i) => (
            <div className={"tstep" + (item.done || i < item.revealed - 1 ? " done" : "")} key={i}>
              {s}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------------- answer block ---------------- */
function AnswerBlock({ res }: { res: DuplicationResult }) {
  // When the backend sends a markdown write-up, render it as the answer body.
  if (res.markdown) {
    return (
      <div className="msg">
        <div className="ans">
          <div className="md">
            <Markdown>{res.markdown}</Markdown>
          </div>
        </div>
      </div>
    );
  }

  const open = res.verdict === "open" || !res.matches?.length;

  if (open) {
    return (
      <div className="msg">
        <div className="ans">
          <div className="verdict open">
            <span className="vm" />
            No markers on this path — you&apos;re the first here
          </div>
          <div className="card openp">
            <div className="ch">
              <span>open trail</span>
              <span className="cid">no prior internal work</span>
            </div>
            <div className="q">
              Nothing on your org&apos;s trail matches this, and nothing in the published record
              searched.
            </div>
            <div className="e">
              This path looks open. As you explore it, Breadcrumbs drops a marker — so the next
              person who asks finds <em>you</em>.
            </div>
          </div>
          <div className="calib">
            {"// Breadcrumbs doesn't cry duplicate. When a path is new, it says so — and starts mapping it."}
          </div>
        </div>
      </div>
    );
  }

  const m = res.matches;
  const n = m.length;
  return (
    <div className="msg">
      <div className="ans">
        <div className="verdict">
          <span className="vm" />
          {n} marker{n > 1 ? "s" : ""} on your trail — you&apos;re not the first here
        </div>

        {m.map((f, i) => {
          const L = LABEL[f.status] || LABEL.confirmed;
          const tag = i === 0 ? L.tag : f.status === "confirmed" ? "related work" : L.tag;
          return (
            <div className={`card ${L.cls}`} key={f.id + "-" + i}>
              <div className="ch">
                <span>{tag}</span>
                <span className="cid">
                  {f.id} · {f.author || ""} {f.disease ? "· " + f.disease : ""}
                </span>
              </div>
              <div className="q">{f.hypothesis_text}</div>
              {f.effect && <div className="e" dangerouslySetInnerHTML={{ __html: f.effect }} />}
              {f.reason && <div className="r" dangerouslySetInnerHTML={{ __html: f.reason }} />}
            </div>
          );
        })}

        {res.external && (
          <div className="ext">
            <b>published record</b>
            <span dangerouslySetInnerHTML={{ __html: res.external }} />
          </div>
        )}
        <div className="calib">
          {"// no claim of novelty — Breadcrumbs reports what it found on your trail, and what it didn't."}
          <br />
          {`// internal checked first · ${res.searched ?? "—"} markers searched · external second`}
        </div>
      </div>
    </div>
  );
}

/* ---------------- trail graph ---------------- */
function TrailGraph({
  highlight,
  onPick,
}: {
  highlight: string[];
  onPick: (f: Finding) => void;
}) {
  const active = highlight.length > 0;
  const hset = new Set(highlight);

  return (
    <svg className="graph" viewBox="0 0 380 520">
      {E.map(([a, b, r], i) => {
        const A = byId[a];
        const B = byId[b];
        const dup = r === "duplicate_of";
        const dim = active && !(hset.has(a) && hset.has(b));
        return (
          <line
            key={i}
            className={"gedge" + (dim ? " dim" : "")}
            x1={A.x}
            y1={A.y}
            x2={B.x}
            y2={B.y}
            stroke={dup ? "#7d8a78" : "#3d4a3f"}
            strokeWidth={dup ? 1.5 : 1}
            strokeDasharray={dup ? "3 3" : undefined}
          />
        );
      })}

      {F.map((f) => {
        const on = hset.has(f.id);
        const dim = active && !on;
        const baseFill = COL[f.st];
        const litFill = f.st === "abandoned" ? COL.abandoned : COL.match;
        return (
          <g className={"gnode" + (dim ? " dim" : "")} key={f.id} onClick={() => onPick(f)}>
            {on && <circle className="ring" cx={f.x} cy={f.y} r={6} fill={litFill} />}
            <circle
              cx={f.x}
              cy={f.y}
              r={f.st === "in_progress" ? 5.5 : 5}
              fill={on ? litFill : baseFill}
            />
            {f.st === "abandoned" && (
              <path
                d={`M${f.x - 2.6} ${f.y - 2.6} l5.2 5.2 M${f.x + 2.6} ${f.y - 2.6} l-5.2 5.2`}
                stroke="#121A12"
                strokeWidth={1.3}
                strokeLinecap="round"
              />
            )}
            {f.st === "in_progress" && !on && (
              <circle className="ring" cx={f.x} cy={f.y} r={5.5} fill={COL.in_progress} />
            )}
            <title>{`${f.id} · ${f.dis} · ${f.st}`}</title>
          </g>
        );
      })}
    </svg>
  );
}

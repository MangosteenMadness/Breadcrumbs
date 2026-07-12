"use client";

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  hydrateFigure,
  type Block,
  type PlotFigure,
  type Session,
} from "@/lib/sessions";

/* ============================================================
   K Pro transcript view — replays a stored session with its real charts.

   Every block here comes verbatim from breadcrumbs.db (see ingestion/export_sessions.py). The
   Plotly figures are the exact objects K Pro drew; rendering them with Plotly.js reproduces the
   chart with no auth and no network. Heavy plots stripped at ingest render as an honest
   "omitted" placeholder rather than a blank.
   ============================================================ */

/** One Plotly figure, drawn client-side. Plotly is browser-only, so it is imported lazily
    inside the effect — never at module load, where it would break server rendering. */
function PlotBlock({ figure, title }: { figure: PlotFigure; title?: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    const node = ref.current;
    if (!node) return;

    (async () => {
      try {
        const mod = await import("plotly.js-dist-min");
        const Plotly = mod.default ?? (mod as unknown as typeof mod.default);
        if (disposed) return;
        const f = hydrateFigure(figure);
        // Let the figure fill the card width and reflow on resize; keep everything else K Pro set.
        const layout = { ...(f.layout ?? {}), autosize: true };
        delete (layout as Record<string, unknown>).width;
        delete (layout as Record<string, unknown>).height;
        await Plotly.newPlot(node, f.data, layout, {
          responsive: true,
          displaylogo: false,
          displayModeBar: false,
        });
      } catch (err) {
        if (!disposed) setError(String(err));
      }
    })();

    return () => {
      disposed = true;
      import("plotly.js-dist-min")
        .then((mod) => (mod.default ?? mod).purge(node))
        .catch(() => {});
    };
  }, [figure]);

  if (error) {
    return (
      <div className="tk-omit">
        <span className="tk-omit-tag">chart failed to render</span>
        <span className="tk-omit-meta mono">{error}</span>
      </div>
    );
  }

  return (
    <figure className="tk-plot">
      {title && <figcaption className="tk-plot-cap">{title}</figcaption>}
      <div className="tk-plot-canvas" ref={ref} />
    </figure>
  );
}

const TABLE_PREVIEW_ROWS = 5;

function DataTableBlock({
  columns,
  rows,
  title,
}: {
  columns: string[];
  rows: (string | number | null)[][];
  title?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasMore = rows.length > TABLE_PREVIEW_ROWS;
  const visibleRows = expanded ? rows : rows.slice(0, TABLE_PREVIEW_ROWS);

  return (
    <figure className="tk-table-wrap">
      {title && <figcaption className="tk-plot-cap">{title}</figcaption>}
      <div className="tk-table-scroll">
        <table className="tk-table">
          <thead>
            <tr>
              {columns.map((c, i) => (
                <th key={i}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, c) => (
                  <td key={c}>{cell === null ? "" : String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasMore && (
        <button className="tk-table-more" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show less" : `Show more (${rows.length - TABLE_PREVIEW_ROWS} more rows)`}
        </button>
      )}
    </figure>
  );
}

function OmittedBlock({ blockType, bytes }: { blockType: string; bytes?: number | null }) {
  const size = typeof bytes === "number" ? ` · ${(bytes / 1024).toFixed(0)} KB` : "";
  return (
    <div className="tk-omit">
      <span className="tk-omit-tag">{blockType} omitted</span>
      <span className="tk-omit-meta mono">
        heavy render stripped at ingest to keep the store small{size}
      </span>
    </div>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case "text":
      return (
        <div className="tk-md">
          <Markdown remarkPlugins={[remarkGfm]}>{block.text}</Markdown>
        </div>
      );
    case "suggestion":
      return <div className="tk-suggest">{block.text}</div>;
    case "plot":
      return <PlotBlock figure={block.figure} title={block.title} />;
    case "table":
      return <DataTableBlock columns={block.columns} rows={block.rows} title={block.title} />;
    case "omitted":
      return <OmittedBlock blockType={block.blockType} bytes={block.bytes} />;
  }
}

export function SessionTranscript({
  session,
  onClose,
}: {
  session: Session;
  onClose: () => void;
}) {
  // Close on Escape, and lock the page behind the overlay from scrolling.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  const { plots, tables, omitted } = session.counts;
  const chips = [
    plots ? `${plots} chart${plots > 1 ? "s" : ""}` : null,
    tables ? `${tables} table${tables > 1 ? "s" : ""}` : null,
    omitted ? `${omitted} omitted` : null,
  ].filter(Boolean);

  return (
    <div className="tk-overlay" onClick={onClose}>
      <div className="tk-modal" onClick={(e) => e.stopPropagation()}>
        <header className="tk-head">
          <div>
            <div className="tk-eyebrow mono">the actual K Pro run · replayed from the store</div>
            <h2 className="tk-title">{session.title || "K Pro session"}</h2>
            <div className="tk-meta mono">
              {session.researcher ? `${session.researcher} · ` : ""}
              {chips.join(" · ")}
            </div>
          </div>
          <button className="tk-close" onClick={onClose} aria-label="Close transcript">
            ✕
          </button>
        </header>

        <div className="tk-body">
          {session.turns.map((turn, ti) => (
            <div className={`tk-turn tk-${turn.role}`} key={ti}>
              <div className="tk-role mono">{turn.role === "user" ? "Researcher" : "K Pro"}</div>
              <div className="tk-blocks">
                {turn.blocks.map((block, bi) => (
                  <BlockView block={block} key={bi} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

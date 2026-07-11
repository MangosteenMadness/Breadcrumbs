/* ============================================================
   Breadcrumbs — seeded trail data (11 pairs, 22 findings)
   Ported verbatim from the original demo UI. This is the local
   stand-in the mock resolves against; the real trail lives in
   the SQLite MCP server. See lib/duplication.ts.
   ============================================================ */

export type Status = "confirmed" | "in_progress" | "abandoned";
export type Relationship = "duplicate_of" | "extends" | "related";

export interface Finding {
  id: string;
  cat: string;
  dis: string;
  q: string;
  ent: string[];
  eff: string;
  rz?: string; // reason — populated for abandoned findings
  st: Status;
  au: string;
  x: number;
  y: number;
}

/** One matched marker returned by check_duplication. */
export interface Match {
  id: string;
  status: Status;
  relationship: Relationship;
  hypothesis_text: string;
  effect: string;
  reason: string | null;
  author: string;
  disease: string;
}

/** The exact contract the UI renders against — from the MCP or the mock. */
export interface DuplicationResult {
  verdict: "match" | "open";
  matches: Match[];
  external?: string;
  searched: number;
}

export const F: Finding[] = [
  { id: "F-201", cat: "CXCL13 spatial", dis: "DLBCL", q: "Do MOSAIC DLBCL tumors show organized follicle-like structures (CXCL13+ B cell aggregates) spatially, and which patients have them?", ent: ["CXCL13", "B_cell"], eff: "~35% of patients show organized CXCL13+ aggregates resembling tertiary lymphoid structures, localized peri-tumorally.", st: "confirmed", au: "A. Rahman", x: 70, y: 52 },
  { id: "F-202", cat: "CXCL13 spatial", dis: "OV", q: "In MOSAIC OV, do CXCL13+ T cells cluster at tumor borders and does this associate with immune infiltration?", ent: ["CXCL13", "T_cell"], eff: "CXCL13+ T cells enriched at invasive margins; border clustering tracks with higher TIL density.", st: "confirmed", au: "A. Rahman", x: 104, y: 74 },

  { id: "F-203", cat: "Mutation → spatial immune", dis: "BLCA", q: "In MOSAIC BLCA, do TP53-mutant patients have a distinct spatial immune architecture compared to TP53-wildtype?", ent: ["TP53"], eff: "TP53-mutant cases show a more immune-excluded spatial pattern; wildtype more inflamed.", st: "confirmed", au: "D. Cho", x: 196, y: 42 },
  { id: "F-204", cat: "Mutation → spatial immune", dis: "GBM", q: "What is the spatial gene expression profile of MOSAIC GBM tumors with EGFR amplification vs. without?", ent: ["EGFR"], eff: "EGFR-amplified regions show elevated proliferative/invasive programs vs non-amplified.", st: "confirmed", au: "D. Cho", x: 230, y: 64 },

  { id: "F-205", cat: "Pan-cancer programs", dis: "pan-cancer", q: "Which spatial gene expression programs appear in at least 3 of the 5 MOSAIC Window cancer types?", ent: [], eff: "A hypoxia program and an immune-exclusion program recur across most types; others lineage-specific.", st: "confirmed", au: "P. Nair", x: 308, y: 56 },
  { id: "F-206", cat: "Pan-cancer programs", dis: "pan-cancer", q: "Which cell types are consistently spatially excluded from tumor cores across all MOSAIC Window cancers?", ent: ["T_cell"], eff: "Cytotoxic T cells excluded from cores across all five types; myeloid cells more core-permissive.", st: "confirmed", au: "P. Nair", x: 340, y: 80 },

  { id: "F-207", cat: "Myeloid dominance", dis: "GBM", q: "In MOSAIC GBM, what proportion of the TME is tumor-associated macrophages, and are they spatially concentrated?", ent: ["TAM", "myeloid"], eff: "TAMs ~30–40% of TME cells; concentrated in perivascular and necrosis-adjacent zones.", st: "confirmed", au: "M. Feld", x: 326, y: 170 },
  { id: "F-208", cat: "Myeloid dominance", dis: "pan-cancer", q: "Is the myeloid-to-T cell ratio in the tumor core consistently elevated across all 5 MOSAIC cancer types, or cancer-type specific?", ent: ["myeloid", "T_cell"], eff: "Analysis running now — GBM shows high core myeloid dominance; OV/BLCA less pronounced.", st: "in_progress", au: "M. Feld", x: 352, y: 196 },

  { id: "F-209", cat: "Treatment response", dis: "BLCA", q: "In MOSAIC BLCA patients who received neoadjuvant chemotherapy, what spatial features distinguish responders from non-responders?", ent: [], eff: "No robust separator found.", rz: "Responder subgroup too small — underpowered for a spatial signature. Do not re-run without pooling more BLCA neoadjuvant cases.", st: "abandoned", au: "L. Ortiz", x: 300, y: 282 },
  { id: "F-210", cat: "Treatment response", dis: "OV", q: "Do MOSAIC OV patients with higher tumor stage show more immune exclusion spatially than early-stage patients?", ent: ["T_cell"], eff: "Late-stage cases trend toward greater immune exclusion at the core; early-stage more infiltrated.", st: "confirmed", au: "L. Ortiz", x: 332, y: 306 },

  { id: "F-211", cat: "Intra-tumor heterogeneity", dis: "GBM", q: "Within a single MOSAIC GBM patient, how different is gene expression between the tumor core and the invasive margin?", ent: [], eff: "Core enriched for hypoxia/proliferation; margin for invasion and neuronal-interaction programs.", st: "confirmed", au: "M. Feld", x: 196, y: 352 },
  { id: "F-212", cat: "Intra-tumor heterogeneity", dis: "OV", q: "Do different spatial regions within the same MOSAIC OV tumor sample show distinct immune cell compositions?", ent: ["T_cell", "myeloid"], eff: "Stromal bands are T-cell-rich; epithelial nests immune-poor and myeloid-leaning.", st: "confirmed", au: "A. Rahman", x: 228, y: 376 },

  { id: "F-213", cat: "T cell exhaustion", dis: "GBM · OV", q: "What exhaustion markers (LAG3, TIM3, TIGIT) are expressed by CD8+ T cells in MOSAIC GBM and OV tumors?", ent: ["CD8A", "LAG3", "HAVCR2", "TIGIT"], eff: "Exhaustion markers co-expressed on core CD8+ T cells in both; highest in GBM cores.", st: "confirmed", au: "P. Nair", x: 78, y: 330 },
  { id: "F-214", cat: "T cell exhaustion", dis: "MESO", q: "Do MOSAIC MESO tumors have higher CAF content than other MOSAIC cancers, and does CAF density correlate with T cell exclusion?", ent: ["CAF", "T_cell"], eff: "MESO shows highest CAF fraction; CAF-dense regions coincide with T-cell-poor zones.", st: "confirmed", au: "P. Nair", x: 108, y: 356 },

  { id: "F-215", cat: "Mutation → infiltration", dis: "OV", q: "Do MOSAIC OV patients with BRCA1/2 mutations show higher tumor-infiltrating lymphocyte density spatially vs BRCA-wildtype?", ent: ["BRCA1", "BRCA2", "T_cell"], eff: "BRCA-mutant cases trend toward higher spatial TIL density; consistent with neoantigen load.", st: "confirmed", au: "D. Cho", x: 40, y: 186 },
  { id: "F-216", cat: "Mutation → infiltration", dis: "BLCA", q: "In MOSAIC BLCA, does tumor mutational burden from WES correlate with spatial immune infiltration levels?", ent: ["TMB", "T_cell"], eff: "Positive but modest correlation; several high-TMB outliers remain immunologically cold.", st: "confirmed", au: "D. Cho", x: 60, y: 214 },

  { id: "F-217", cat: "H&E → spatial bridge", dis: "GBM", q: "Is there a relationship between H&E-visible tumor grade and spatial immune infiltration density in MOSAIC GBM?", ent: [], eff: "Higher-grade H&E regions coincide with lower spatial immune density — a weak inverse relationship.", st: "confirmed", au: "L. Ortiz", x: 180, y: 242 },
  { id: "F-218", cat: "H&E → spatial bridge", dis: "BLCA", q: "In MOSAIC BLCA, what spatial features distinguish responders from non-responders in H&E alone?", ent: [], eff: "H&E-alone classifier did not separate response groups reliably.", rz: "H&E morphology alone lacks signal for response; needs paired spatial/molecular features. Same clinical question already abandoned in F-209.", st: "abandoned", au: "L. Ortiz", x: 214, y: 268 },

  { id: "F-219", cat: "Hypoxia co-localization", dis: "GBM", q: "In MOSAIC GBM, do hypoxic spatial niches (HIF1A-high) co-localize with areas of high tumor cell proliferation (MKI67-high)?", ent: ["HIF1A", "MKI67"], eff: "HIF1A-high and MKI67-high regions partially co-localize at the core–margin transition; not fully overlapping.", st: "confirmed", au: "M. Feld", x: 262, y: 142 },
  { id: "F-220", cat: "Hypoxia co-localization", dis: "OV", q: "Do MOSAIC OV patients with higher tumor stage show more hypoxic spatial signatures than early-stage patients?", ent: ["HIF1A"], eff: "Late-stage OV cases show broader hypoxic spatial signatures than early-stage.", st: "confirmed", au: "A. Rahman", x: 290, y: 166 },

  { id: "F-221", cat: "SYPL1 spatial", dis: "pan-cancer", q: "How is SYPL1 expressed in the different cell types across MOSAIC indications based on spatial transcriptomic data?", ent: ["SYPL1"], eff: "SYPL1 expression highest in epithelial/tumor compartments; low in lymphoid, variable in stroma.", st: "confirmed", au: "A. Rahman", x: 120, y: 130 },
  { id: "F-222", cat: "SYPL1 spatial", dis: "pan-cancer", q: "In MOSAIC indications where SYPL1 is highly expressed, does its spatial localization co-occur with regions of active immune suppression or stromal enrichment?", ent: ["SYPL1", "CAF", "T_cell"], eff: "Running now — early signal suggests SYPL1-high regions overlap stromal-enriched, T-cell-poor zones.", st: "in_progress", au: "S. Iqbal", x: 150, y: 156 },
];

/** edges: within-pair + cross-pair (the interesting duplicate/extends links) */
export const E: [string, string, Relationship][] = [
  ["F-202", "F-201", "related"], ["F-204", "F-203", "related"], ["F-206", "F-205", "extends"],
  ["F-208", "F-207", "extends"], ["F-210", "F-209", "related"], ["F-212", "F-211", "related"],
  ["F-214", "F-213", "related"], ["F-216", "F-215", "related"], ["F-218", "F-217", "related"],
  ["F-220", "F-219", "related"], ["F-222", "F-221", "extends"],
  /* cross-pair — the interesting ones */
  ["F-218", "F-209", "duplicate_of"],
  ["F-220", "F-210", "related"],
  ["F-216", "F-203", "related"],
  ["F-222", "F-214", "related"],
  ["F-206", "F-213", "related"],
];

export const byId: Record<string, Finding> = Object.fromEntries(F.map((f) => [f.id, f]));

export const COL: Record<string, string> = {
  confirmed: "#657262",
  in_progress: "#3E7A5E",
  abandoned: "#A7AFA2",
  match: "#C6862B",
};

export const LABEL: Record<Status, { cls: string; tag: string }> = {
  abandoned: { cls: "dead", tag: "⚑ dead end" },
  in_progress: { cls: "live", tag: "◉ a colleague is on this right now" },
  confirmed: { cls: "dup", tag: "already explored" },
};

export const STEPS = [
  "Parsing hypothesis",
  "Extracting entities",
  "Retrieving candidates from the trail",
  "Semantic match — by meaning, not keywords",
  "Checking published record (Europe PMC)",
  "Verdict ready",
];

export const HIST = [
  { t: "Cytotoxic infiltration → survival in LUAD", m: "A. Rahman · Mar 14" },
  { t: "Myeloid-to-T cell ratio across MOSAIC cancers", m: "M. Feld · Mar 14 · running" },
  { t: "SYPL1 co-occurrence with stromal enrichment", m: "S. Iqbal · Mar 12 · running" },
  { t: "BLCA neoadjuvant spatial responders", m: "L. Ortiz · Mar 15 · abandoned" },
  { t: "CAF density and T cell exclusion in MESO", m: "P. Nair · Mar 20" },
];

export function neighborsOf(id: string): { id: string; rel: Relationship }[] {
  const out: { id: string; rel: Relationship }[] = [];
  E.forEach(([a, b, r]) => {
    if (a === id) out.push({ id: b, rel: r });
    if (b === id) out.push({ id: a, rel: r });
  });
  return out;
}

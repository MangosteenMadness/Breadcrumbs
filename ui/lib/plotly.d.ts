/* plotly.js-dist-min ships no type declarations and is a browser-only CJS bundle (it touches
   `document` at load, so it must be dynamically imported inside an effect, never on the server).
   We touch only three functions, so a minimal ambient declaration keeps `strict` happy without
   the full @types/plotly.js surface. */
declare module "plotly.js-dist-min" {
  interface PlotlyStatic {
    newPlot(
      root: HTMLElement,
      data: unknown[],
      layout?: Record<string, unknown>,
      config?: Record<string, unknown>,
    ): Promise<void>;
    react(
      root: HTMLElement,
      data: unknown[],
      layout?: Record<string, unknown>,
      config?: Record<string, unknown>,
    ): Promise<void>;
    purge(root: HTMLElement): void;
  }
  const Plotly: PlotlyStatic;
  export default Plotly;
}

import { Component } from "react";

/**
 * Keeps one screen's crash from taking down the whole window.
 *
 * React unmounts the entire tree when a render throws and nothing catches it.
 * Before this existed, a single bad render anywhere below <main> left the app
 * as an empty black window -- no navigation rail, no Settings, no way back --
 * which in a packaged desktop build means quitting and relaunching. Verified
 * by rendering the real build in Chromium: one throw inside the lazily-loaded
 * Code tab took `#root` from one child to zero and removed all five nav
 * buttons with it.
 *
 * Each destination gets its own boundary (see App.jsx) so a failure is
 * contained to the screen that caused it: the rail keeps working, the other
 * tabs keep their state, and the user can simply navigate away. `resetKey`
 * clears a caught error when the user switches to a different conversation or
 * tab, so a transient failure doesn't leave the screen stuck on an error card
 * forever.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  componentDidCatch(error, info) {
    // Real diagnostics for a real failure -- this is the only place the
    // component stack survives, and the packaged app has no dev overlay.
    console.error(`[${this.props.label || "screen"}] render failed:`, error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex h-full w-full items-center justify-center p-6">
        <div className="max-w-md rounded-xl border border-charcoal-700 bg-charcoal-900 p-5">
          <h2 className="text-sm font-semibold text-charcoal-100">
            The {this.props.label || "screen"} screen hit an error
          </h2>
          <p className="mt-2 text-[13px] leading-relaxed text-charcoal-400">
            The rest of the app is still running — you can switch to another tab from the
            rail on the left, or try this screen again.
          </p>
          <pre className="mt-3 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-charcoal-950 p-2.5 text-[11px] leading-relaxed text-charcoal-400">
            {String(error?.message || error)}
          </pre>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-emerald-500"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-charcoal-300 ring-1 ring-charcoal-700 transition-colors hover:bg-charcoal-800"
            >
              Reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}

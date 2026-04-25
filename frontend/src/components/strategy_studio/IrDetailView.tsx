/**
 * IrDetailView — read-only renderer for a parsed Strategy IR.
 *
 * Purpose:
 *   Display every section of a parsed `StrategyIR` artifact in the
 *   spec-doc section ordering (A–J). Entirely presentational: no data
 *   fetching, no mutation, no router coupling. Consumed by the Strategy
 *   Studio detail page once an IR has been imported.
 *
 * Responsibilities:
 *   - Render Metadata, Universe, DataRequirements, Indicators, EntryLogic
 *     (long + short, or basket), ExitLogic, RiskModel, ExecutionModel,
 *     Filters, BasketTemplates (when present), DerivedFields (when present),
 *     and AmbiguitiesAndDefaults (when present).
 *   - Provide an opinionated layout that mirrors `StrategyPnL.tsx`:
 *     each block is a `<section aria-label=...>` with an `<h2>` header and
 *     a card-style body using surface-* + border tailwind classes.
 *   - Render the exit-logic `same_bar_priority` ordering at the top of the
 *     ExitLogic section so the operator can see conflict resolution at a
 *     glance.
 *
 * Does NOT:
 *   - Fetch the IR (parent passes it in via props).
 *   - Allow editing of any field (Strategy Studio editor is a separate
 *     M2.D-series component).
 *   - Validate the IR (validation happens server-side via Pydantic).
 *
 * Dependencies:
 *   - `StrategyIR` types from `@/types/strategy_ir`.
 *
 * Example:
 *     import { IrDetailView } from "@/components/strategy_studio/IrDetailView";
 *     <IrDetailView ir={parsedStrategyIR} />
 */

import type {
  StrategyIR,
  IrMetadata,
  IrUniverse,
  IrDataRequirements,
  IrIndicator,
  IrEntryLogic,
  IrExitLogic,
  IrExitStop,
  IrRiskModel,
  IrExecutionModel,
  IrFilter,
  IrDerivedField,
  IrAmbiguitiesAndDefaults,
  IrConditionTree,
  IrLeafCondition,
  IrDirectionalEntry,
  IrBasketTemplate,
} from "@/types/strategy_ir";
import { isLeafCondition } from "@/types/strategy_ir";

// ---------------------------------------------------------------------------
// Shared layout primitives
// ---------------------------------------------------------------------------

/**
 * Section wrapper — single header + card body. Mirrors StrategyPnL.tsx's
 * `<section aria-label=... className="rounded-lg border ... bg-white p-4">`
 * idiom so the IR view feels like a sibling of the existing read-only pages.
 */
function Section({
  letter,
  title,
  testId,
  children,
}: {
  letter: string;
  title: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-label={title}
      className="rounded-lg border border-surface-200 bg-white p-4"
      data-testid={testId}
    >
      <h2 className="mb-3 text-lg font-semibold text-surface-900">
        <span className="mr-2 inline-block rounded bg-brand-100 px-2 py-0.5 text-xs font-bold text-brand-800">
          {letter}
        </span>
        {title}
      </h2>
      <div className="text-sm text-surface-800">{children}</div>
    </section>
  );
}

/** Compact label + value row used in metadata-style blocks. */
function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 py-1">
      <span className="min-w-[10rem] text-xs font-medium uppercase tracking-wider text-surface-500">
        {label}
      </span>
      <span className="text-sm text-surface-900">{value}</span>
    </div>
  );
}

/** Pill / chip used for symbols, timeframes, and short tags. */
function Chip({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "brand" | "warn";
}) {
  const toneClass =
    tone === "brand"
      ? "bg-brand-50 text-brand-800 border-brand-200"
      : tone === "warn"
        ? "bg-yellow-50 text-yellow-800 border-yellow-200"
        : "bg-surface-100 text-surface-700 border-surface-200";
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${toneClass}`}
    >
      {children}
    </span>
  );
}

/** Render an arbitrary JSON-ish value defensively (used for ambiguities). */
function renderUnknown(value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-surface-400">—</span>;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return (
      <ul className="list-inside list-disc space-y-1">
        {value.map((item, idx) => (
          <li key={idx}>{renderUnknown(item)}</li>
        ))}
      </ul>
    );
  }
  // Object: render key:value pairs.
  return (
    <dl className="space-y-1">
      {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <dt className="font-medium text-surface-700">{k}:</dt>
          <dd className="text-surface-800">{renderUnknown(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------------------
// A. Metadata
// ---------------------------------------------------------------------------

function MetadataSection({ metadata }: { metadata: IrMetadata }) {
  const notes: string[] = Array.isArray(metadata.notes)
    ? metadata.notes
    : metadata.notes
      ? [metadata.notes]
      : [];
  return (
    <Section letter="A" title="Metadata" testId="ir-section-metadata">
      <Field label="Strategy Name" value={metadata.strategy_name} />
      <Field label="Version" value={metadata.strategy_version} />
      <Field label="Author" value={metadata.author} />
      <Field label="Created (UTC)" value={metadata.created_utc} />
      <Field label="Status" value={<Chip tone="brand">{metadata.status}</Chip>} />
      <div className="mt-2">
        <p className="text-xs font-medium uppercase tracking-wider text-surface-500">Objective</p>
        <p className="mt-1 text-sm text-surface-900">{metadata.objective}</p>
      </div>
      {notes.length > 0 && (
        <details className="mt-3" data-testid="ir-metadata-notes">
          <summary className="cursor-pointer text-xs font-medium uppercase tracking-wider text-surface-500">
            Notes ({notes.length})
          </summary>
          <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-surface-700">
            {notes.map((note, idx) => (
              <li key={idx}>{note}</li>
            ))}
          </ul>
        </details>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// B. Universe
// ---------------------------------------------------------------------------

function UniverseSection({ universe }: { universe: IrUniverse }) {
  return (
    <Section letter="B" title="Universe" testId="ir-section-universe">
      <Field label="Asset Class" value={<Chip>{universe.asset_class}</Chip>} />
      <Field label="Direction" value={<Chip tone="brand">{universe.direction}</Chip>} />
      {universe.selection_mode && (
        <Field label="Selection Mode" value={<Chip>{universe.selection_mode}</Chip>} />
      )}
      <div className="mt-2">
        <p className="text-xs font-medium uppercase tracking-wider text-surface-500">
          Symbols ({universe.symbols.length})
        </p>
        <div className="mt-1 flex flex-wrap gap-1.5" data-testid="ir-universe-symbols">
          {universe.symbols.map((sym) => (
            <Chip key={sym}>{sym}</Chip>
          ))}
        </div>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// C. Data Requirements
// ---------------------------------------------------------------------------

function DataRequirementsSection({ data }: { data: IrDataRequirements }) {
  // The on-disk IR JSONs sometimes omit list-valued fields entirely
  // rather than emitting `[]`. Pydantic's `default_factory=list` handles
  // this server-side, but we cannot rely on that here; the parsed JSON
  // is what we render, so we coerce missing lists to empty arrays.
  const confirmationTimeframes = data.confirmation_timeframes ?? [];
  const requiredFields = data.required_fields ?? [];
  const calendarDeps = data.calendar_dependencies ?? [];
  const allowedEntryDays = data.session_rules?.allowed_entry_days ?? [];
  const blockedEntryWindows = data.session_rules?.blocked_entry_windows ?? [];

  return (
    <Section letter="C" title="Data Requirements" testId="ir-section-data-requirements">
      <Field label="Primary Timeframe" value={<Chip tone="brand">{data.primary_timeframe}</Chip>} />
      {confirmationTimeframes.length > 0 && (
        <Field
          label="Confirmation TFs"
          value={
            <span className="flex flex-wrap gap-1">
              {confirmationTimeframes.map((tf) => (
                <Chip key={tf}>{tf}</Chip>
              ))}
            </span>
          }
        />
      )}
      <Field label="Timezone" value={data.timezone} />
      <Field label="Warmup Bars" value={data.warmup_bars.toString()} />
      <Field
        label="Missing Bar Policy"
        value={<code className="font-mono text-xs">{data.missing_bar_policy}</code>}
      />
      <Field
        label="Required Fields"
        value={
          <span className="flex flex-wrap gap-1">
            {requiredFields.map((f) => (
              <Chip key={f}>{f}</Chip>
            ))}
          </span>
        }
      />
      {calendarDeps.length > 0 && (
        <Field
          label="Calendar Deps"
          value={
            <span className="flex flex-wrap gap-1">
              {calendarDeps.map((c) => (
                <Chip key={c}>{c}</Chip>
              ))}
            </span>
          }
        />
      )}

      {/* Session rules */}
      <div className="mt-3 border-t border-surface-100 pt-3">
        <p className="text-xs font-medium uppercase tracking-wider text-surface-500">
          Session Rules
        </p>
        {allowedEntryDays.length > 0 && (
          <div className="mt-2">
            <span className="text-xs text-surface-600">Allowed entry days: </span>
            <span className="flex flex-wrap gap-1 pt-1">
              {allowedEntryDays.map((d) => (
                <Chip key={d}>{d}</Chip>
              ))}
            </span>
          </div>
        )}
        {blockedEntryWindows.length > 0 && (
          <table className="mt-2 w-full text-xs" data-testid="ir-blocked-entry-windows">
            <thead>
              <tr className="text-left text-surface-500">
                <th className="py-1 pr-3">Day</th>
                <th className="py-1 pr-3">Start</th>
                <th className="py-1 pr-3">End</th>
              </tr>
            </thead>
            <tbody>
              {blockedEntryWindows.map((w, idx) => (
                <tr key={idx} className="border-t border-surface-100">
                  <td className="py-1 pr-3">{w.day}</td>
                  <td className="py-1 pr-3 font-mono">{w.start_time}</td>
                  <td className="py-1 pr-3 font-mono">{w.end_time}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// D. Indicators
// ---------------------------------------------------------------------------

/**
 * Format an indicator's defining parameters into a single human string.
 * Discriminates on the `type` literal so each variant prints only the
 * fields it actually carries (no undefined / extra noise).
 */
function indicatorParams(ind: IrIndicator): string {
  switch (ind.type) {
    case "ema":
    case "sma":
    case "rsi":
      return `source=${ind.source}, length=${ind.length}`;
    case "atr":
    case "adx":
      return `length=${ind.length}`;
    case "bollinger_upper":
    case "bollinger_lower":
      return `source=${ind.source}, length=${ind.length}, stddev=${ind.stddev}`;
    case "rolling_stddev":
    case "rolling_high":
    case "rolling_low":
      return `source=${ind.source}, length_bars=${ind.length_bars}`;
    case "rolling_max":
    case "rolling_min":
      return `source=${ind.source}, length=${ind.length}`;
    case "zscore":
      return `source=${ind.source}, mean=${ind.mean_source}, std=${ind.std_source}`;
    case "calendar_business_day_index":
    case "calendar_days_to_month_end":
      return "—";
  }
}

function IndicatorsSection({ indicators }: { indicators: IrIndicator[] }) {
  return (
    <Section letter="D" title="Indicators" testId="ir-section-indicators">
      <table className="w-full text-sm" data-testid="ir-indicators-table">
        <thead>
          <tr className="border-b border-surface-200 text-left text-xs uppercase tracking-wider text-surface-500">
            <th className="py-2 pr-4">ID</th>
            <th className="py-2 pr-4">Type</th>
            <th className="py-2 pr-4">Timeframe</th>
            <th className="py-2 pr-4">Parameters</th>
          </tr>
        </thead>
        <tbody>
          {indicators.map((ind) => (
            <tr key={ind.id} className="border-b border-surface-100">
              <td className="py-2 pr-4 font-mono text-xs">{ind.id}</td>
              <td className="py-2 pr-4">
                <Chip tone="brand">{ind.type}</Chip>
              </td>
              <td className="py-2 pr-4 font-mono text-xs">{ind.timeframe}</td>
              <td className="py-2 pr-4 font-mono text-xs text-surface-700">
                {indicatorParams(ind)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// E. Entry Logic — condition tree renderer + per-direction blocks
// ---------------------------------------------------------------------------

/** Render a single leaf condition as `lhs OP rhs [units]`. */
function LeafConditionNode({ leaf }: { leaf: IrLeafCondition }) {
  return (
    <span className="font-mono text-xs text-surface-800">
      <span className="text-surface-700">{leaf.lhs}</span>{" "}
      <span className="font-bold text-brand-700">{leaf.operator}</span>{" "}
      <span className="text-surface-700">{String(leaf.rhs)}</span>
      {leaf.units && <span className="ml-1 text-surface-400">[{leaf.units}]</span>}
    </span>
  );
}

/** Recursively render a condition tree as nested AND/OR groups. */
function ConditionTreeNode({ tree }: { tree: IrConditionTree }) {
  return (
    <div className="border-l-2 border-brand-200 pl-3">
      <div className="mb-1 text-xs font-bold uppercase tracking-wider text-brand-700">
        {tree.op}
      </div>
      <ul className="space-y-1">
        {tree.conditions.map((cond, idx) => (
          <li key={idx}>
            {isLeafCondition(cond) ? (
              <LeafConditionNode leaf={cond} />
            ) : (
              <ConditionTreeNode tree={cond} />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DirectionalEntryBlock({
  side,
  entry,
}: {
  side: "long" | "short";
  entry: IrDirectionalEntry;
}) {
  return (
    <div
      className="rounded border border-surface-200 bg-surface-50 p-3"
      data-testid={`ir-entry-${side}`}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-semibold uppercase text-surface-700">{side}</span>
        <Chip tone="brand">order: {entry.order_type}</Chip>
      </div>
      <ConditionTreeNode tree={entry.logic} />
    </div>
  );
}

function BasketTemplatesSection({ templates }: { templates: IrBasketTemplate[] }) {
  return (
    <Section letter="J" title="Basket Templates" testId="ir-section-basket-templates">
      <div className="space-y-3">
        {templates.map((tpl) => (
          <div
            key={tpl.id}
            className="rounded border border-surface-200 bg-surface-50 p-3"
            data-testid={`ir-basket-${tpl.id}`}
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="font-mono text-sm font-semibold text-surface-900">{tpl.id}</span>
              <span className="text-xs text-surface-500">active when</span>
              <LeafConditionNode leaf={tpl.active_when} />
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-surface-200 text-left text-surface-500">
                  <th className="py-1 pr-3">Symbol</th>
                  <th className="py-1 pr-3">Side</th>
                  <th className="py-1 pr-3">Weight</th>
                </tr>
              </thead>
              <tbody>
                {tpl.legs.map((leg, idx) => (
                  <tr key={idx} className="border-b border-surface-100">
                    <td className="py-1 pr-3 font-mono">{leg.symbol}</td>
                    <td className="py-1 pr-3">
                      <Chip tone={leg.side === "buy" ? "brand" : "warn"}>{leg.side}</Chip>
                    </td>
                    <td className="py-1 pr-3 font-mono">{leg.weight}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </Section>
  );
}

function EntryLogicSection({ entry }: { entry: IrEntryLogic }) {
  return (
    <Section letter="E" title="Entry Logic" testId="ir-section-entry-logic">
      <div className="mb-3 flex flex-wrap gap-2">
        <Field label="Evaluation Timing" value={<Chip>{entry.evaluation_timing}</Chip>} />
        <Field label="Execution Timing" value={<Chip>{entry.execution_timing}</Chip>} />
        {entry.signal_expiration_bars !== undefined && entry.signal_expiration_bars !== null && (
          <Field label="Signal Expiry (bars)" value={entry.signal_expiration_bars.toString()} />
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {entry.long && <DirectionalEntryBlock side="long" entry={entry.long} />}
        {entry.short && <DirectionalEntryBlock side="short" entry={entry.short} />}
      </div>
      {entry.entry_filters && (
        <div className="mt-3" data-testid="ir-entry-filters">
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-surface-500">
            Entry Filters
          </p>
          <ConditionTreeNode tree={entry.entry_filters} />
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// F. Exit Logic
// ---------------------------------------------------------------------------

/** Format an exit-stop wrapper into a short human description. */
function describeExitStop(stop: IrExitStop): React.ReactNode {
  switch (stop.type) {
    case "atr_multiple":
    case "basket_atr_multiple":
      return (
        <span className="font-mono text-xs">
          {stop.multiple} × <span className="text-brand-700">{stop.indicator}</span>
        </span>
      );
    case "risk_reward_multiple":
      return <span className="font-mono text-xs">RR = {stop.multiple}</span>;
    case "opposite_inner_band_touch":
      return <span className="text-xs italic text-surface-600">opposite inner band touch</span>;
    case "middle_band_close_violation":
      return <span className="text-xs italic text-surface-600">close beyond middle band</span>;
    case "channel_exit":
    case "mean_reversion_to_mid":
      return (
        <div className="space-y-1">
          <div>
            <span className="text-xs text-surface-500">long: </span>
            <LeafConditionNode leaf={stop.long_condition} />
          </div>
          <div>
            <span className="text-xs text-surface-500">short: </span>
            <LeafConditionNode leaf={stop.short_condition} />
          </div>
        </div>
      );
    case "calendar_exit":
    case "zscore_stop":
      return <LeafConditionNode leaf={stop.condition} />;
    case "basket_open_loss_pct":
      return <span className="font-mono text-xs">≥ {stop.threshold_pct}% open loss</span>;
  }
}

function ExitStopRow({ label, stop }: { label: string; stop: IrExitStop }) {
  return (
    <div
      className="flex items-start gap-3 border-b border-surface-100 py-2 last:border-b-0"
      data-testid={`ir-exit-${label.replace(/ /g, "-").toLowerCase()}`}
    >
      <span className="min-w-[10rem] text-xs font-medium uppercase tracking-wider text-surface-500">
        {label}
      </span>
      <div className="flex flex-col gap-1">
        <Chip tone="brand">{stop.type}</Chip>
        <div>{describeExitStop(stop)}</div>
      </div>
    </div>
  );
}

function ExitLogicSection({ exit }: { exit: IrExitLogic }) {
  const sameBarPriority = exit.same_bar_priority ?? [];
  return (
    <Section letter="F" title="Exit Logic" testId="ir-section-exit-logic">
      {sameBarPriority.length > 0 && (
        <div
          className="mb-3 rounded border border-brand-200 bg-brand-50 p-3"
          data-testid="ir-same-bar-priority"
        >
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-brand-800">
            Same-Bar Priority (in order)
          </p>
          <ol className="list-inside list-decimal text-sm text-surface-800">
            {sameBarPriority.map((label, idx) => (
              <li key={idx} className="font-mono text-xs">
                {label}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="space-y-1">
        {exit.initial_stop && <ExitStopRow label="Initial Stop" stop={exit.initial_stop} />}
        {exit.take_profit && <ExitStopRow label="Take Profit" stop={exit.take_profit} />}
        {exit.primary_exit && <ExitStopRow label="Primary Exit" stop={exit.primary_exit} />}
        {exit.trailing_exit && <ExitStopRow label="Trailing Exit" stop={exit.trailing_exit} />}
        {exit.scheduled_exit && <ExitStopRow label="Scheduled Exit" stop={exit.scheduled_exit} />}
        {exit.equity_stop && <ExitStopRow label="Equity Stop" stop={exit.equity_stop} />}
        {exit.catastrophic_zscore_stop && (
          <ExitStopRow label="Catastrophic Z" stop={exit.catastrophic_zscore_stop} />
        )}

        {exit.trailing_stop && (
          <div className="flex items-start gap-3 border-b border-surface-100 py-2">
            <span className="min-w-[10rem] text-xs font-medium uppercase tracking-wider text-surface-500">
              Trailing Stop
            </span>
            <div className="flex flex-col gap-1">
              <Chip tone={exit.trailing_stop.enabled ? "brand" : "neutral"}>
                {exit.trailing_stop.enabled ? "enabled" : "disabled"}
              </Chip>
              <span className="font-mono text-xs">{exit.trailing_stop.type}</span>
            </div>
          </div>
        )}

        {exit.break_even && (
          <div className="flex items-start gap-3 border-b border-surface-100 py-2">
            <span className="min-w-[10rem] text-xs font-medium uppercase tracking-wider text-surface-500">
              Break-Even
            </span>
            <div className="flex flex-col gap-1">
              <Chip tone={exit.break_even.enabled ? "brand" : "neutral"}>
                {exit.break_even.enabled ? "enabled" : "disabled"}
              </Chip>
              <span className="font-mono text-xs">
                trigger {exit.break_even.trigger_r_multiple}R · offset {exit.break_even.offset_pips}{" "}
                pips
              </span>
            </div>
          </div>
        )}

        {exit.time_exit && (
          <div className="flex items-start gap-3 border-b border-surface-100 py-2">
            <span className="min-w-[10rem] text-xs font-medium uppercase tracking-wider text-surface-500">
              Time Exit
            </span>
            <div className="flex flex-col gap-1">
              <Chip tone={exit.time_exit.enabled ? "brand" : "neutral"}>
                {exit.time_exit.enabled ? "enabled" : "disabled"}
              </Chip>
              <span className="font-mono text-xs">
                max {exit.time_exit.max_bars_in_trade} bars in trade
              </span>
            </div>
          </div>
        )}

        {exit.max_bars_in_trade !== undefined && exit.max_bars_in_trade !== null && (
          <div className="flex items-start gap-3 border-b border-surface-100 py-2">
            <span className="min-w-[10rem] text-xs font-medium uppercase tracking-wider text-surface-500">
              Max Bars In Trade
            </span>
            <span className="font-mono text-xs">{exit.max_bars_in_trade}</span>
          </div>
        )}

        {exit.friday_close_exit && (
          <div className="flex items-start gap-3 border-b border-surface-100 py-2">
            <span className="min-w-[10rem] text-xs font-medium uppercase tracking-wider text-surface-500">
              Friday Close Exit
            </span>
            <div className="flex flex-col gap-1">
              <Chip tone={exit.friday_close_exit.enabled ? "brand" : "neutral"}>
                {exit.friday_close_exit.enabled ? "enabled" : "disabled"}
              </Chip>
              <span className="font-mono text-xs">
                {exit.friday_close_exit.close_time} {exit.friday_close_exit.timezone}
              </span>
            </div>
          </div>
        )}

        {exit.session_close_exit && (
          <div className="flex items-start gap-3 border-b border-surface-100 py-2">
            <span className="min-w-[10rem] text-xs font-medium uppercase tracking-wider text-surface-500">
              Session Close Exit
            </span>
            <div className="flex flex-col gap-1">
              <Chip tone={exit.session_close_exit.enabled ? "brand" : "neutral"}>
                {exit.session_close_exit.enabled ? "enabled" : "disabled"}
              </Chip>
              <span className="font-mono text-xs">
                {exit.session_close_exit.friday_close_time} {exit.session_close_exit.timezone}
              </span>
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// G. Risk Model
// ---------------------------------------------------------------------------

function RiskModelSection({ risk }: { risk: IrRiskModel }) {
  const ps = risk.position_sizing;
  return (
    <Section letter="G" title="Risk Model" testId="ir-section-risk-model">
      <div className="mb-3 rounded border border-surface-200 bg-surface-50 p-3">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-surface-500">
          Position Sizing
        </p>
        <Field label="Method" value={<Chip tone="brand">{ps.method}</Chip>} />
        <Field label="Risk %/Equity" value={`${ps.risk_pct_of_equity}%`} />
        {ps.stop_distance_source && (
          <Field
            label="Stop Distance Source"
            value={<code className="font-mono text-xs">{ps.stop_distance_source}</code>}
          />
        )}
        {ps.allocation_mode && (
          <Field label="Allocation Mode" value={<Chip>{ps.allocation_mode}</Chip>} />
        )}
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        {risk.max_open_positions !== undefined && risk.max_open_positions !== null && (
          <Field label="Max Open Positions" value={risk.max_open_positions.toString()} />
        )}
        {risk.max_positions_per_symbol !== undefined && risk.max_positions_per_symbol !== null && (
          <Field label="Max Positions / Symbol" value={risk.max_positions_per_symbol.toString()} />
        )}
        {risk.max_open_baskets !== undefined && risk.max_open_baskets !== null && (
          <Field label="Max Open Baskets" value={risk.max_open_baskets.toString()} />
        )}
        {risk.gross_exposure_cap_pct_of_equity !== undefined &&
          risk.gross_exposure_cap_pct_of_equity !== null && (
            <Field label="Gross Exposure Cap" value={`${risk.gross_exposure_cap_pct_of_equity}%`} />
          )}
        <Field label="Daily Loss Limit" value={`${risk.daily_loss_limit_pct}%`} />
        <Field label="Max Drawdown Halt" value={`${risk.max_drawdown_halt_pct}%`} />
        <Field
          label="Pyramiding"
          value={<Chip tone={risk.pyramiding ? "warn" : "neutral"}>{String(risk.pyramiding)}</Chip>}
        />
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// H. Execution Model
// ---------------------------------------------------------------------------

function ExecutionModelSection({ exec }: { exec: IrExecutionModel }) {
  return (
    <Section letter="H" title="Execution Model" testId="ir-section-execution-model">
      <Field
        label="Fill Model"
        value={<code className="font-mono text-xs">{exec.fill_model}</code>}
      />
      <Field
        label="Slippage Ref"
        value={<code className="font-mono text-xs">{exec.slippage_model_ref}</code>}
      />
      <Field
        label="Spread Ref"
        value={<code className="font-mono text-xs">{exec.spread_model_ref}</code>}
      />
      <Field
        label="Commission Ref"
        value={<code className="font-mono text-xs">{exec.commission_model_ref}</code>}
      />
      <Field
        label="Swap Ref"
        value={<code className="font-mono text-xs">{exec.swap_model_ref}</code>}
      />
      <Field
        label="Partial Fill Policy"
        value={<code className="font-mono text-xs">{exec.partial_fill_policy}</code>}
      />
      <Field
        label="Reject Policy"
        value={<code className="font-mono text-xs">{exec.reject_policy}</code>}
      />
    </Section>
  );
}

// ---------------------------------------------------------------------------
// I. Filters
// ---------------------------------------------------------------------------

/**
 * Filters are heterogeneous (comparison-style or named-rule). Render as a
 * compact key=value chip strip per filter, dropping any field that is
 * absent. Always includes ID + (type or "comparison").
 */
function filterFields(f: IrFilter): Array<[string, string]> {
  const fields: Array<[string, string]> = [];
  if (f.type) fields.push(["type", f.type]);
  if (f.lhs) fields.push(["lhs", f.lhs]);
  if (f.operator) fields.push(["op", f.operator]);
  if (f.rhs !== null && f.rhs !== undefined) fields.push(["rhs", String(f.rhs)]);
  if (f.units) fields.push(["units", f.units]);
  if (f.day) fields.push(["day", f.day]);
  if (f.time) fields.push(["time", f.time]);
  if (f.timezone) fields.push(["tz", f.timezone]);
  if (f.month !== null && f.month !== undefined) fields.push(["month", String(f.month)]);
  if (f.business_day_start !== null && f.business_day_start !== undefined)
    fields.push(["bday_start", String(f.business_day_start)]);
  if (f.business_day_end !== null && f.business_day_end !== undefined)
    fields.push(["bday_end", String(f.business_day_end)]);
  if (f.unit) fields.push(["unit", f.unit]);
  return fields;
}

function FiltersSection({ filters }: { filters: IrFilter[] }) {
  return (
    <Section letter="I" title="Filters" testId="ir-section-filters">
      <ul className="space-y-2">
        {filters.map((f) => (
          <li
            key={f.id}
            className="rounded border border-surface-200 bg-surface-50 p-2"
            data-testid={`ir-filter-${f.id}`}
          >
            <div className="mb-1 flex items-center gap-2">
              <span className="font-mono text-xs font-semibold text-surface-900">{f.id}</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {filterFields(f).map(([k, v]) => (
                <Chip key={k}>
                  <span className="text-surface-500">{k}=</span>
                  <span>{v}</span>
                </Chip>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Derived Fields
// ---------------------------------------------------------------------------

function DerivedFieldsSection({ derived }: { derived: IrDerivedField[] }) {
  return (
    <Section letter="K" title="Derived Fields" testId="ir-section-derived-fields">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-surface-200 text-left text-xs uppercase tracking-wider text-surface-500">
            <th className="py-2 pr-4">ID</th>
            <th className="py-2 pr-4">Formula</th>
          </tr>
        </thead>
        <tbody>
          {derived.map((d) => (
            <tr key={d.id} className="border-b border-surface-100">
              <td className="py-2 pr-4 font-mono text-xs">{d.id}</td>
              <td className="py-2 pr-4 font-mono text-xs text-surface-700">{d.formula}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Ambiguities and Defaults
// ---------------------------------------------------------------------------

function AmbiguitiesSection({ ambiguities }: { ambiguities: IrAmbiguitiesAndDefaults }) {
  const entries = Object.entries(ambiguities);
  if (entries.length === 0) return null;
  return (
    <Section letter="L" title="Ambiguities & Defaults" testId="ir-section-ambiguities">
      <details>
        <summary className="cursor-pointer text-xs font-medium uppercase tracking-wider text-surface-500">
          Show {entries.length} item{entries.length === 1 ? "" : "s"}
        </summary>
        <dl className="mt-2 space-y-2">
          {entries.map(([key, value]) => (
            <div key={key} className="border-l-2 border-surface-200 pl-3">
              <dt className="text-xs font-semibold text-surface-700">{key}</dt>
              <dd className="mt-1 text-sm text-surface-800">{renderUnknown(value)}</dd>
            </div>
          ))}
        </dl>
      </details>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Root view
// ---------------------------------------------------------------------------

export interface IrDetailViewProps {
  ir: StrategyIR;
}

/**
 * Read-only top-level renderer for a `StrategyIR`. Sections render in the
 * spec-doc canonical order; optional sections are omitted entirely when
 * absent rather than shown with empty bodies.
 */
export function IrDetailView({ ir }: IrDetailViewProps) {
  return (
    <div
      className="space-y-4 text-surface-900"
      data-testid="ir-detail-view"
      data-strategy-name={ir.metadata.strategy_name}
    >
      <MetadataSection metadata={ir.metadata} />
      <UniverseSection universe={ir.universe} />
      <DataRequirementsSection data={ir.data_requirements} />
      <IndicatorsSection indicators={ir.indicators} />
      <EntryLogicSection entry={ir.entry_logic} />
      <ExitLogicSection exit={ir.exit_logic} />
      <RiskModelSection risk={ir.risk_model} />
      <ExecutionModelSection exec={ir.execution_model} />
      {ir.filters && ir.filters.length > 0 && <FiltersSection filters={ir.filters} />}
      {ir.entry_logic.basket_templates && ir.entry_logic.basket_templates.length > 0 && (
        <BasketTemplatesSection templates={ir.entry_logic.basket_templates} />
      )}
      {ir.derived_fields && ir.derived_fields.length > 0 && (
        <DerivedFieldsSection derived={ir.derived_fields} />
      )}
      {ir.ambiguities_and_defaults && (
        <AmbiguitiesSection ambiguities={ir.ambiguities_and_defaults} />
      )}
    </div>
  );
}

export default IrDetailView;

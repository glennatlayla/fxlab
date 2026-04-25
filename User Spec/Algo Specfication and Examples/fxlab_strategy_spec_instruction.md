# FXLab Strategy Specification Instruction Document

## Purpose

This document tells a strategy developer how to write a trading algorithm specification that is detailed enough to be translated into FXLab-style research artifacts.

This is not a trading idea template. It is a compilation-ready specification template.

The goal is to produce a strategy definition that is:

- explicit
- deterministic
- machine-translatable
- reproducible in backtesting
- reviewable by another developer without relying on unstated assumptions

A strategy spec is **not complete** until a second developer could implement it with materially identical behavior.

---

## Required deliverables

For each strategy, the developer should produce these four items:

1. A human-readable strategy specification document
2. `strategy_ir.json`
3. `search_space.json`
4. `experiment_plan.json`

Optional additional artifacts may include:

- `data_contract.json`
- `cost_model.json`
- `readiness_thresholds.json`
- `notes.md`

---

## Authoring rules

### 1. Do not use vague language

Avoid phrases like:

- strong trend
- good momentum
- weak market
- high volatility
- bad spread
- favorable setup
- confirmation candle

Replace them with explicit, measurable rules.

Example:

- Bad: “Enter when momentum is strong.”
- Good: “Enter long when RSI(14) is greater than 55 and MACD line is above the signal line on the close of the 15-minute bar.”

### 2. Every rule must be testable

Every entry, exit, filter, and sizing rule must be expressible as deterministic logic.

### 3. Timing semantics must be explicit

For every signal, define exactly when it is evaluated and when the order is placed.

Examples:

- evaluate on bar close, submit order for next bar open
- evaluate intrabar, enter immediately at stop trigger
- evaluate on every tick, but only one signal per bar

### 4. Assumptions must be declared

If any part of the strategy depends on interpretation, list that interpretation explicitly.

### 5. Parameters must be separated from logic

The strategy logic should define what the rule is.
The parameter file should define which values are fixed and which are tunable.

---

## What must be defined in the strategy specification

## A. Strategy identity

Required fields:

- strategy name
- version
- author
- date
- objective
- market or asset class
- instrument universe
- direction: long, short, or both
- intended deployment mode: research only, paper, or live candidate

---

## B. Data contract

The developer must define:

- symbols or symbol-selection method
- timeframe(s)
- required fields: open, high, low, close, volume, bid/ask, spread, etc.
- session or trading-hours rules
- time zone
- holiday/calendar assumptions
- handling of missing bars
- handling of duplicate bars
- roll logic if futures or continuous contracts are used
- warmup lookback requirements

Example:

- Primary timeframe: 15m
- Higher timeframe confirmation: 1h
- Session: Sunday 17:00 ET to Friday 17:00 ET
- Do not open new trades between Friday 16:00 ET and Sunday 18:00 ET
- Require 200 complete warmup bars before signals are valid

---

## C. Entry logic

For each entry rule, define:

- long or short
- all required indicators and how they are calculated
- parameter values or parameter names
- comparison operator
- grouping logic using AND/OR
- evaluation timing
- order type
- order expiry

Example checklist:

- condition 1
- condition 2
- condition 3
- conditions grouped as `(1 AND 2 AND 3)`
- evaluated on bar close
- submit market order at next bar open

If both long and short logic exist, define them separately.

---

## D. Exit logic

Define every possible exit path.

Required categories:

- initial stop-loss
- take-profit
- trailing stop
- break-even logic
- opposite-signal exit
- time-based exit
- session close exit
- max-bars-in-trade exit
- emergency exit or trading halt conditions

For each, define:

- trigger condition
- order type
- priority if multiple exits trigger in the same bar

---

## E. Position sizing and risk

Define:

- sizing model: fixed units, fixed dollar risk, percent equity risk, volatility scaled, etc.
- max risk per trade
- account basis for sizing
- max concurrent positions
- max positions per symbol
- max portfolio exposure
- pyramiding rules
- scale-in/scale-out rules
- daily loss limit
- drawdown halt thresholds

---

## F. Filters and trade blockers

Common filter categories include:

- spread filter
- volatility filter
- trend filter
- regime filter
- time-of-day filter
- day-of-week filter
- event/news filter
- cooldown period after trade close
- minimum bar range filter

Each filter must be measurable.

Example:

- Do not enter if current spread in pips is greater than 1.8
- Do not enter if ATR(14) on 15m is below 0.0009

---

## G. Execution realism assumptions

These assumptions must be declared because they strongly affect backtest credibility.

Required definitions:

- order types used
- fill model
- slippage model
- spread model
- commission model
- financing or swap model
- partial fill assumptions
- rejection or cancel assumptions
- market gap behavior
- stop execution behavior
- limit execution behavior

If the backtest engine supports multiple realism modes, specify which one to use.

---

## H. Optimization contract

If optimization is allowed, define:

- tunable parameters
- parameter ranges
- parameter steps or enumerated values
- constraints between parameters
- optimization method: grid, random, Bayesian, evolutionary, etc.
- optimization objective
- tie-break rules
- max trial count or compute limits

Example constraint:

- `slow_ema > fast_ema`

---

## I. Research and validation plan

The developer must define how the strategy will be evaluated.

Required definitions:

- in-sample period
- out-of-sample period
- holdout period
- walk-forward design
- Monte Carlo or bootstrap method if used
- minimum trade count
- ranking metric
- acceptance thresholds
- invalidation criteria
- regime segmentation if required

Examples of acceptance thresholds:

- Profit factor >= 1.20
- Max drawdown <= 12%
- At least 150 trades across full test period
- Out-of-sample Sharpe ratio >= 0.80

---

## J. Ambiguities and default assumptions

This section is mandatory.

List:

- anything not fully specified by the strategy author
- assumptions requested from implementers
- fallback behavior when data is missing
- tie-break rules for same-bar events
- interpretation of ambiguous order sequencing

If this section is omitted, the strategy should be treated as incomplete.

---

## Suggested JSON artifact structure

These example structures are inferred from the program materials and may need to be adapted to the exact FXLab schema.

### 1. `strategy_ir.json`

Purpose:
- defines the strategy logic
- identifies required data
- captures execution and risk rules

Should contain:

- metadata
- universe
- data requirements
- indicators
- signal logic
- order model
- risk model
- filters
- ambiguity notes

### 2. `search_space.json`

Purpose:
- defines tunable parameters and constraints

Should contain:

- parameter list
- domains
- defaults
- constraints
- optimization objective

### 3. `experiment_plan.json`

Purpose:
- defines how the strategy should be tested

Should contain:

- dataset selectors or dataset versions
- train/validation/holdout splits
- cost model reference
- seed
- walk-forward settings
- ranking metrics
- acceptance thresholds
- output requirements

---

## Minimum quality standard before submission

A strategy package is not ready unless all of the following are true:

- every indicator is fully defined
- every threshold is numeric or enum-based
- every entry and exit path is explicit
- timing semantics are explicit
- risk rules are explicit
- optimization rules are explicit
- research plan is explicit
- execution realism assumptions are explicit
- ambiguities are listed

If any of those are missing, the strategy package should be rejected or returned for clarification.

---

## Developer handoff checklist

Before handing the strategy to the FXLab operator, verify:

- [ ] The strategy can be explained in one paragraph
- [ ] The strategy can be implemented without verbal clarification
- [ ] A second developer would implement the same behavior
- [ ] Entry logic is deterministic
- [ ] Exit logic is deterministic
- [ ] Cost assumptions are declared
- [ ] Data requirements are declared
- [ ] Optimization scope is declared
- [ ] Validation plan is declared
- [ ] Open ambiguities are explicitly listed

---

## Final instruction to the developer

Do not send a narrative trading idea.
Send a machine-translatable strategy package.

The package must be specific enough that a backtest run can be reproduced later using the same logic, parameters, data selection, cost assumptions, and research plan.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm test                    # Run unit tests (270+ skill/structure tests)
npm run validate            # Validate prompt file contents and format
npm run pre-release         # Full pre-release check: pre-release-check + validate + test
npm run verify              # Verify local setup is correct
npm run release:dry-run     # Preview release without making changes
npm run integration-tests   # Run integration tests
```

Validate JSON manifests manually:
```bash
jq empty plugins/us-stock-analysis/.claude-plugin/plugin.json
jq empty .claude-plugin/marketplace.json
```

## Architecture

InvestSkill is a **prompt-engineering plugin**, not traditional software. There is no application runtime — the "skills" are structured markdown frameworks that guide AI assistants through investment analysis workflows.

### Skill Distribution Model

Each skill lives in two forms simultaneously:

1. **`plugins/us-stock-analysis/skills/<name>/SKILL.md`** — Claude Code form, includes YAML frontmatter (`---\ndescription: ...\n---`) and uses slash command syntax
2. **`prompts/<name>.md`** — Universal form, identical content but with frontmatter stripped, AI-agnostic (no slash commands)

These two files must stay in sync. The `prompts/` version is what Cursor, Gemini CLI, GitHub Copilot, and ChatGPT users access.

### Platform Config Files

| File | Platform |
|------|----------|
| `plugins/us-stock-analysis/.claude-plugin/plugin.json` | Claude Code plugin manifest |
| `.claude-plugin/marketplace.json` | Claude marketplace listing |
| `.cursor/rules/invest-skill.mdc` | Cursor IDE auto-loading rules |
| `.github/copilot-instructions.md` | GitHub Copilot auto-loading |
| `GEMINI.md` | Gemini CLI auto-loading |

### Signal Block Requirement

Every SKILL.md and every `prompts/*.md` must end with a standardized Investment Signal Block using box-drawing characters (UTF-8). Tests validate this.

### Output Directory Index Rule

Whenever generating or updating an HTML report in `output/`, Claude Code **MUST** dynamically update `output/index.html` (e.g. by running `npm run update:index` or `node scripts/generate-output-index.js`). `output/index.html` provides a central interactive index listing all HTML reports with direct clickable links.

### Price Integrity & Zero-Truncation Execution Rule

- **Strictly Prohibit Double-Quoted Inline Shell Execution**: NEVER run inline scripts (e.g. `python3 -c "..."` or `node -e "..."`) that interpolate strings with currency amounts like `$125.00` or `$268.70`. Shell variable expansion turns them into `.00` and `.70`.
- **Mandatory Safe Generation Methods**: Always use dedicated script files, safe heredocs (`cat << 'EOF' > ...`), or dedicated file tools.
- **Mandatory Post-Generation Verification**: Automatically scan all generated HTML/MD files for truncated numbers (e.g. `>\s*\.\d{2}`, `Strike\s*\.\d{2}`) before finishing.

### Mobile Compatibility & Responsive Layout Rule

Whenever generating HTML reports:
- **Mandatory Viewport & Meta**: Must include `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, viewport-fit=cover">` and `<meta name="format-detection" content="telephone=no">`.
- **Responsive Layout**: Main container must be fluid (`max-width: 1100px; width: 100%`) with `@media (max-width: 768px)` collapsing grids to 1-2 columns and adjusting padding to 16px.
- **Scrollable Data Tables & Charts**: All data tables must be wrapped in `.table-scroll` (`overflow-x: auto; -webkit-overflow-scrolling: touch;`), and Chart.js configured with `responsive: true, maintainAspectRatio: false`.
- **Self-Contained & Touch Friendly**: Inline CSS, no external broken CDN fonts/icons, minimum body font size 14px for legible mobile reading.

### Terminal & Python Non-Blocking Execution & Token Diet Rule

- **Mandatory Max Wait Time**: Whenever executing commands via tool calls, always set `WaitMsBeforeAsync: 10000` (10,000 ms) so fast data fetching scripts complete synchronously without prematurely dropping into background tasks.
- **Mandatory Unbuffered Execution**: Always run Python scripts with `-u` (e.g. `python3 -u script.py`) or set `PYTHONUNBUFFERED=1` so terminal logs stream immediately.
- **Decoupled Architecture & Local Scratch Cache**: Keep remote data fetching and local HTML generation decoupled. Cache remote payloads to local scratch JSON (`<appDataDir>/brain/<conversation-id>/scratch/` or `/tmp/`) and perform local re-renders in < 0.2s without redundant network roundtrips.
- **Network Timeouts**: Always set explicit socket/request timeouts (e.g. `timeout=5`) in data scrapers to prevent hanging on slow upstream finance APIs.
- **Terminal Output Throttling & Token Diet**: Use `head`, `tail`, `-n`, `--silent`, or `-q` (e.g. `git log -n 5`, `head -n 30`) to avoid flooding the context and increasing model inference latency.

### Workspace Cleanliness & Zero Intermediate Artifacts Rule

- **Single Output Target Whitelist**: ONLY final generated HTML research reports in `output/` (and their corresponding index entry in `output/index.html`) may be placed in the project directory.
- **Strict Isolation of Intermediate Code & Data**: NEVER save ad-hoc fetch scripts, data scrapers, intermediate JSON cache files, or report builders in `scripts/`, `data/`, or root. All temporary code and data MUST strictly be written to the scratch directory (`<appDataDir>/brain/<conversation-id>/scratch/` or `/tmp/`).
- **Immediate Cleanup**: Any temporary files generated must be immediately moved to scratch or deleted before concluding the task.

### Mandatory Dividend Disclosure Rule

- **Explicit Dividend Reporting**: Whenever generating stock evaluations, research reports, financial summaries, or key metrics tables, Claude Code **MUST explicitly state the dividend status** (Dividend Yield, Annual Payout, Payout Ratio, Ex-Dividend Date).
- **Zero Dividend / None**: If the company does not pay dividends (0.00% yield), **MUST explicitly write "无 / 没有 (无股息派发 / Dividend: None / N/A)"** and mention shareholder return alternatives (e.g. Share Buybacks / 股票回购). Never omit or leave the dividend field blank.

### Mandatory Comprehensive 15-Module Depth by Default

- **Comprehensive Depth by Default**: All stock research, deep-dive reports, and HTML output generation **MUST ALWAYS default to Comprehensive Depth (all 15 modules)**.
- **Strictly Prohibited**: Never default to Quick (5-7 modules) or Standard (8-10 modules) unless explicitly instructed by the user.
- **Mandatory 15 Modules**:
  1. 执行摘要与投资核心逻辑 (Executive Summary & Thesis)
  2. 多因子量化评分雷达模型 (Multi-Factor Quantitative Scorecard & Radar Chart)
  3. 商业模式、垂直整合与波特五力护城河评级 (Business Model & Porter's 5 Forces)
  4. 核心财务报表与盈利质量深度剖析 (Financial Statements, Margins & Cash Flow Quality)
  5. 杜邦三因子拆解与资本运营效率 (DuPont Analysis: Margin × Turnover × Leverage)
  6. 行业竞争格局与同行全景对标矩阵 (Peer Comparison Matrix with Multiples, Margins, Market Share)
  7. DCF 现金流折现、研发资本化成长模型与多维估值公允中枢 (DCF Valuation: Conservative Floor, Growth & R&D Capitalized DCF, Multiples-Implied Fair Value & Premium Decomposition Bridge)
  8. 技术面量化、均线系统与关键筹码位 (Technical Analysis: SMA20/50/200, RSI, MACD, S/R)
  9. 资本配置、股息政策与股东回报披露 (Capital Allocation & Dividend: explicit "无/没有" if zero dividend)
  10. 现金担保卖出看跌期权 (Cash-Secured Sell Put) 收益增强策略 (Conservative, Moderate, Aggressive 3 Tiers)
  11. 机构持仓与主力资金动向 (Institutional Ownership: Top 13F Holders Table)
  12. 内部人交易、管理层语气与财报电话会洞察 (Insider Trading Form 4 & Earnings Call Tone)
  13. 做空比例、平仓天数与轧空风险评估 (Short Interest, Days to Cover & Options P/C Ratio)
  14. 核心风险矩阵与熊市压力测试 (Risk Matrix & Bear Case Downside Stress Test)
  15. 未来关键催化剂日历与增长路线图 (Catalyst Calendar & Strategic Milestones)
  16. 最终投资评级与执行建议 (Final Verdict & Standardized Signal Block)


## Adding a New Skill (12-step process)

See `ADDING-NEW-SKILLS.md` for the full walkthrough. Key steps:

1. Create `plugins/us-stock-analysis/skills/<name>/SKILL.md` with frontmatter
2. Create `prompts/<name>.md` — same content, no frontmatter, no platform-specific syntax
3. Skills are auto-discovered from the `skills/` directory — no changes needed in `plugin.json`
4. Bump version in **all three**: `plugin.json`, `.claude-plugin/marketplace.json` (both `metadata.version` and the plugin entry), and `package.json` (must match — see Version Consistency Rule)
5. Update `.cursor/rules/invest-skill.mdc`, `.github/copilot-instructions.md`, `GEMINI.md` (table row + example + directory tree)
6. Update `README.md` and platform-specific `README-*.md` files (framework table row + count)
7. **Update the site** (both English and Traditional Chinese — see Site Update Rule)
8. Add entry to `CHANGELOG.md`
9. Run `npm run pre-release` (pre-release-check + validate + `npm test`) to confirm all tests pass
10. Run `npm run build:site` to confirm the site builds and the new skill lands in the right category

## Site Update Rule

The public site (`site/`) is generated by `site/build/build-site.js` and deployed by CI — the `_site/` output is gitignored, so you commit **source**, not built HTML. **Whenever a skill is added, renamed, or removed, update the site in the same change:**

1. **`site/build/build-site.js` → `SKILL_CATEGORIES`** — add the skill to the correct category so it appears in the right group on `skills.html` (an unlisted skill still renders, but falls into a generic "Other" bucket). Keep these categories mirroring the README's framework table.
2. **`site/content/CHOOSE-A-SKILL.md` and `CHOOSE-A-SKILL-zh-TW.md`** — add a "goal → skill" row so users can discover it (both languages).
3. **`site/content/COOKBOOK.md` and `COOKBOOK-zh-TW.md`** — update the framework count and, if the skill warrants it, add a usage recipe (both languages).
4. Per-skill reference pages (`skill-<name>.html`) are auto-generated from `prompts/<name>.md` — no manual page needed.
5. Run `npm run build:site` and confirm: `All N frameworks` shows the new count, `skill-<name>.html` is generated, and the skill is not stranded under "Other".

Always update **both** the English and Traditional Chinese (`-zh-TW`) variants of any site content file you touch.

## Version Consistency Rule

All three version fields must match at all times:
- `plugins/us-stock-analysis/.claude-plugin/plugin.json` → `"version"`
- `.claude-plugin/marketplace.json` → `"metadata.version"` (and the plugin entry's `version`)
- `package.json` → `"version"`

Verify with: `jq '.version' plugins/us-stock-analysis/.claude-plugin/plugin.json && jq '.metadata.version' .claude-plugin/marketplace.json && jq '.version' package.json`

This is enforced by the consistency checks in `npm test`.

## Release Timing Rule

Choosing the version number and *when* to cut the release both matter — don't tag prematurely.

**Which number to bump (SemVer):**
- **MINOR** (`1.8.x → 1.9.0`) — a new skill/framework, or a meaningful new capability. (Adding `bear-case` was a minor bump.)
- **PATCH** (`1.9.0 → 1.9.1`) — fixes, doc/site tweaks, prompt refinements with no new skill.
- **MAJOR** (`1.x → 2.0.0`) — breaking changes to skill names, output contracts, or the plugin layout.

**When to stamp the date and tag:**
- The `## [X.Y.Z] - YYYY-MM-DD` heading in `CHANGELOG.md` must carry the **actual release date**, not the day you started the work. If the ship date is uncertain, keep the changes under `## [Unreleased]` and let the release step stamp the date when the release is actually cut.
- The git tag `vX.Y.Z` is created by `npm run release` (`release-interactive.js`), which commits the version bump, tags, and triggers CI. **Create the tag at release time — do not tag ahead of merge.** Preview first with `npm run release:dry-run`.
- Feature work lands on a branch → PR → merge to `main`; the tag/release is cut from `main` once merged. The manifest version can be bumped in the feature branch (tests require CHANGELOG ↔ manifest version parity), but the *tag* waits until the release is genuinely happening.
- Batch small changes: prefer one clean `1.9.0` release over tagging every intermediate commit. Cut the release when the set of changes is coherent and green (`npm run pre-release` passes).

## Framework Count Rule

The **advertised framework count** = number of skills in `plugins/us-stock-analysis/skills/` **minus output-only tools** (`report-generator`). It is currently **24 analysis frameworks** (25 skill directories − 1 output tool).

- Keep this number consistent across `README.md`, `README-zh-TW.md`, `site/content/CHOOSE-A-SKILL(-zh-TW).md`, `site/content/COOKBOOK(-zh-TW).md`, and `plugin.json`'s description.
- `site/build/build-site.js` derives it automatically (`FRAMEWORK_COUNT`) — never hardcode a count there.
- Enforced by the consistency checks in `npm test` (stale totals like 18/21 will fail):
  - **Test 11** checks the six site-facing `COUNT_DOCS` for "N frameworks" claims.
  - **Test 13** checks the cross-AI configs (`GEMINI.md`, `.cursor/rules/invest-skill.mdc`, `.github/copilot-instructions.md`) — every prompt must be referenced (a new skill can't be silently omitted from a platform), and every "N frameworks" claim must equal the advertised count. It also checks the COOKBOOK plugin-list skill counts equal the skill-directory count.

## Current State

- **Version**: 1.9.0 (plugin.json = marketplace.json = package.json)
- **Skills**: 25 directories in `plugins/us-stock-analysis/skills/` (auto-discovered)
- **Advertised frameworks**: 24 analysis frameworks (25 − `report-generator`)
- **Prompts**: 25 universal files in `prompts/` (one per skill, including `research-bundle` and `full-report`)
- **Node**: ≥18.0.0 required

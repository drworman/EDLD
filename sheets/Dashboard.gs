/**
 * EDLD mining dashboard — theme, header sorting, and formula repair.
 *
 * Lives beside Code.gs in the same Apps Script project: Extensions > Apps Script,
 * "+" > Script, name it Dashboard, paste this in, save, reload the spreadsheet.
 * It does not replace Code.gs. The two share nothing but the spreadsheet.
 *
 * What it does
 * ------------
 * Theme.   Sheets cannot colour a cell from a formula, so the hex codes on the
 *          Settings tab are only numbers until something applies them. This does,
 *          on every edit to Settings!B5:B21 or the Themes tab, and from the menu.
 *
 * Sorting. The dashboard table is a single FILTER formula, and Range.sort()
 *          cannot reorder a formula's output. Sorting is therefore done inside
 *          the formula, driven by the Sort By / Order cells (Dashboard!E5:F5).
 *          Those dropdowns work with no script at all. This adds click-to-sort:
 *          click a header to sort by it, click it again to reverse.
 *
 * Repair.  The xlsx template carries its Sheets-only formulas in the wrapper
 *          Google itself uses for export, and Sheets restores them on import.
 *          If that ever fails, ED Dashboard > Repair dashboard formulas rewrites
 *          them from FORMULAS below. build_dashboard.py reads FORMULAS from this
 *          file, so this is the one place they are defined.
 *
 *          It is also the upgrade. A sheet started from an older template
 *          keeps that template's table; Repair rewrites the formulas, the
 *          header list the sort reads, and the column layout, so pasting in a
 *          newer Dashboard.gs and running it brings the table up to date —
 *          the Notes column included — without re-importing anything.
 */

const ED = {
  SETTINGS: 'Settings',
  DASH: 'Dashboard',
  THEMES: 'Themes',
  QUERIES: 'Queries',
  THEME_CELL: 'B5',
  TITLE_FONT_CELL: 'B6',
  BODY_FONT_CELL: 'B7',
  ROLE_FIRST_ROW: 10,     // Settings!A10:A21 hold the role names
  ROLE_COUNT: 12,
  NOTES_ROW: 24,
  NOTES_LINES: 5,
  HEADER_ROW: 7,          // Dashboard row the table header lands on
  DATA_FIRST_ROW: 8,
  DATA_COLS: 10,          // A:J
  DASH_COLS: 11,          // A:K (K is a margin)
  NOTES_COL: 10,          // J, the one column of prose
  SORT_BY_CELL: 'E5',
  SORT_ORDER_CELL: 'F5',
  SORT_NAMES: 'D1:M1',    // Queries: plain header names, the Sort By list
  PARK_CELL: 'K7',        // where selection goes after a header click
  // The table's columns, in the order the FILTER below emits them. Must match
  // HEADERS in build_dashboard.py; tests/test_sheets_dashboard.py checks.
  HEADERS: ['System', 'Body', 'Gravity', 'Mining Site', 'Commodity',
            'Amount', 'Density', 'Rigs', 'Depleted', 'Notes'],
  // Column widths in pixels, A:K, for Repair to lay an older sheet out with.
  WIDTHS: [130, 160, 80, 100, 170, 95, 80, 60, 100, 280, 20],
  FALLBACK: {             // Classic HUD, used when a cell is blank or not #RRGGBB
    'Background': '#0A0A0A', 'Panel': '#16100A', 'Panel Alt': '#2B1E0E',
    'Accent': '#FF7100', 'Accent Text': '#0A0A0A', 'Title': '#FF8C1A',
    'Text': '#FFB266', 'Text Dim': '#9A5A1E', 'Border': '#4A2800',
    'Highlight': '#FFD24A', 'Warning': '#E0301E', 'Input Text': '#FFA040'
  }
};
const HEX = /^#[0-9a-f]{6}$/i;

/**
 * Sheets-only formulas. Keep each one a plain template literal with no ${}:
 * build_dashboard.py parses them out of this file by regex.
 *
 * The FILTER picks Deposits columns by letter, so it depends on COLUMNS in
 * Code.gs; tests/test_sheets_dashboard.py checks each letter against it. The
 * rank list in the SORT is AMOUNT_LEVELS from core/mining_db.py, lowest first,
 * and is checked too.
 */
const FORMULAS = {
  'Dashboard!A7': `=IF(
  AND(Dashboard!$A$5="", Dashboard!$B$5=""),
  "",
  {
    Queries!$D$2:$M$2;
    IFERROR(
      LET(
        dep, FILTER(
          {Deposits!B2:B, Deposits!D2:D, Deposits!G2:G, Deposits!K2:K, Deposits!L2:L,
           Deposits!Q2:Q, Deposits!P2:P, Deposits!R2:R, Deposits!X2:X, Deposits!Y2:Y},
          (Dashboard!$A$5="") + (Deposits!B2:B=Dashboard!$A$5) > 0,
          (Dashboard!$B$5="") + (Deposits!L2:L=Dashboard!$B$5) > 0,
          Deposits!W2:W <> 1
        ),
        sortkey, INDEX(dep, 0, Queries!$N$1),
        SORT(
          dep,
          ARRAYFORMULA(IFERROR(MATCH(sortkey, {"Low";"Medium";"High"}, 0), sortkey)),
          Queries!$N$2
        )
      ),
      {"No deposits match this filter","","","","","","","","",""}
    )
  }
)`,
  'Queries!A1': `=IFERROR(SORT(UNIQUE(FILTER(Deposits!B2:B, Deposits!B2:B<>"", Deposits!W2:W<>1))), "")`,
  'Queries!B1': `=IFERROR(SORT(UNIQUE(FILTER(Deposits!L2:L, Deposits!L2:L<>"", Deposits!W2:W<>1))), "")`
};

// ------------------------------------------------------------------ triggers & menu

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('ED Dashboard')
    .addItem('Apply theme', 'applyTheme')
    .addItem('Copy active theme to Custom', 'copyActiveToCustom')
    .addSeparator()
    .addItem('Repair dashboard formulas', 'repairFormulas')
    .addToUi();
}

function onEdit(e) {
  if (!e || !e.range) return;
  const name = e.range.getSheet().getName();
  if (name === ED.THEMES) { applyTheme(); return; }
  if (name !== ED.SETTINGS) return;
  const lastRoleRow = ED.ROLE_FIRST_ROW + ED.ROLE_COUNT - 1;
  const touchesCol = e.range.getColumn() <= 2 && e.range.getLastColumn() >= 2;
  const touchesRows = e.range.getLastRow() >= 5 && e.range.getRow() <= lastRoleRow;
  if (touchesCol && touchesRows) applyTheme();
}

/**
 * Click-to-sort. A click on a header cell sets Sort By to that column, or flips
 * Order if it already is, then moves the selection off the header so the next
 * click on the same header fires again. Viewers without edit access can still
 * use the table; their clicks just do nothing.
 */
function onSelectionChange(e) {
  const r = e && e.range;
  if (!r || r.getNumRows() !== 1 || r.getNumColumns() !== 1) return;
  if (r.getRow() !== ED.HEADER_ROW || r.getColumn() > ED.DATA_COLS) return;
  const sh = r.getSheet();
  if (sh.getName() !== ED.DASH) return;
  if (sh.getRange(ED.HEADER_ROW, 1).getDisplayValue() === '') return;  // no table yet

  const names = sh.getParent().getSheetByName(ED.QUERIES)
    .getRange(ED.SORT_NAMES).getDisplayValues()[0];
  const name = names[r.getColumn() - 1];
  if (!name) return;

  const by = sh.getRange(ED.SORT_BY_CELL);
  const order = sh.getRange(ED.SORT_ORDER_CELL);
  if (by.getDisplayValue() === name) {
    order.setValue(order.getDisplayValue() === 'Descending' ? 'Ascending' : 'Descending');
  } else {
    by.setValue(name);
    order.setValue('Ascending');
  }
  sh.getRange(ED.PARK_CELL).activate();
}

// ------------------------------------------------------------------ public actions

function applyTheme() {
  const ss = SpreadsheetApp.getActive();
  const t = readTheme_(ss);
  const dash = ss.getSheetByName(ED.DASH);
  const set = ss.getSheetByName(ED.SETTINGS);
  const thm = ss.getSheetByName(ED.THEMES);
  if (dash) styleDashboard_(dash, t);
  if (set) styleSettings_(set, t);
  if (thm) styleThemes_(thm, t);
}

/** Copies the currently active colours into the Custom column and switches Theme to Custom. */
function copyActiveToCustom() {
  const ss = SpreadsheetApp.getActive();
  const st = ss.getSheetByName(ED.SETTINGS);
  const t = readTheme_(ss);
  st.getRange(ED.ROLE_FIRST_ROW, 2, ED.ROLE_COUNT, 1)
    .setValues(t.roles.map(r => [t.c[r]]));
  st.getRange(ED.THEME_CELL).setValue('Custom');
  applyTheme(); // programmatic edits don't fire onEdit
}

/**
 * Rewrites the Sheets-only formulas, clearing each one's spill area first, and
 * brings the table's helpers and layout up to the current column set: the
 * header names and sort arrows on Queries, the Sort By list, column widths,
 * and wrapping on the Notes column. A sheet from an older template comes out
 * the same as a fresh one.
 */
function repairFormulas() {
  const ss = SpreadsheetApp.getActive();
  const dash = ss.getSheetByName(ED.DASH);
  const q = ss.getSheetByName(ED.QUERIES);
  const H = ED.HEADERS, n = H.length;

  // Room for the layout below, on a sheet somebody has trimmed.
  if (dash.getMaxColumns() < ED.DASH_COLS)
    dash.insertColumnsAfter(dash.getMaxColumns(), ED.DASH_COLS - dash.getMaxColumns());
  if (q.getMaxColumns() < 15)
    q.insertColumnsAfter(q.getMaxColumns(), 15 - q.getMaxColumns());

  // Everything the older layout wrote, one column wider for the margin.
  dash.getRange(ED.HEADER_ROW, 1, dash.getMaxRows() - ED.HEADER_ROW + 1, ED.DASH_COLS).clearContent();
  q.getRange(1, 1, q.getMaxRows(), q.getMaxColumns()).clearContent();

  // Queries helpers: names (the Sort By list), names with the sort arrow (the
  // table header), the sort column index and direction.
  q.getRange(1, 4, 1, n).setValues([H]);
  const arrows = H.map((_, i) => {
    const c = String.fromCharCode(68 + i);     // D, E, ...
    return `=${c}1&IF(${c}1=Dashboard!$E$5,IF(Dashboard!$F$5="Descending"," ▼"," ▲"),"")`;
  });
  q.getRange(2, 4, 1, n).setFormulas([arrows]);
  const last = String.fromCharCode(68 + n - 1);
  q.getRange('N1').setFormula(`=IFERROR(MATCH(Dashboard!$E$5,$D$1:$${last}$1,0),1)`);
  q.getRange('N2').setFormula('=Dashboard!$F$5<>"Descending"');
  q.getRange('O1:O2').setValues([['← sort column index'], ['← ascending?']]);

  Object.keys(FORMULAS).forEach(key => {
    const [sheet, a1] = key.split('!');
    ss.getSheetByName(sheet).getRange(a1).setFormula(FORMULAS[key]);
  });

  dash.getRange(ED.SORT_BY_CELL).setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireValueInRange(q.getRange(ED.SORT_NAMES), true).build());

  // Layout: widths across A:K, the margin column shown, everything past it
  // hidden, and the Notes column wrapped so a long note reads as a paragraph.
  ED.WIDTHS.forEach((w, i) => dash.setColumnWidth(i + 1, w));
  dash.showColumns(1, ED.DASH_COLS);
  const maxC = dash.getMaxColumns();
  if (maxC > ED.DASH_COLS) dash.hideColumns(ED.DASH_COLS + 1, maxC - ED.DASH_COLS);
  const dataRows = dash.getMaxRows() - ED.DATA_FIRST_ROW + 1;
  dash.getRange(ED.DATA_FIRST_ROW, 1, dataRows, ED.DATA_COLS).setVerticalAlignment('top');
  dash.getRange(ED.HEADER_ROW, ED.NOTES_COL, dataRows + 1, 1)
    .setWrap(true).setHorizontalAlignment('left');

  // Sheets from before depletion became a date alone carry the word in the
  // amount column. EDLD ignores it on read; clear it so the table does too.
  const deps = ss.getSheetByName('Deposits');
  if (deps && deps.getLastRow() > 1) {
    const head = deps.getRange(1, 1, 1, deps.getLastColumn()).getValues()[0];
    const col = head.indexOf('amount') + 1;
    if (col > 0) {
      const rng = deps.getRange(2, col, deps.getLastRow() - 1, 1);
      const vals = rng.getValues();
      if (vals.some(v => v[0] === 'Depleted')) {
        rng.setValues(vals.map(v => [v[0] === 'Depleted' ? '' : v[0]]));
      }
    }
  }

  applyTheme();
  ss.toast('Dashboard formulas and layout rewritten.', 'ED Dashboard');
}

// ------------------------------------------------------------------ theme resolution

function readTheme_(ss) {
  const st = ss.getSheetByName(ED.SETTINGS);
  const th = ss.getSheetByName(ED.THEMES);
  const R0 = ED.ROLE_FIRST_ROW, N = ED.ROLE_COUNT;

  const roles = st.getRange(R0, 1, N, 1).getDisplayValues().map(r => r[0].trim());
  const custom = st.getRange(R0, 2, N, 1).getDisplayValues().map(r => r[0].trim());
  const name = st.getRange(ED.THEME_CELL).getDisplayValue().trim();

  // Resolve from the Themes tab directly rather than Settings!D, so the result
  // never depends on whether the Active column has recalculated yet.
  let source = custom;
  if (name && name.toLowerCase() !== 'custom' && th) {
    const data = th.getDataRange().getDisplayValues();
    const col = data[0].map(s => s.trim()).indexOf(name);
    if (col > 0) {
      const byRole = {};
      data.slice(1).forEach(row => { byRole[row[0].trim()] = (row[col] || '').trim(); });
      source = roles.map(r => byRole[r] || '');
    }
  }

  const c = {};
  Object.keys(ED.FALLBACK).forEach(role => {
    const i = roles.indexOf(role);
    let v = i >= 0 ? source[i] : '';
    if (!HEX.test(v)) v = (i >= 0 && HEX.test(custom[i])) ? custom[i] : ED.FALLBACK[role];
    c[role] = v.toUpperCase();
  });

  return {
    c: c,
    roles: roles,
    custom: custom,
    titleFont: st.getRange(ED.TITLE_FONT_CELL).getDisplayValue().trim() || 'Orbitron',
    bodyFont: st.getRange(ED.BODY_FONT_CELL).getDisplayValue().trim() || 'Exo 2'
  };
}

function contrast_(hex) {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return (0.299 * r + 0.587 * g + 0.114 * b) > 140 ? '#000000' : '#FFFFFF';
}

// ------------------------------------------------------------------ Dashboard

function styleDashboard_(sh, t) {
  const c = t.c, D = ED.DATA_COLS, maxR = sh.getMaxRows();
  const SOLID = SpreadsheetApp.BorderStyle.SOLID;
  sh.setHiddenGridlines(true);
  sh.setTabColor(c['Accent']);

  // Base layer
  sh.getRange(1, 1, maxR, ED.DASH_COLS)
    .setBackground(c['Background'])
    .setFontColor(c['Text'])
    .setFontFamily(t.bodyFont)
    .setFontSize(10)
    .setFontWeight('normal')
    .setFontStyle('normal')
    .setBorder(false, false, false, false, false, false);

  // Title block
  sh.getRange('A1').setFontFamily(t.titleFont).setFontSize(20)
    .setFontWeight('bold').setFontColor(c['Title']);
  sh.getRange('A2').setFontColor(c['Text Dim']).setFontStyle('italic');
  sh.getRange('E2').setFontColor(c['Text Dim']).setFontSize(9);
  sh.getRange(3, 1, 1, D).setBackground(c['Accent']);           // HUD stripe

  // Filter and sort controls
  sh.getRangeList(['A4:B4', 'E4:F4']).setFontColor(c['Text Dim'])
    .setFontWeight('bold').setFontSize(9);
  sh.getRangeList(['A5:B5', 'E5:F5']).setBackground(c['Panel'])
    .setFontColor(c['Input Text']).setFontWeight('bold')
    .setBorder(true, true, true, true, true, false, c['Accent'], SOLID);

  // Conditional formatting, rebuilt every time. Sheets applies the first rule
  // that matches, so the specific rules go before the general ones — and every
  // pair that could overlap is also written to be mutually exclusive, so order
  // only matters between High/Low and the plain banding.
  const r0 = ED.DATA_FIRST_ROW, n = maxR - r0 + 1;
  const header = sh.getRange(ED.HEADER_ROW, 1, 1, D);
  const all = sh.getRange(r0, 1, n, D);
  const hilo = sh.getRange(r0, 6, n, 2);                          // Amount, Density
  const bands = [[0, c['Panel']], [1, c['Panel Alt']]];           // row 8 is even
  const mk = (range, formula, bg, fg, o) => {
    let b = SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied(formula).setRanges([range])
      .setBackground(bg).setFontColor(fg);
    if (o && o.bold) b = b.setBold(true);
    if (o && o.italic) b = b.setItalic(true);
    if (o && o.strike) b = b.setStrikethrough(true);
    return b.build();
  };
  const rules = [];
  const h = ED.HEADER_ROW;
  rules.push(mk(header, `=$A$${h}<>""`, c['Accent'], c['Accent Text'], { bold: true }));
  bands.forEach(([p, bg]) => {
    rules.push(mk(hilo, `=AND($A${r0}<>"",$I${r0}="",F${r0}="High",MOD(ROW(),2)=${p})`,
      bg, c['Highlight'], { bold: true }));
    rules.push(mk(hilo, `=AND($A${r0}<>"",$I${r0}="",F${r0}="Low",MOD(ROW(),2)=${p})`,
      bg, c['Text Dim']));
  });
  bands.forEach(([p, bg]) => rules.push(mk(all,
    `=AND($A${r0}<>"",$I${r0}<>"",MOD(ROW(),2)=${p})`, bg, c['Warning'], { italic: true, strike: true })));
  bands.forEach(([p, bg]) => rules.push(mk(all,
    `=AND($A${r0}<>"",$I${r0}="",MOD(ROW(),2)=${p})`, bg, c['Text'])));
  sh.setConditionalFormatRules(rules);   // replaces all CF rules on Dashboard
}

// ------------------------------------------------------------------ Settings

function styleSettings_(sh, t) {
  const c = t.c, R0 = ED.ROLE_FIRST_ROW, N = ED.ROLE_COUNT;
  const SOLID = SpreadsheetApp.BorderStyle.SOLID;
  const maxR = Math.max(sh.getLastRow() + 5, 40);
  sh.setHiddenGridlines(true);
  sh.setTabColor(c['Text Dim']);

  sh.getRange(1, 1, maxR, 8).setBackground(c['Background']).setFontColor(c['Text'])
    .setFontFamily(t.bodyFont).setFontWeight('normal').setFontStyle('normal')
    .setBorder(false, false, false, false, false, false);

  sh.getRangeList(['A1:A2', 'A5:A7']).setFontColor(c['Text Dim']).setFontWeight('bold');
  sh.getRangeList(['B1:B2', 'B5:B7']).setBackground(c['Panel'])
    .setFontColor(c['Input Text']).setFontWeight('bold')
    .setBorder(null, null, true, null, null, null, c['Accent'], SOLID);
  sh.getRange('D1').setFontColor(c['Text Dim']).setFontSize(9);
  sh.getRange('C5:C6').setFontColor(c['Text Dim']).setFontStyle('italic').setFontSize(9);
  sh.getRange('A4').setFontFamily(t.titleFont).setFontColor(c['Title'])
    .setFontWeight('bold').setFontSize(12);

  // Colour table
  sh.getRange(R0 - 1, 1, 1, 6).setBackground(c['Accent'])
    .setFontColor(c['Accent Text']).setFontWeight('bold');
  const bgs = [];
  for (let i = 0; i < N; i++) {
    const band = i % 2 ? c['Panel Alt'] : c['Panel'];
    const cust = HEX.test(t.custom[i]) ? t.custom[i] : c['Background'];
    const active = c[t.roles[i]] || c['Background'];
    bgs.push([band, band, cust, band, active, band]);
  }
  sh.getRange(R0, 1, N, 6).setBackgrounds(bgs)
    .setBorder(null, null, null, null, null, true, c['Border'], SOLID);
  sh.getRange(R0, 2, N, 1).setFontColor(c['Input Text']).setFontFamily('Share Tech Mono')
    .setFontWeight('bold').setHorizontalAlignment('center');
  sh.getRange(R0, 4, N, 1).setFontFamily('Share Tech Mono').setHorizontalAlignment('center');
  sh.getRange(R0, 6, N, 1).setFontColor(c['Text Dim']).setFontStyle('italic');
  [3, 5].forEach(col => sh.getRange(R0, col, N, 1)
    .setBorder(true, true, true, true, null, true, c['Border'], SOLID));

  // Notes
  sh.getRange(ED.NOTES_ROW, 1).setFontFamily(t.titleFont).setFontColor(c['Title'])
    .setFontWeight('bold').setFontSize(10);
  sh.getRange(ED.NOTES_ROW + 1, 1, ED.NOTES_LINES, 1).setFontColor(c['Text Dim']);
}

// ------------------------------------------------------------------ Themes tab

function styleThemes_(sh, t) {
  const c = t.c;
  sh.setHiddenGridlines(true);
  const lastR = sh.getLastRow(), lastC = sh.getLastColumn();
  if (lastR < 2 || lastC < 2) return;
  sh.getRange(1, 1, 1, lastC).setBackground(c['Accent'])
    .setFontColor(c['Accent Text']).setFontWeight('bold');
  const vals = sh.getRange(2, 2, lastR - 1, lastC - 1).getDisplayValues();
  const bgs = vals.map(row => row.map(v => HEX.test(v.trim()) ? v.trim() : c['Background']));
  const fgs = bgs.map(row => row.map(contrast_));
  sh.getRange(2, 2, lastR - 1, lastC - 1).setBackgrounds(bgs).setFontColors(fgs);
  sh.getRange(2, 1, lastR - 1, 1).setBackground(c['Panel']).setFontColor(c['Text']);
}

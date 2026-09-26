/**
 * EDLD sheet — building the dashboard's tabs where a sheet has none.
 *
 * Bundled with Code.gs, Dashboard.gs and Upgrade.gs into edld_sheet.js. A
 * sheet made by pasting Loader.gs into a blank spreadsheet has nothing but
 * Google's empty first tab, and a sheet set up years ago may have only
 * Deposits. Both should end up where a sheet started from
 * Mining_Dashboard.xlsx does, without anybody importing a file.
 *
 * The content — labels, placeholders, presets, fonts, notes, formulas — is
 * TEMPLATE, which build_bundle.py copies out of build_dashboard.py, the same
 * constants the xlsx is built from; tests/test_sheets_template.py builds tabs
 * here and compares them with that file. Layout that Repair already owns (the
 * Queries helpers, the table formula, the Dashboard's widths) is left to
 * rebuildDashboard_(), and every colour and font to applyTheme(), so each has
 * one author.
 *
 * Only missing tabs are built. A tab that exists is never rewritten, because
 * what is in it — the squadron's name, a chosen theme, custom colours — is
 * the owner's.
 */

/** Characters of column width, as openpyxl counts them, to pixels. */
function chars_(w) { return Math.round(w * 7 + 5); }

/**
 * Template text as a cell value. Code.gs's _cell() marks text that Sheets
 * would otherwise read as something else: a leading apostrophe is Sheets'
 * own "this is text" marker and is dropped, so "'High' amount / density"
 * arrived as "High' amount / density". Formulas the template means as
 * formulas are written without it.
 */
function text_(v) { return _cell(v); }
function texts_(rows) { return rows.map(row => row.map(text_)); }

/**
 * Create whichever of Themes, Settings, Queries and Dashboard are missing.
 * Returns the names created. Deposits is Code.gs's own (_sheet()).
 */
function ensureTemplate_(ss) {
  const made = [];
  const has = name => !!ss.getSheetByName(name);
  // Themes before Settings (its Active column and Theme list read Themes),
  // Settings and Queries before Dashboard (its title and filter lists read
  // them).
  if (!has(ED.THEMES)) { buildThemes_(ss); made.push(ED.THEMES); }
  if (!has(ED.SETTINGS)) { buildSettings_(ss); made.push(ED.SETTINGS); }
  _sheet();
  if (!has(ED.QUERIES)) { ss.insertSheet(ED.QUERIES).hideSheet(); made.push(ED.QUERIES); }
  if (!has(ED.DASH)) { buildDashboardTab_(ss); made.push(ED.DASH); }
  if (made.length) dropBlankDefaultTab_(ss);
  return made;
}

/**
 * Google's own first tab — "Sheet1", empty — once there are real tabs beside
 * it. Only a tab with that kind of name and nothing at all in it is removed.
 */
function dropBlankDefaultTab_(ss) {
  ss.getSheets().forEach(sh => {
    if (/^Sheet\s?\d+$/.test(sh.getName()) && sh.getLastRow() === 0 &&
        sh.getLastColumn() === 0 && ss.getSheets().length > 1) {
      ss.deleteSheet(sh);
    }
  });
}

/**
 * Settings!D1 names the release, for the Dashboard's corner. Rewritten each
 * upgrade, but only while it still reads as ours: an owner's own text there
 * is theirs.
 */
function refreshVersionLine_(ss) {
  const st = ss.getSheetByName(ED.SETTINGS);
  if (!st) return;
  const cell = st.getRange('D1');
  const now = String(cell.getValue() || '');
  const ours = new RegExp('^' + TEMPLATE.VERSION_LINE
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace('\\{version\\}', '\\S+') + '$');
  if (now === '' || ours.test(now)) {
    cell.setValue(text_(TEMPLATE.VERSION_LINE.replace('{version}', EDLD_VERSION)));
  }
}

function buildThemes_(ss) {
  const T = TEMPLATE, names = Object.keys(T.THEMES);
  const th = ss.insertSheet(ED.THEMES);
  const rows = [['Color Role'].concat(names, ['Custom']).map(text_)];
  T.ROLES.forEach((role, i) => {
    rows.push([text_(role[0])].concat(names.map(n => text_(T.THEMES[n][i])),
                                      ['=Settings!$B$' + (T.ROLE_ROW0 + i)]));
  });
  th.getRange(1, 1, rows.length, rows[0].length).setValues(rows);
  th.getRange(T.ROLES.length + 3, 1).setValue(text_(T.THEMES_NOTE));
  th.getRange(1, 2, rows.length, rows[0].length - 1).setHorizontalAlignment('center');
  th.setColumnWidth(1, chars_(T.THEMES_WIDTHS[0]));
  for (let c = 2; c <= rows[0].length; c++) th.setColumnWidth(c, chars_(T.THEMES_WIDTHS[1]));
  th.setFrozenRows(1);
  th.setFrozenColumns(1);
  th.hideSheet();
}

function buildSettings_(ss) {
  const T = TEMPLATE, R0 = T.ROLE_ROW0, n = T.ROLES.length;
  const st = ss.insertSheet(ED.SETTINGS, 0);

  Object.keys(T.SETTINGS_LABELS).forEach(a =>
    st.getRange(a).setValue(text_(T.SETTINGS_LABELS[a])));
  st.getRange('B1:B2').setValues(texts_([[T.PLACEHOLDER_SQUADRON], [T.PLACEHOLDER_MAINTAINER]]));
  st.getRange('B5:B7').setValues(texts_([[T.DEFAULT_THEME], [T.TITLE_FONT], [T.BODY_FONT]]));
  Object.keys(T.SETTINGS_HINTS).forEach(a =>
    st.getRange(a).setValue(text_(T.SETTINGS_HINTS[a])));
  st.getRange('D1:H1').merge().setHorizontalAlignment('right');
  st.getRange('D1').setValue(text_(T.VERSION_LINE.replace('{version}', EDLD_VERSION)));

  // The colour table: role, the owner's hex (Classic HUD to start), a swatch,
  // the active hex, a swatch, what the role colours.
  st.getRange(R0 - 1, 1, 1, T.COLOR_TABLE_HEADERS.length)
    .setValues(texts_([T.COLOR_TABLE_HEADERS]));
  const classic = T.THEMES[T.DEFAULT_THEME];
  const table = T.ROLES.map((role, i) => {
    const r = R0 + i;
    return [text_(role[0]), text_(classic[i]), '',
            '=IFERROR(INDEX(Themes!$B$2:$Z$50,MATCH($A' + r + ',Themes!$A$2:$A$50,0),' +
            'MATCH($B$5,Themes!$B$1:$Z$1,0)),B' + r + ')',
            '', text_(role[1])];
  });
  st.getRange(R0, 1, n, 6).setValues(table);
  st.getRange(T.NOTES_ROW, 1, T.SETTINGS_NOTES.length, 1)
    .setValues(T.SETTINGS_NOTES.map(line => [text_(line)]));

  // The same validation the xlsx carries: a preset from Themes, a font from
  // the list (others allowed), a hex code in the Custom column.
  const themes = ss.getSheetByName(ED.THEMES);
  st.getRange('B5').setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInRange(themes.getRange('B1:Z1'), true).setAllowInvalid(false).build());
  st.getRange('B6:B7').setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInList(T.FONTS, true).setAllowInvalid(true).build());
  st.getRange(R0, 2, n, 1).setDataValidation(SpreadsheetApp.newDataValidation()
    .requireFormulaSatisfied('=AND(LEN(B' + R0 + ')=7,LEFT(B' + R0 + ',1)="#",' +
                             'ISNUMBER(HEX2DEC(MID(B' + R0 + ',2,6))))')
    .setAllowInvalid(false).setHelpText(T.HEX_ERROR).build());

  T.SETTINGS_WIDTHS.forEach((w, i) => st.setColumnWidth(i + 1, chars_(w)));
}

function buildDashboardTab_(ss) {
  const T = TEMPLATE, n = ED.HEADERS.length;
  const dash = ss.insertSheet(ED.DASH, 0);
  const q = ss.getSheetByName(ED.QUERIES);

  dash.getRange('A1').setFormula(T.DASH_TITLE_FORMULA);
  dash.getRange('A2').setFormula(T.DASH_SUBTITLE_FORMULA);
  dash.getRange(2, 5, 1, n - 4).merge().setHorizontalAlignment('right');
  dash.getRange('E2').setFormula('=Settings!D1');
  Object.keys(T.DASH_LABELS).forEach(a =>
    dash.getRange(a).setValue(text_(T.DASH_LABELS[a])));
  dash.getRange('E5:F5').setValues(texts_([[ED.HEADERS[0], T.SORT_ORDERS[0]]]));

  // Filter lists come from Queries A and B; Sort By is set by Repair.
  [['A5', 'A1:A1000'], ['B5', 'B1:B1000']].forEach(([cell, src]) =>
    dash.getRange(cell).setDataValidation(SpreadsheetApp.newDataValidation()
      .requireValueInRange(q.getRange(src), true).setAllowInvalid(true).build()));
  dash.getRange('F5').setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInList(T.SORT_ORDERS, true).setAllowInvalid(false).build());

  dash.setRowHeight(1, 38);
  dash.setRowHeight(3, 4);
  dash.setRowHeight(5, 22);
  dash.setRowHeight(ED.HEADER_ROW, 24);
  dash.setFrozenRows(ED.HEADER_ROW);

  const rows = dash.getMaxRows() - ED.DATA_FIRST_ROW + 1, r0 = ED.DATA_FIRST_ROW;
  dash.getRange(r0, 3, rows, 1).setNumberFormat('0.000" g"');
  dash.getRange(r0, 4, rows, 1).setNumberFormat('0');
  dash.getRange(r0, 8, rows, 1).setNumberFormat('0');
  dash.getRange(ED.HEADER_ROW, 1, rows + 1, n).setHorizontalAlignment('center');
  [1, 2, 5].forEach(c => dash.getRange(ED.HEADER_ROW, c, rows + 1, 1)
    .setHorizontalAlignment('left'));
}

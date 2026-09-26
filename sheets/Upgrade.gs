/**
 * EDLD sheet — the sheet's own upgrade steps.
 *
 * Bundled with Code.gs, Dashboard.gs and Template.gs into edld_sheet.js. Loader.gs installs
 * a new bundle and then calls upgradeSheet() from it, so the steps that run
 * are always the ones that shipped with the code they prepare the sheet for.
 *
 * The sheet's layout version is kept in its document properties as
 * EDLD_SHEET_VERSION. A sheet from before there was a version — anything set
 * up by pasting Code.gs, with or without the dashboard template — has none,
 * and is version 0. Each entry in SHEET_MIGRATIONS brings a sheet to its `to`
 * version; upgradeSheet() runs every entry above the sheet's version, in
 * order, and records each as it completes, so an interrupted upgrade resumes
 * where it stopped.
 *
 * Rules for a step:
 *   - Safe to run twice. It is re-run if the one after it fails.
 *   - Deposits is only ever added to. No column is moved or removed, because
 *     every EDLD writing to the sheet addresses columns by position.
 *   - Settings values are the owner's. A step may add a row, never rewrite one.
 *   - A tab that exists keeps what is in it. Missing dashboard tabs are
 *     built (Template.gs), so a blank spreadsheet, a receiver-only sheet and
 *     one started from the xlsx all end up the same.
 *
 * Append new steps; never edit one that has shipped.
 */

var SHEET_VERSION_PROPERTY = 'EDLD_SHEET_VERSION';

/** Oldest Loader.gs this bundle can run under. Raised only when it must be. */
var MIN_LOADER = 1;

var SHEET_MIGRATIONS = [
  {
    to: 1,
    name: 'Notes and assessment columns; Notes on the dashboard; depletion as a date',
    run: function (ss) {
      _sheet();                 // Code.gs: widens the Deposits header in place
      tidyDeposits_(ss);
      if (rebuildDashboard_(ss)) applyTheme();
    }
  },
  {
    to: 2,
    name: 'Dashboard, Settings and Themes tabs, where the sheet has none',
    run: function (ss) {
      var made = ensureTemplate_(ss);
      if (rebuildDashboard_(ss)) applyTheme();
      return made.length ? 'added ' + made.join(', ') : 'all present';
    }
  }
];

/** The layout version the steps above bring a sheet to. */
var SHEET_VERSION = SHEET_MIGRATIONS[SHEET_MIGRATIONS.length - 1].to;

function sheetVersion_() {
  return Number(PropertiesService.getDocumentProperties()
                  .getProperty(SHEET_VERSION_PROPERTY) || 0);
}

/**
 * Bring the sheet to SHEET_VERSION. Returns what was done, for the loader to
 * report. Backs up Deposits first whenever there is anything to do.
 */
function upgradeSheet() {
  var ss = SpreadsheetApp.getActive();
  var doc = PropertiesService.getDocumentProperties();
  var have = sheetVersion_();
  var todo = SHEET_MIGRATIONS.filter(function (m) { return m.to > have; });
  var result = { from: have, to: have, steps: [], backup: '' };
  refreshVersionLine_(ss);        // every install, steps or not
  if (!todo.length) return result;

  result.backup = backupDeposits_(ss);
  for (var i = 0; i < todo.length; i++) {
    var detail = todo[i].run(ss);
    doc.setProperty(SHEET_VERSION_PROPERTY, String(todo[i].to));
    result.to = todo[i].to;
    result.steps.push(todo[i].name + (detail ? ' — ' + detail : ''));
  }
  return result;
}

/**
 * A hidden copy of Deposits, named for when it was taken. Nothing is deleted:
 * a backup is only worth having if it is still there when somebody notices
 * they need it, and they can remove old ones themselves. Returns its name,
 * or '' when there were no rows to protect.
 */
function backupDeposits_(ss) {
  var deps = ss.getSheetByName(SHEET_NAME);
  if (!deps || deps.getLastRow() < 2) return '';
  var stamp = Utilities.formatDate(new Date(), Session.getScriptTimeZone(),
                                   'yyyy-MM-dd HHmm');
  var name = SHEET_NAME + ' backup ' + stamp;
  var n = 2;
  while (ss.getSheetByName(name)) name = SHEET_NAME + ' backup ' + stamp + ' (' + (n++) + ')';
  var copy = deps.copyTo(ss);
  copy.setName(name);
  copy.hideSheet();
  return name;
}

/**
 * Deposits as the current rules expect them, without changing what any row
 * says. "Depleted" leaves the amount column — depletion is the date alone —
 * and a depletion date Sheets parsed into a date becomes the plain day it was
 * sent as, so the table and a fetch agree on which day it was.
 */
function tidyDeposits_(ss) {
  var deps = ss.getSheetByName(SHEET_NAME);
  if (!deps || deps.getLastRow() < 2) return;
  var head = deps.getRange(1, 1, 1, deps.getLastColumn()).getValues()[0];
  var rows = deps.getLastRow() - 1;

  var amount = head.indexOf('amount') + 1;
  if (amount > 0) {
    var ar = deps.getRange(2, amount, rows, 1);
    var av = ar.getValues();
    if (av.some(function (v) { return v[0] === 'Depleted'; })) {
      ar.setValues(av.map(function (v) { return [v[0] === 'Depleted' ? '' : v[0]]; }));
    }
  }

  var depleted = head.indexOf('depleted_on') + 1;
  if (depleted > 0) {
    var dr = deps.getRange(2, depleted, rows, 1);
    var dv = dr.getValues();
    var isDate = function (v) {
      return Object.prototype.toString.call(v) === '[object Date]';
    };
    if (dv.some(function (v) { return isDate(v[0]); })) {
      // Every cell is written back as text, not only the converted ones: a
      // day already stored as text would otherwise be parsed on the way in.
      dr.setValues(dv.map(function (v) {
        return [v[0] === '' || v[0] === null ? '' : "'" + _day(v[0])];
      }));
    }
  }
}

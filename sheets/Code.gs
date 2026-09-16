/**
 * EDLD surface survey — Google Sheets receiver.
 *
 * Deploy this bound to the spreadsheet you want deposits written to. EDLD
 * POSTs batches of deposits here; this script decides what is new, what has
 * changed, and what to ignore.
 *
 * Setup is in sheets/README.md. The short version: Extensions > Apps Script,
 * paste this in, set TOKEN below, Deploy > New deployment > Web app,
 * "Execute as: Me", "Who has access: Anyone with the link".
 *
 * Why the dedupe lives here rather than in EDLD
 * ---------------------------------------------
 * A squadron sheet has several commanders writing to it, and none of them can
 * see the others' local stores. Only the sheet knows what is already in the
 * sheet. Put the check on the client and two commanders who find the same
 * deposit in the same evening both append it, because each was right about
 * what it had seen. Here, LockService serialises them and the second one
 * updates the first one's row.
 *
 * Matching is exact string equality on deposit_id. EDLD works out the geometry
 * — same system, same body, same commodity, within 75 m — and hands over a
 * stable id. This script never needs to know a deposit has moved a few metres.
 */

// ── Configuration ────────────────────────────────────────────────────────────

/**
 * Shared secret. EDLD sends it as "Authorization: Bearer <token>"; Apps Script
 * strips that header from web app requests, so it is re-sent in the body too
 * and read from there. Change it to something long and random before you
 * deploy, and change it again to revoke access — anyone holding the old one
 * stops being able to write, and the URL does not have to change.
 */
var TOKEN = 'CHANGE-ME-BEFORE-DEPLOYING';

/** Sheet tab that deposits are written to. Created if absent. */
var SHEET_NAME = 'Deposits';

/**
 * Column order. This is a contract with core/sheets_publish.py — the client
 * sends objects, this array decides where each value lands, so adding a field
 * means appending here and in the client's COLUMNS. Never reorder: existing
 * rows are positional.
 */
var COLUMNS = [
  'deposit_id',
  'system',
  'system_address',
  'body',
  'body_id',
  'planet_class',
  'gravity',
  'body_radius_m',
  'atmosphere',
  'volcanism',
  'signal_no',
  'commodity',
  'latitude',
  'longitude',
  'density_claimed',
  'density_observed',
  'amount',
  'rigs',
  'refine_count',
  'first_seen',
  'last_confirmed',
  'reported_by',
  'is_test'
];

/** Fields a later report is allowed to overwrite on an existing row. */
var MUTABLE = [
  'density_claimed', 'density_observed', 'amount', 'rigs', 'refine_count',
  'last_confirmed', 'signal_no', 'planet_class', 'gravity', 'body_radius_m',
  'atmosphere', 'volcanism', 'system', 'body'
];

// ── Entry points ─────────────────────────────────────────────────────────────

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');

    if (!TOKEN || TOKEN === 'CHANGE-ME-BEFORE-DEPLOYING') {
      return _json({ ok: false, error: 'server token not configured' });
    }
    if (String(body.token || '') !== TOKEN) {
      return _json({ ok: false, error: 'bad token' });
    }

    if (body.ping) {
      return _json({ ok: true, pong: true, columns: COLUMNS.length });
    }

    // Read: everything this sheet knows about one body.
    //
    // The write half alone made the survey a place to send data and never a
    // place to get any, which left the in-game compass pointing only at
    // deposits the commander had already found — something the game's own HUD
    // already shows them. The point of a shared sheet is the deposits somebody
    // else found.
    if (body.fetch) {
      return _json(_read(body.fetch));
    }

    var deposits = body.deposits;
    if (!deposits || !deposits.length) {
      return _json({ ok: true, added: 0, updated: 0, unchanged: 0 });
    }

    return _json(_write(deposits));
  } catch (err) {
    // Returned rather than thrown: a thrown error becomes an HTML error page
    // that the client cannot parse, so the failure would reach EDLD as
    // "unreadable response" instead of as what actually went wrong.
    return _json({ ok: false, error: String(err) });
  }
}

function doGet() {
  return _json({ ok: true, service: 'EDLD surface survey', columns: COLUMNS.length });
}

// ── Writing ──────────────────────────────────────────────────────────────────

function _read(query) {
  var sheet = _sheet();
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return { ok: true, deposits: [] };

  var sysCol = COLUMNS.indexOf('system_address');
  var bodyCol = COLUMNS.indexOf('body_id');
  var testCol = COLUMNS.indexOf('is_test');

  var wantSys = String(query.system_address || '');
  var wantBody = String(query.body_id || '');
  if (!wantSys || !wantBody) return { ok: false, error: 'system_address and body_id required' };

  // One read of the whole range, then filter here. A getRange per row is the
  // difference between this answering instantly and timing out once the sheet
  // has a few thousand rows in it.
  var values = sheet.getRange(2, 1, lastRow - 1, COLUMNS.length).getValues();
  var out = [];
  for (var i = 0; i < values.length; i++) {
    var row = values[i];
    if (String(row[sysCol]) !== wantSys) continue;
    if (String(row[bodyCol]) !== wantBody) continue;
    if (testCol >= 0 && String(row[testCol]) === '1') continue;
    var dep = {};
    for (var c = 0; c < COLUMNS.length; c++) dep[COLUMNS[c]] = row[c];
    out.push(dep);
  }
  return { ok: true, deposits: out };
}


function _write(deposits) {
  // Thirty seconds is long enough for a batch and short enough that a stuck
  // lock surfaces as an error rather than a hang.
  var lock = LockService.getDocumentLock();
  if (!lock.tryLock(30000)) {
    return { ok: false, error: 'sheet busy, try again' };
  }
  try {
    var sheet = _sheet();
    var lastRow = sheet.getLastRow();
    var added = 0, updated = 0, unchanged = 0;

    // Row index by deposit_id, read once. Column A only — pulling the whole
    // sheet to find one column is the difference between this finishing and
    // this timing out once the sheet has a few thousand rows in it.
    var index = {};
    if (lastRow > 1) {
      var ids = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
      for (var i = 0; i < ids.length; i++) {
        var id = String(ids[i][0] || '').trim();
        if (id) index[id] = i + 2;
      }
    }

    var appends = [];
    for (var d = 0; d < deposits.length; d++) {
      var dep = deposits[d];
      var depId = String(dep.deposit_id || '').trim();
      if (!depId) continue;

      var row = index[depId];
      if (!row) {
        appends.push(_toRow(dep));
        // Guard against the same id appearing twice inside one batch.
        index[depId] = -1;
        added++;
        continue;
      }
      if (row < 0) continue;  // already queued for append in this batch

      if (_update(sheet, row, dep)) updated++; else unchanged++;
    }

    if (appends.length) {
      sheet.getRange(sheet.getLastRow() + 1, 1, appends.length, COLUMNS.length)
           .setValues(appends);
    }
    return { ok: true, added: added, updated: updated, unchanged: unchanged };
  } finally {
    lock.releaseLock();
  }
}

function _update(sheet, row, dep) {
  var current = sheet.getRange(row, 1, 1, COLUMNS.length).getValues()[0];
  var changed = false;

  for (var m = 0; m < MUTABLE.length; m++) {
    var field = MUTABLE[m];
    var col = COLUMNS.indexOf(field);
    if (col < 0) continue;
    if (!(field in dep)) continue;

    var incoming = dep[field];
    if (incoming === null || incoming === undefined || incoming === '') continue;

    // A blank stored value is always filled in. A populated one is only
    // replaced when the report is newer than what is on the row, so a
    // commander replaying an old session cannot walk back a fresher reading.
    var existing = current[col];
    if (String(existing) === String(incoming)) continue;
    if (existing !== '' && existing !== null && !_isNewer(dep, current)) continue;

    sheet.getRange(row, col + 1).setValue(incoming);
    current[col] = incoming;
    changed = true;
  }
  return changed;
}

function _isNewer(dep, currentRow) {
  var col = COLUMNS.indexOf('last_confirmed');
  if (col < 0) return true;
  var theirs = String(dep.last_confirmed || '');
  var ours = String(currentRow[col] || '');
  if (!ours) return true;
  return theirs >= ours;
}

function _toRow(dep) {
  var row = [];
  for (var c = 0; c < COLUMNS.length; c++) {
    var v = dep[COLUMNS[c]];
    row.push(v === null || v === undefined ? '' : v);
  }
  return row;
}

function _sheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(SHEET_NAME);

  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, COLUMNS.length).setValues([COLUMNS]);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, COLUMNS.length).setFontWeight('bold');
    // Latitude and longitude need the decimal places. Sheets rounds them for
    // display by default, which makes a coordinate look wrong when copied out
    // even though the stored value is fine.
    var latCol = COLUMNS.indexOf('latitude') + 1;
    sheet.getRange(2, latCol, sheet.getMaxRows() - 1, 2).setNumberFormat('0.000000');
  }
  return sheet;
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
                       .setMimeType(ContentService.MimeType.JSON);
}

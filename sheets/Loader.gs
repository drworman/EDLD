/**
 * EDLD sheet loader — the one file a sheet owner pastes.
 *
 * Paste this as the only file in the sheet's Apps Script project, save,
 * reload the sheet, and run ED Dashboard > Upgrade. That fetches EDLD's sheet
 * code from the latest release, checks it, stores it in this project's
 * properties and brings the sheet's layout up to date. Every later release is
 * the same menu item. Full instructions: sheets/README.md in the EDLD repo.
 *
 * Why a loader
 * ------------
 * An Apps Script project can only rewrite its own files through the Apps
 * Script API, and that API is disabled in the hidden Cloud project every
 * sheet script gets — enabling it means a trip to the Cloud console for every
 * sheet owner. So this file never changes. It keeps the entry points Google
 * calls (doPost, onOpen, the menu) and runs the real code, which lives in
 * script properties and is replaced by Upgrade. The web app deployment points
 * at this file, so an upgrade needs no redeploy and the URL and token
 * squadron members hold never change.
 *
 * What it trusts
 * --------------
 * Code comes only from the release manifest's URL, only from
 * raw.githubusercontent.com, and only if its SHA-256 matches the manifest. The
 * hash catches a truncated or corrupted download; it does not make the code
 * more trustworthy than the repository it came from, which is the same trust
 * as pasting it by hand. Nothing is installed without the owner confirming
 * the version, and the stored code is re-checked against its hash every time
 * it is loaded.
 *
 * Change only when unavoidable: every change is another paste for every
 * owner. A release that needs a newer loader says so, via min_loader.
 */

var LOADER_VERSION = 1;

/** Where the latest release is described. Override with the property below. */
var EDLD_RELEASE_URL =
    'https://raw.githubusercontent.com/drworman/EDLD/main/sheets/release.json';

var LP_ = {
  CODE: 'EDLD_CODE_',            // EDLD_CODE_0, EDLD_CODE_1, …
  PARTS: 'EDLD_CODE_PARTS',
  SHA: 'EDLD_CODE_SHA256',
  VERSION: 'EDLD_CODE_VERSION',
  TOKEN: 'EDLD_TOKEN',           // read by Code.gs
  RELEASE_URL: 'EDLD_RELEASE_URL'
};

/** Property values are capped at 9 kB; characters, not bytes, are counted here. */
var LOADER_CHUNK_ = 4000;

// ── the stored code ───────────────────────────────────────────────────────────

var edldModule_ = null;

function sha256Hex_(text) {
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text,
                                      Utilities.Charset.UTF_8);
  return bytes.map(function (b) {
    return ('0' + (b & 0xff).toString(16)).slice(-2);
  }).join('');
}

function compile_(src) {
  var mod = new Function('LOADER', src)({ version: LOADER_VERSION });
  if (!mod || typeof mod.doPost !== 'function' ||
      typeof mod.upgradeSheet !== 'function') {
    throw new Error('the code does not look like an EDLD sheet bundle');
  }
  return mod;
}

/** The installed code, loaded once per execution. Null if none is installed. */
function edld_() {
  if (edldModule_) return edldModule_;
  var props = PropertiesService.getScriptProperties().getProperties();
  var parts = parseInt(props[LP_.PARTS] || '0', 10);
  if (!parts) return null;
  var src = '';
  for (var i = 0; i < parts; i++) src += props[LP_.CODE + i] || '';
  if (sha256Hex_(src) !== props[LP_.SHA]) {
    throw new Error('the stored EDLD code is incomplete or has been altered — ' +
                    'run ED Dashboard > Upgrade to reinstall it');
  }
  edldModule_ = compile_(src);
  return edldModule_;
}

/** As edld_(), but a failure is logged and treated as nothing installed. */
function edldQuiet_() {
  try { return edld_(); } catch (err) { console.error(err); return null; }
}

function storeCode_(src, version, sha) {
  var sp = PropertiesService.getScriptProperties();
  var old = parseInt(sp.getProperty(LP_.PARTS) || '0', 10);
  var props = {};
  var parts = Math.max(1, Math.ceil(src.length / LOADER_CHUNK_));
  for (var i = 0; i < parts; i++) {
    props[LP_.CODE + i] = src.slice(i * LOADER_CHUNK_, (i + 1) * LOADER_CHUNK_);
  }
  props[LP_.PARTS] = String(parts);
  props[LP_.SHA] = sha;
  props[LP_.VERSION] = version;
  sp.setProperties(props, false);                 // one write, all or nothing
  for (var j = parts; j < old; j++) sp.deleteProperty(LP_.CODE + j);
  edldModule_ = null;
}

// ── entry points Google calls ─────────────────────────────────────────────────

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
                       .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  var m;
  try { m = edld_(); } catch (err) { return json_({ ok: false, error: String(err.message || err) }); }
  if (!m) {
    return json_({ ok: false, error: 'EDLD is not installed in this sheet yet — ' +
                   'open it and run ED Dashboard > Upgrade' });
  }
  return m.doPost(e);
}

function doGet(e) {
  var m = edldQuiet_();
  if (!m) return json_({ ok: false, error: 'EDLD is not installed in this sheet yet' });
  return m.doGet(e);
}

function onOpen(e) {
  var m = edldQuiet_();
  var menu = SpreadsheetApp.getUi().createMenu('ED Dashboard');
  var items = (m && m.MENU) || [];
  for (var i = 0; i < items.length && i < 8; i++) {
    menu.addItem(items[i].label, 'edldMenu' + i);
  }
  if (items.length) menu.addSeparator();
  menu.addItem(m ? 'Upgrade…' : 'Install / Upgrade…', 'edldUpgrade')
      .addItem('Set sheet token…', 'edldSetToken')
      .addItem('About', 'edldAbout')
      .addToUi();
  if (m && m.sheetVersion() < m.SHEET_VERSION) {
    SpreadsheetApp.getActive().toast(
      'This sheet has upgrade steps waiting. Run ED Dashboard > Upgrade.',
      'ED Dashboard', 10);
  }
}

function onEdit(e) {
  var m = edldQuiet_();
  if (m && m.onEdit) m.onEdit(e);
}

function onSelectionChange(e) {
  var m = edldQuiet_();
  if (m && m.onSelectionChange) m.onSelectionChange(e);
}

// Fixed names the menu can point at; which item each runs is the bundle's.
function edldMenu_(i) {
  var m = edld_();
  if (m && m.MENU && m.MENU[i]) m.MENU[i].run();
}
function edldMenu0() { edldMenu_(0); }
function edldMenu1() { edldMenu_(1); }
function edldMenu2() { edldMenu_(2); }
function edldMenu3() { edldMenu_(3); }
function edldMenu4() { edldMenu_(4); }
function edldMenu5() { edldMenu_(5); }
function edldMenu6() { edldMenu_(6); }
function edldMenu7() { edldMenu_(7); }

// ── Upgrade ───────────────────────────────────────────────────────────────────

function fetchText_(url) {
  if (!/^https:\/\/raw\.githubusercontent\.com\//.test(url)) {
    throw new Error('refusing to fetch from ' + url +
                    ' — releases come only from raw.githubusercontent.com');
  }
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
  if (res.getResponseCode() !== 200) {
    throw new Error('could not fetch ' + url + ' (HTTP ' + res.getResponseCode() + ')');
  }
  return res.getContentText('UTF-8');
}

function releaseUrl_() {
  return PropertiesService.getScriptProperties().getProperty(LP_.RELEASE_URL) ||
         EDLD_RELEASE_URL;
}

/** Fetch and check the release manifest. Throws with a readable message. */
function fetchRelease_() {
  var rel = JSON.parse(fetchText_(releaseUrl_()));
  if (!rel.version || !rel.bundle || !rel.bundle.url || !rel.bundle.sha256) {
    throw new Error('the release manifest is missing version or bundle details');
  }
  return rel;
}

function edldUpgrade() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActive();
  var sp = PropertiesService.getScriptProperties();
  var installed = sp.getProperty(LP_.VERSION) || '';
  var current = edldQuiet_();
  var sheetHave = current ? current.sheetVersion() : 0;

  var rel;
  try { rel = fetchRelease_(); } catch (err) {
    ui.alert('Upgrade', 'Could not read the latest release.\n\n' + err.message, ui.ButtonSet.OK);
    return;
  }
  if (Number(rel.min_loader || 1) > LOADER_VERSION) {
    ui.alert('Upgrade',
      'EDLD ' + rel.version + ' needs a newer loader than the one in this sheet.\n\n' +
      'Replace this project\'s Loader.gs with the one from that release ' +
      '(sheets/Loader.gs), save, reload the sheet and run Upgrade again. ' +
      'Nothing has been changed.', ui.ButtonSet.OK);
    return;
  }
  var sheetTo = Number(rel.sheet_version || 0);
  if (installed === rel.version && current && sheetHave >= sheetTo) {
    ui.alert('Upgrade', 'This sheet is up to date — EDLD ' + installed +
             ', sheet layout v' + sheetHave + '.', ui.ButtonSet.OK);
    return;
  }

  var ask = (installed ? 'Upgrade this sheet from EDLD ' + installed + ' to ' + rel.version + '?'
                       : 'Install EDLD ' + rel.version + ' in this sheet?') +
            '\n\nThe sheet code is replaced' +
            (sheetTo > sheetHave ? ', and the layout goes from v' + sheetHave + ' to v' +
             sheetTo + '. Deposits is copied to a hidden backup tab first' : '') +
            '. Your deposits, settings, URL and token are kept.';
  if (ui.alert('Upgrade', ask, ui.ButtonSet.YES_NO) !== ui.Button.YES) return;

  var src, mod;
  try {
    src = fetchText_(rel.bundle.url);
    var sha = sha256Hex_(src);
    if (sha !== String(rel.bundle.sha256).toLowerCase()) {
      throw new Error('the downloaded code does not match the release manifest ' +
                      '(SHA-256 ' + sha.slice(0, 12) + '…, expected ' +
                      String(rel.bundle.sha256).slice(0, 12) + '…)');
    }
    mod = compile_(src);
  } catch (err) {
    ui.alert('Upgrade', 'Nothing was changed.\n\n' + err.message, ui.ButtonSet.OK);
    return;
  }

  if (!sp.getProperty(LP_.TOKEN) && !askToken_(ui, true)) {
    ui.alert('Upgrade', 'Nothing was changed. A token is needed before EDLD ' +
             'can accept deposits.', ui.ButtonSet.OK);
    return;
  }

  // The same lock doPost holds, so a commander's write waits for the upgrade
  // instead of landing between the new code and the layout it expects.
  var lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  var done;
  try {
    storeCode_(src, rel.version, rel.bundle.sha256.toLowerCase());
    done = edld_().upgradeSheet();
  } catch (err) {
    ui.alert('Upgrade', 'The upgrade stopped part way.\n\n' + err.message +
             '\n\nRun Upgrade again: finished steps are recorded and are not ' +
             'repeated. Deposits are untouched.', ui.ButtonSet.OK);
    return;
  } finally {
    lock.releaseLock();
  }

  var lines = ['EDLD ' + rel.version + ' is installed.'];
  if (done.steps.length) {
    lines.push('', 'Sheet layout v' + done.from + ' → v' + done.to + ':');
    done.steps.forEach(function (s) { lines.push('  • ' + s); });
  }
  if (done.backup) lines.push('', 'Backup of Deposits: hidden tab "' + done.backup + '".');
  if (!installed) {
    lines.push('', 'One last manual step, only this once: Deploy > Manage ' +
               'deployments > edit (pencil) > Version: New version > Deploy. ' +
               'The web app keeps its URL, and from now on upgrades need no redeploy.');
  }
  ui.alert('Upgrade', lines.join('\n'), ui.ButtonSet.OK);
  onOpen();
}

// ── token ─────────────────────────────────────────────────────────────────────

function edldSetToken() { askToken_(SpreadsheetApp.getUi(), false); }

/**
 * Ask for the token squadron members use. Returns whether one was stored.
 * First-time installs are offered the old one from Code.gs — it cannot be
 * read out of a file that has already been replaced by this one.
 */
function askToken_(ui, firstTime) {
  var res = ui.prompt('Sheet token',
    (firstTime
      ? 'If this sheet already had EDLD set up, paste the token from the old ' +
        'Code.gs (the text between the quotes in TOKEN = \'…\') so everybody\'s ' +
        'EDLD keeps working.\n\n'
      : 'Paste a new token. Everybody\'s EDLD must then be given it.\n\n') +
    'Leave it blank to generate a new one.', ui.ButtonSet.OK_CANCEL);
  if (res.getSelectedButton() !== ui.Button.OK) return false;
  var token = String(res.getResponseText() || '').trim();
  if (!token) {
    token = (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '');
    ui.alert('Sheet token', 'New token — give it to everybody who publishes to ' +
             'this sheet, in EDLD\'s Options:\n\n' + token, ui.ButtonSet.OK);
  } else if (token.length < 16 || /\s/.test(token)) {
    ui.alert('Sheet token', 'A token needs at least 16 characters and no spaces. ' +
             'Nothing was changed.', ui.ButtonSet.OK);
    return false;
  }
  PropertiesService.getScriptProperties().setProperty(LP_.TOKEN, token);
  return true;
}

// ── About ─────────────────────────────────────────────────────────────────────

function edldAbout() {
  var sp = PropertiesService.getScriptProperties();
  var m = edldQuiet_();
  SpreadsheetApp.getUi().alert('ED Dashboard',
    'EDLD sheet code: ' + (sp.getProperty(LP_.VERSION) || 'not installed') + '\n' +
    'Sheet layout: v' + (m ? m.sheetVersion() : 0) +
    (m ? ' (this code expects v' + m.SHEET_VERSION + ')' : '') + '\n' +
    'Loader: v' + LOADER_VERSION + '\n' +
    'Token: ' + (sp.getProperty(LP_.TOKEN) ? 'set' : 'not set') + '\n' +
    'Releases from: ' + releaseUrl_(),
    SpreadsheetApp.getUi().ButtonSet.OK);
}

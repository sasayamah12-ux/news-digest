/**
 * 毎朝のニュースダイジェスト用クリック追跡サーバー。
 * - 通常のGET: クリックをスプレッドシートに記録し、実際の記事URLへリダイレクト
 * - ?mode=summary: 直近のクリック傾向をJSONで返す(生成スクリプトのパーソナライズ用、要シークレットキー)
 */

const SHEET_NAME = 'Clicks';

function doGet(e) {
  const params = e.parameter || {};
  if (params.mode === 'summary') {
    return handleSummary(params);
  }
  return handleClick(params);
}

function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(['timestamp', 'kind', 'category', 'title', 'dest']);
  }
  return sheet;
}

function handleClick(params) {
  const dest = params.dest || '';
  const kind = params.kind || '';
  const category = params.cat || '';
  const title = params.t || '';

  if (!/^https:\/\//.test(dest)) {
    return HtmlService.createHtmlOutput('Invalid destination');
  }

  try {
    getSheet().appendRow([new Date(), kind, category, title, dest]);
  } catch (err) {
    // シート書き込みに失敗してもリダイレクトは継続する
  }

  const html =
    '<!DOCTYPE html><html><head><meta charset="utf-8">' +
    '<meta http-equiv="refresh" content="0;url=' + dest.replace(/"/g, '&quot;') + '">' +
    '<title>Redirecting…</title></head><body>' +
    '<script>location.replace(' + JSON.stringify(dest) + ');</script>' +
    '<a href="' + dest.replace(/"/g, '&quot;') + '">記事へ移動</a>' +
    '</body></html>';
  return HtmlService.createHtmlOutput(html);
}

function handleSummary(params) {
  const secret = PropertiesService.getScriptProperties().getProperty('SUMMARY_SECRET');
  if (!secret || params.key !== secret) {
    return jsonOutput({ error: 'unauthorized' });
  }

  const kindFilter = params.kind || '';
  const days = Number(params.days) > 0 ? Number(params.days) : 30;
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000);

  const values = getSheet().getDataRange().getValues();
  const counts = {};

  for (let i = 1; i < values.length; i++) {
    const row = values[i];
    const ts = row[0];
    const kind = row[1];
    const category = row[2];
    if (!(ts instanceof Date) || ts < since) continue;
    if (!category) continue;
    if (kindFilter && kind !== kindFilter) continue;
    counts[category] = (counts[category] || 0) + 1;
  }

  return jsonOutput(counts);
}

function jsonOutput(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}

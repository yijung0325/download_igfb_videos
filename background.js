'use strict';
(function(){
  if (chrome && chrome.runtime && chrome.runtime.onInstalled) {
    chrome.runtime.onInstalled.addListener(function() {
      chrome.storage.local.get({ savedUrls: [] }, function(data){
        if (!data || !data.savedUrls) chrome.storage.local.set({ savedUrls: [] });
      });
    });
  }
  if (chrome && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {
      try {
        if (msg && msg.type === "saveUrl" && typeof msg.url === "string") {
          chrome.storage.local.get({ savedUrls: [] }, function(data) {
            var list = data.savedUrls || [];
            var now = Date.now();
            var cmt = (typeof msg.comment === 'string') ? msg.comment : '';
            list.push({ url: msg.url, ts: now, comment: cmt });
            chrome.storage.local.set({ savedUrls: list }, function(){ sendResponse({ ok:true }); });
          });
          return true;
        } else if (msg && msg.type === "clearAll") {
          chrome.storage.local.set({ savedUrls: [] }, function(){ sendResponse({ ok:true }); });
          return true;
        } else if (msg && msg.type === "exportNow") {
          exportCsv(function(){ sendResponse({ ok:true }); });
          return true;
        } else if (msg && msg.type === "updateComment" && typeof msg.ts === "number") {
          chrome.storage.local.get({ savedUrls: [] }, function(data){
            var list = data.savedUrls || [];
            for (var i=0;i<list.length;i++) {
              if (list[i].ts === msg.ts) { list[i].comment = (typeof msg.comment === "string" ? msg.comment : ""); break; }
            }
            chrome.storage.local.set({ savedUrls: list }, function(){ sendResponse({ ok:true }); });
          });
          return true;
        } else if (msg && msg.type === "deleteItem" && typeof msg.ts === "number") {
          chrome.storage.local.get({ savedUrls: [] }, function(data){
            var list = data.savedUrls || [];
            var nlist = [];
            for (var i=0;i<list.length;i++) { if (list[i].ts !== msg.ts) nlist.push(list[i]); }
            chrome.storage.local.set({ savedUrls: nlist }, function(){ sendResponse({ ok:true }); });
          });
          return true;
        }
        sendResponse({ ok:true });
      } catch (e) {
        console.error(e);
        sendResponse({ ok:false, error:String(e) });
      }
      return true;
    });
  }
  function csvEscape(v) {
    v = String(v);
    if (v.indexOf('"') !== -1) v = v.split('"').join('""');
    var need = v.indexOf(',') !== -1 || v.indexOf('"') !== -1 || v.indexOf('\n') !== -1;
    return need ? ('"' + v + '"') : v;
  }
  function exportCsv(doneCb) {
    chrome.storage.local.get({ savedUrls: [] }, function(data) {
      var items = data.savedUrls || [];
      var lines = [];
      for (var i=0; i<items.length; i++) {
        var d = new Date(items[i].ts);
        var t = d.toISOString();
        var c = items[i].comment || '';
        c = String(c).split('\r').join(' ').split('\n').join(' ');
        var row = t + ',' + csvEscape(c) + ',' + csvEscape(items[i].url);
        lines.push(row);
      }
      var content = lines.join('\n');
      var dataUrl = 'data:text/csv;charset=utf-8,' + encodeURIComponent(content);
      try {
        chrome.downloads.download({
          url: dataUrl,
          filename: 'ig_fb_saved_urls.csv',
          saveAs: true,
          conflictAction: 'uniquify'
        }, function(id) {
          if (chrome.runtime && chrome.runtime.lastError) {
            console.error('downloads.download error:', chrome.runtime.lastError.message);
          }
          if (typeof doneCb === 'function') doneCb();
        });
      } catch (e) {
        console.error('Download failed', e);
        if (typeof doneCb === 'function') doneCb();
      }
    });
  }
})();
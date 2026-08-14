(function(){
  var IG_HOSTS = { 'www.instagram.com':1, 'instagram.com':1 };
  var FB_HOSTS = { 'www.facebook.com':1, 'facebook.com':1, 'm.facebook.com':1 };
  var X_HOSTS = {
    'x.com':1, 'www.x.com':1, 'm.x.com':1, 'mobile.x.com':1,
    'twitter.com':1, 'www.twitter.com':1, 'm.twitter.com':1, 'mobile.twitter.com':1
  };

  function getCanonicalContentInfo(url) {
    try {
      var h = url.hostname;
      var p = url.pathname;
      var m;
      if (IG_HOSTS[h]) {
        m = p.match(/^\/(p|reel|reels)\/([^\/?#]+)/);
        if (m) {
          return {
            key: 'ig:' + m[1] + ':' + m[2],
            pathname: '/' + m[1] + '/' + m[2] + '/'
          };
        }
        m = p.match(/^\/(stories|story)\/([^\/?#]+)(\/[^\/?#]+)?/);
        if (m) {
          return {
            key: 'ig:' + m[1] + ':' + m[2] + ':' + (m[3] || ''),
            pathname: '/' + m[1] + '/' + m[2] + (m[3] || '') + '/'
          };
        }
      }
      if (X_HOSTS[h]) {
        m = p.match(/^\/((?:i\/web)|[^\/?#]+)\/status\/(\d+)(?:\/(video|photo)\/(\d+))?/);
        if (m) {
          return {
            key: 'x:status:' + m[2],
            hostname: 'x.com',
            pathname: '/' + m[1] + '/status/' + m[2] + (m[3] ? ('/' + m[3] + '/' + m[4]) : ''),
            mediaPath: m[3] ? ('/' + m[3] + '/' + m[4]) : ''
          };
        }
      }
    } catch(e) {}
    return null;
  }

  function stripUrl(u) {
    try {
      var url = new URL(u);
      var currentUrl = new URL(location.href);
      var info = getCanonicalContentInfo(url);
      var currentInfo = getCanonicalContentInfo(currentUrl);
      url.hash = '';
      if (info) {
        if (info.hostname) url.hostname = info.hostname;
        if (X_HOSTS[new URL(u).hostname] && !info.mediaPath && currentInfo &&
            info.key === currentInfo.key && currentInfo.mediaPath) {
          url.pathname = info.pathname + currentInfo.mediaPath;
        } else {
          url.pathname = info.pathname;
        }
      }
      // keep only selected query params
      var keep = { 'img_index': 1 };
      var params = new URLSearchParams(url.search);
      var kept = new URLSearchParams();
      params.forEach(function(value, key){
        if (keep[key]) kept.set(key, value);
      });
      if (!kept.has('img_index') && info && currentInfo && info.key === currentInfo.key) {
        var currentParams = new URLSearchParams(currentUrl.search);
        var currentImgIndex = currentParams.get('img_index');
        if (currentImgIndex) kept.set('img_index', currentImgIndex);
      }
      url.search = kept.toString() ? ('?' + kept.toString()) : '';
      return url.toString();
    } catch(e){ return null; }
  }
  function isOurHost(u) {
    try { var h = new URL(u).hostname; return IG_HOSTS[h] || FB_HOSTS[h] || X_HOSTS[h]; } catch(e){ return false; }
  }
  function urlLooksLikeContent(u) {
    try {
      var parsed = new URL(u);
      var p = parsed.pathname;
      if (X_HOSTS[parsed.hostname]) return /^\/(?:i\/web|[^\/?#]+)\/status\/\d+(?:\/(?:video|photo)\/\d+)?/.test(p);
      return p.indexOf('/reel/')>=0 || p.indexOf('/reels/')>=0 || p.indexOf('/p/')>=0 ||
             p.indexOf('/stories/')>=0 || p.indexOf('/story/')>=0 || p.indexOf('/watch/')>=0 ||
             p.indexOf('/video')>=0;
    } catch(e){ return false; }
  }
  function closestAnchorHref(el) {
    var node = el;
    while (node) {
      if (node.tagName === 'A' && node.href) return node.href;
      node = node.parentElement;
    }
    return null;
  }
  function findUsefulUrlFromElement(el) {
    if (!el) return stripUrl(location.href);
    var a1 = closestAnchorHref(el);
    if (a1 && isOurHost(a1) && urlLooksLikeContent(a1)) return stripUrl(a1);
    if (X_HOSTS[location.hostname]) {
      var article = el.closest ? el.closest('article') : null;
      var articleLinks = article ? article.querySelectorAll('a[href]') : [];
      var firstPostUrl = null;
      var firstPostInfo = null;
      for (var x=0;x<articleLinks.length;x++) {
        var articleHref = articleLinks[x].href;
        if (!isOurHost(articleHref) || !urlLooksLikeContent(articleHref)) continue;
        var articleInfo = getCanonicalContentInfo(new URL(articleHref));
        if (!firstPostUrl) {
          firstPostUrl = articleHref;
          firstPostInfo = articleInfo;
        } else if (articleInfo && firstPostInfo && articleInfo.key === firstPostInfo.key && articleInfo.mediaPath) {
          return stripUrl(articleHref);
        }
      }
      if (firstPostUrl) return stripUrl(firstPostUrl);
    }
    var node = el;
    while (node) {
      var links = node.querySelectorAll ? node.querySelectorAll('a[href]') : [];
      for (var i=0;i<links.length;i++){
        var href = links[i].href;
        if (isOurHost(href) && urlLooksLikeContent(href)) return stripUrl(href);
      }
      node = node.parentElement;
    }
    return stripUrl(location.href);
  }
  function saveUrl(url) {
    var host = null;
    try { host = url ? new URL(url).hostname : null; } catch(e) {}
    if (url && isOurHost(url) && (!X_HOSTS[host] || urlLooksLikeContent(url))) {
      var note = prompt('為這個連結加個註解（可留空）:', '');
      if (note === null) { return; } // cancel => do NOT save
      chrome.runtime.sendMessage({ type:'saveUrl', url:url, comment:note }, function(){});
      flashToast('已儲存連結');
    } else {
      flashToast('未偵測到可儲存的 IG/FB/X 連結');
    }
  }
  var toastTimer=null;
  function flashToast(text){
    var t=document.getElementById('__igfb_toast__');
    if(!t){ t=document.createElement('div'); t.id='__igfb_toast__';
      t.style.cssText='position:fixed;left:50%;transform:translateX(-50%);bottom:24px;background:rgba(0,0,0,.75);color:#fff;padding:8px 12px;border-radius:10px;font:13px/1.2 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;z-index:2147483647;pointer-events:none;opacity:0;transition:opacity .2s';
      document.documentElement.appendChild(t);
    }
    t.textContent=text; t.style.opacity='1';
    clearTimeout(toastTimer); toastTimer=setTimeout(function(){t.style.opacity='0';},1200);
  }
  function createFloatingButton(){
    if(document.getElementById('__igfb_btn__'))return;
    var btn=document.createElement('button'); btn.id='__igfb_btn__'; btn.textContent='Save URL';
    btn.title='儲存目前內容的連結（可拖曳移動）';
    btn.style.cssText='position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#0a84ff;color:#fff;border:none;border-radius:999px;padding:10px 14px;font:14px/1 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.2);cursor:pointer;user-select:none';
    document.documentElement.appendChild(btn);
    btn.addEventListener('click', function(e){ e.preventDefault(); var url=stripUrl(location.href); saveUrl(url); });
    var dragging=false,sx=0,sy=0,sr=0,sb=0;
    btn.addEventListener('mousedown', function(e){ dragging=true; sx=e.clientX; sy=e.clientY; sr=parseInt(btn.style.right,10)||16; sb=parseInt(btn.style.bottom,10)||16; document.body.style.userSelect='none'; });
    window.addEventListener('mousemove', function(e){ if(!dragging)return; var dx=e.clientX-sx, dy=e.clientY-sy; btn.style.right=Math.max(0,sr-dx)+'px'; btn.style.bottom=Math.max(0,sb-dy)+'px'; });
    window.addEventListener('mouseup', function(){ dragging=false; document.body.style.userSelect=''; });
  }
  function ensureChipFor(videoEl){
    if(!videoEl || videoEl.dataset.igfbChip) return;
    var chip=document.createElement('button'); chip.textContent='Save'; chip.className='__igfb_chip__';
    chip.style.cssText='position:absolute;right:8px;top:8px;z-index:2147483647;background:rgba(10,132,255,.95);color:#fff;border:none;border-radius:999px;padding:6px 10px;font:12px/1 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.2);cursor:pointer;opacity:1';
    var parent=videoEl.parentElement; if(!parent) return;
    if (X_HOSTS[location.hostname]) {
      if (window.getComputedStyle(parent).position === 'static') parent.style.position='relative';
      parent.appendChild(chip);
    } else {
      var wrap=document.createElement('div'); wrap.style.position='relative'; wrap.style.display='inline-block';
      parent.insertBefore(wrap, videoEl); wrap.appendChild(videoEl); wrap.appendChild(chip);
    }
    videoEl.dataset.igfbChip='1';
    chip.addEventListener('click', function(e){ e.stopPropagation(); e.preventDefault(); var u=findUsefulUrlFromElement(videoEl); saveUrl(u); });
  }
  var mo=new MutationObserver(function(){ var vids=document.querySelectorAll('video:not([data-igfb-chip])'); for(var i=0;i<vids.length;i++){ try{ensureChipFor(vids[i]);}catch(e){} } });
  mo.observe(document.documentElement,{childList:true,subtree:true});
  createFloatingButton();
  var init=document.querySelectorAll('video'); for(var j=0;j<init.length;j++){ try{ensureChipFor(init[j]);}catch(e){} }
  // No 's' keyboard shortcut.
})();

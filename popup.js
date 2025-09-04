(function(){
  function render(){
    chrome.storage.local.get({ savedUrls: [] }, function(data){
      var list = data.savedUrls || [];
      var ul = document.getElementById('list'); ul.innerHTML='';
      var last = list.slice(-50).reverse();
      for (var i=0;i<last.length;i++){
        var it = last[i];
        var li = document.createElement('li');
        var d = new Date(it.ts);
        var cm = it.comment || '';
        li.innerHTML = '<span class="time">[' + d.toLocaleString() + ']</span> ' +
                       (cm ? '<span class="note">（' + escapeHtml(cm) + '）</span> ' : '') +
                       '<a class="url" href="' + escapeAttr(it.url) + '" target="_blank" rel="noreferrer noopener">' + escapeHtml(it.url) + '</a>' +
                       ' <button class="btn-sm edit" data-ts="' + it.ts + '">Edit</button>' +
                       ' <button class="btn-sm del" data-ts="' + it.ts + '">Delete</button>';
        ul.appendChild(li);
      }
      document.getElementById('count').textContent = '共 ' + list.length + ' 筆';
    });
  }

  function escapeHtml(s){ return String(s).replace(/[&<>"']/g, function(c){return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]);}); }
  function escapeAttr(s){ return String(s).replace(/"/g,'&quot;'); }

  document.getElementById('export').addEventListener('click', function(){
    chrome.runtime.sendMessage({ type:'exportNow' }, function(){});
  });
  document.getElementById('clear').addEventListener('click', function(){
    if (confirm('確定要清空暫存的連結嗎？')) {
      chrome.runtime.sendMessage({ type:'clearAll' }, render);
    }
  });

  document.getElementById('list').addEventListener('click', function(e){
    var t = e.target;
    if (t.classList.contains('edit')){
      var ts = Number(t.getAttribute('data-ts'));
      var note = prompt('更新註解（留空可清除註解）：', '');
      if (note === null) return;
      chrome.runtime.sendMessage({ type:'updateComment', ts: ts, comment: note }, function(){ render(); });
    } else if (t.classList.contains('del')){
      var ts2 = Number(t.getAttribute('data-ts'));
      if (!confirm('確定要刪除這一筆嗎？')) return;
      chrome.runtime.sendMessage({ type:'deleteItem', ts: ts2 }, function(){ render(); });
    }
  });

  render();
})();
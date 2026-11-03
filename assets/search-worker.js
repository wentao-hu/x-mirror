/* 下载、解析与全文匹配均在 Worker 内，避免占用首页交互线程。 */
'use strict';

var documents = null;
self.onmessage = function (event) {
  var data = event.data;
  if (data.type === 'init') {
    try {
      importScripts(data.engineUrl);
      self.XMirrorSearch.fetchIndex(data.indexUrl, data.slugs).then(function (docs) {
        documents = docs;
        self.postMessage({ type: 'ready' });
      }).catch(function (error) {
        self.postMessage({ type: 'error', message: error.message });
      });
    } catch (error) {
      self.postMessage({ type: 'error', message: error.message });
    }
  } else if (data.type === 'search' && documents) {
    self.postMessage({
      type: 'result', request: data.request,
      results: self.XMirrorSearch.search(documents, data.request.query, data.request.scope)
    });
  }
};

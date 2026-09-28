// Phase 4.10 — CloudFront Function (runtime cloudfront-js-2.0), viewer request, on the
// default behaviour of shurly.griddo.io: the private S3 bucket with the static build.
// Tests: frontend/tests/cloudfront-static-paths.test.mjs. Setup: DEPLOYMENT.md § Frontend hosting.
//
// Astro writes every page as <path>/index.html, and a private bucket reached through the S3
// REST endpoint (Origin Access Control) doesn't resolve directory indexes. So:
// - a path ending in "/" gets "index.html": /dashboard/ → /dashboard/index.html;
// - a dot in the last segment means a file (/_astro/app.1a2b3c.js, /favicon.svg): left as is;
// - anything else is a page asked for without its slash: a 301 to it with the slash, query kept.
// The rule has one consequence: a page whose last segment has a dot (/manual/v1.2/) works when
// linked with its trailing slash, while /manual/v1.2 reads as a file (and gets the 404).

function handler(event) {
  var request = event.request;
  var uri = request.uri;

  if (uri.charAt(uri.length - 1) === '/') {
    request.uri = uri + 'index.html';
    return request;
  }
  var last = uri.substring(uri.lastIndexOf('/') + 1);
  if (last.indexOf('.') !== -1) {
    return request;
  }
  // One leading slash, never "//host" or "/\host": the browser would read either as
  // another site, and this redirect must stay on this one.
  var path = '/' + uri.replace(/\\/g, '/').replace(/^\/+/, '');
  var query = queryString(request.querystring);
  return {
    statusCode: 301,
    statusDescription: 'Moved Permanently',
    headers: { location: { value: path + '/' + (query ? '?' + query : '') } },
  };
}

// The query as the viewer sent it: the values arrive as they were in the URL.
function queryString(params) {
  var parts = [];
  for (var name in params) {
    var entries = params[name].multiValue || [params[name]];
    for (var i = 0; i < entries.length; i++) {
      parts.push(entries[i].value === '' ? name : name + '=' + entries[i].value);
    }
  }
  return parts.join('&');
}

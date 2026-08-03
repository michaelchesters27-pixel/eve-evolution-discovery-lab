const BACKEND = (process.env.DISCOVERY_RAILWAY_URL || process.env.RAILWAY_API_URL || '').replace(/\/$/, '');

export default async (request, context) => {
  if (!BACKEND) {
    return new Response(JSON.stringify({ detail: 'DISCOVERY_RAILWAY_URL is not configured in Netlify.' }), {
      status: 500,
      headers: { 'content-type': 'application/json' },
    });
  }
  const url = new URL(request.url);
  const path = context.params?.splat ? `/${context.params.splat}` : url.pathname.replace(/^\/api/, '');
  const target = `${BACKEND}/api${path}${url.search}`;
  const headers = new Headers(request.headers);
  headers.delete('host');
  const response = await fetch(target, {
    method: request.method,
    headers,
    body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer(),
  });
  const outputHeaders = new Headers(response.headers);
  outputHeaders.set('cache-control', 'no-store');
  return new Response(response.body, { status: response.status, headers: outputHeaders });
};

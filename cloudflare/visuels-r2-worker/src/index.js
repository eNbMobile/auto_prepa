// Sert les visuels produits du bucket R2 « visuels » : GET /<gencod>.png
export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Méthode non autorisée", { status: 405 });
    }
    const cle = decodeURIComponent(new URL(request.url).pathname.slice(1));
    if (!cle || cle.includes("/")) {
      return new Response("Introuvable", { status: 404 });
    }
    const objet = await env.VISUELS.get(cle);
    if (!objet) {
      return new Response("Introuvable", { status: 404 });
    }
    const entetes = new Headers();
    objet.writeHttpMetadata(entetes);
    if (!entetes.has("content-type")) entetes.set("content-type", "image/png");
    entetes.set("etag", objet.httpEtag);
    entetes.set("cache-control", "public, max-age=86400");
    return new Response(request.method === "HEAD" ? null : objet.body, { headers: entetes });
  },
};

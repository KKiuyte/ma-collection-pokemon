// Fonction de synchro pour "Ma Collection Pokémon"
// À coller dans l'éditeur d'un Worker Cloudflare.
// Elle range/redonne ta collection (un bloc JSON) sous ton code de synchro.
//
// Prérequis : un espace de stockage KV lié au Worker sous le nom  COLLECTIONS
// (Worker → Settings → Bindings → KV namespace → Variable name : COLLECTIONS)

export default {
  async fetch(request, env) {
    // En-têtes pour autoriser l'appli à appeler cette fonction depuis le navigateur
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    // Requête de "vérification" envoyée par le navigateur avant un POST
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: cors });
    }

    const url = new URL(request.url);
    const code = url.searchParams.get("code");

    // Le code de synchro sert d'identifiant + mot de passe : on exige au moins 8 caractères
    if (!code || code.length < 8) {
      return json({ error: "Code de synchro manquant ou trop court (min. 8 caractères)." }, 400, cors);
    }

    const key = "collection:" + code;

    // Charger la collection
    if (request.method === "GET") {
      const value = await env.COLLECTIONS.get(key);
      return json({ data: value ? JSON.parse(value) : null }, 200, cors);
    }

    // Enregistrer la collection
    if (request.method === "POST") {
      let body;
      try {
        body = await request.json();
      } catch {
        return json({ error: "JSON invalide." }, 400, cors);
      }
      await env.COLLECTIONS.put(key, JSON.stringify(body.data ?? {}));
      return json({ ok: true }, 200, cors);
    }

    return json({ error: "Méthode non supportée." }, 405, cors);
  },
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...cors },
  });
}

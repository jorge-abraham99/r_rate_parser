(function initializeRateDeskAuth() {
  "use strict";

  const LOGIN_PATH = "/ui/login.html";
  let clientPromise = null;

  function safeReturnTo(value, fallback = "/ui/") {
    if (typeof value !== "string" || !value.startsWith("/ui/") || value.startsWith("//")) {
      return fallback;
    }
    return value;
  }

  function requestedReturnTo() {
    const params = new URLSearchParams(window.location.search);
    return safeReturnTo(params.get("returnTo"));
  }

  function redirectToLogin() {
    if (window.location.pathname === LOGIN_PATH) return;
    const current = safeReturnTo(
      `${window.location.pathname}${window.location.search}${window.location.hash}`,
    );
    window.location.replace(`${LOGIN_PATH}?returnTo=${encodeURIComponent(current)}`);
  }

  async function createAuthClient() {
    const response = await window.fetch("/api/public-config", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("Login is not configured on this server.");
    const config = await response.json();
    if (!config.supabase_url || !config.supabase_publishable_key) {
      throw new Error("Login is not configured on this server.");
    }
    if (!window.supabase?.createClient) {
      throw new Error("The login library could not load.");
    }
    const client = window.supabase.createClient(
      config.supabase_url,
      config.supabase_publishable_key,
      {
        auth: {
          autoRefreshToken: true,
          persistSession: true,
          detectSessionInUrl: true,
        },
      },
    );
    client.auth.onAuthStateChange((event) => {
      if (event === "SIGNED_OUT") redirectToLogin();
    });
    return client;
  }

  function getClient() {
    if (!clientPromise) clientPromise = createAuthClient();
    return clientPromise;
  }

  async function getSession() {
    const client = await getClient();
    const { data, error } = await client.auth.getSession();
    if (error) throw error;
    return data.session;
  }

  function showSession(session) {
    document.querySelectorAll("[data-auth-email]").forEach((element) => {
      element.textContent = session?.user?.email || "Signed in";
    });
  }

  async function requireSession() {
    const session = await getSession();
    if (!session?.access_token) {
      redirectToLogin();
      return null;
    }
    showSession(session);
    return session;
  }

  async function responseDetail(response) {
    try {
      const payload = await response.clone().json();
      return payload.detail || "";
    } catch (_error) {
      return "";
    }
  }

  async function apiFetch(input, init = {}) {
    const session = await requireSession();
    if (!session) throw new Error("Your session has ended.");
    const headers = new Headers(init.headers || {});
    headers.set("Authorization", `Bearer ${session.access_token}`);
    const response = await window.fetch(input, { ...init, headers });

    if (response.status === 401) {
      const client = await getClient();
      await client.auth.signOut({ scope: "local" });
      redirectToLogin();
      throw new Error("Your session has ended. Sign in again.");
    }
    if (response.status === 403) {
      const detail = await responseDetail(response);
      throw new Error(detail || "You are signed in, but you do not have permission for this action.");
    }
    return response;
  }

  async function signIn(email, password) {
    const client = await getClient();
    const { data, error } = await client.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data.session;
  }

  async function signOut() {
    const client = await getClient();
    await client.auth.signOut({ scope: "local" });
    window.location.replace(LOGIN_PATH);
  }

  document.querySelectorAll("[data-auth-logout]").forEach((button) => {
    button.addEventListener("click", () => signOut());
  });

  window.RATE_DESK_AUTH = Object.freeze({
    apiFetch,
    getClient,
    getSession,
    requireSession,
    requestedReturnTo,
    safeReturnTo,
    signIn,
    signOut,
  });
})();

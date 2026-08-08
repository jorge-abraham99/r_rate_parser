(function initializeLogin() {
  "use strict";

  const form = document.getElementById("loginForm");
  const emailInput = document.getElementById("loginEmail");
  const passwordInput = document.getElementById("loginPassword");
  const submitButton = document.getElementById("loginSubmit");
  const alert = document.getElementById("loginAlert");

  function showError(message) {
    alert.textContent = message;
    alert.hidden = false;
  }

  function setBusy(busy) {
    submitButton.disabled = busy;
    submitButton.textContent = busy ? "Signing in…" : "Sign in";
  }

  async function clearLocalSession() {
    try {
      const client = await window.RATE_DESK_AUTH.getClient();
      await client.auth.signOut({ scope: "local" });
    } catch (_error) {
      // Keep the login page usable if session cleanup also fails.
    }
  }

  async function boot() {
    try {
      const session = await window.RATE_DESK_AUTH.getSession();
      if (session?.access_token) {
        await window.RATE_DESK_AUTH.apiFetch("/api/me");
        window.location.replace(window.RATE_DESK_AUTH.requestedReturnTo());
      }
    } catch (error) {
      await clearLocalSession();
      showError(error.message);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    alert.hidden = true;
    setBusy(true);
    try {
      const session = await window.RATE_DESK_AUTH.signIn(
        emailInput.value.trim(),
        passwordInput.value,
      );
      if (!session?.access_token) throw new Error("Supabase did not create a session.");
      await window.RATE_DESK_AUTH.apiFetch("/api/me");
      window.location.replace(window.RATE_DESK_AUTH.requestedReturnTo());
    } catch (_error) {
      await clearLocalSession();
      showError("The email or password is not correct, or this user has no access.");
      passwordInput.select();
    } finally {
      setBusy(false);
    }
  });

  boot();
})();

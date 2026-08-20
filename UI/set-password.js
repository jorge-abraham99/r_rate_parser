(function initializePasswordSetup() {
  "use strict";

  const form = document.getElementById("passwordForm");
  const passwordInput = document.getElementById("newPassword");
  const confirmInput = document.getElementById("confirmPassword");
  const submitButton = document.getElementById("passwordSubmit");
  const alert = document.getElementById("passwordAlert");
  const invalidPasswordLinkMessage = "This password link is invalid or has expired. Request a new password recovery link or ask your Reudan administrator for a new invitation.";

  function showMessage(message, success = false) {
    alert.textContent = message;
    alert.classList.toggle("success", success);
    alert.hidden = false;
  }

  function setBusy(busy) {
    submitButton.disabled = busy;
    submitButton.textContent = busy ? "Setting password…" : "Set password";
  }

  function hasPasswordSetupMarker() {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const query = new URLSearchParams(window.location.search);
    const type = hash.get("type") || query.get("type");
    return type === "invite" || type === "recovery";
  }

  function hasAuthLinkError() {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const query = new URLSearchParams(window.location.search);
    return Boolean(
      hash.get("error") ||
      hash.get("error_code") ||
      query.get("error") ||
      query.get("error_code")
    );
  }

  async function clearLocalSession() {
    try {
      const client = await window.RATE_DESK_AUTH.getClient();
      await client.auth.signOut({ scope: "local" });
    } catch (_error) {
      // The page can still show a safe error when local cleanup fails.
    }
  }

  async function boot() {
    if (hasAuthLinkError() || !hasPasswordSetupMarker()) {
      await clearLocalSession();
      showMessage(invalidPasswordLinkMessage);
      return;
    }

    try {
      const session = await window.RATE_DESK_AUTH.getSession();
      if (!session?.access_token) throw new Error("No invitation session");
      form.hidden = false;
    } catch (_error) {
      await clearLocalSession();
      showMessage(invalidPasswordLinkMessage);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    alert.hidden = true;

    const password = passwordInput.value;
    if (password.length < 8) {
      showMessage("Use a password with at least 8 characters.");
      passwordInput.focus();
      return;
    }
    if (password !== confirmInput.value) {
      showMessage("The passwords do not match.");
      confirmInput.select();
      return;
    }

    setBusy(true);
    try {
      const client = await window.RATE_DESK_AUTH.getClient();
      const { error } = await client.auth.updateUser({ password });
      if (error) throw error;

      try {
        await window.RATE_DESK_AUTH.apiFetch("/api/me");
      } catch (_membershipError) {
        await clearLocalSession();
        form.hidden = true;
        showMessage("Your password was set, but this account has no organization access. Contact your Reudan administrator.");
        return;
      }

      form.reset();
      form.hidden = true;
      showMessage("Your password is set. Opening the Rate Desk…", true);
      window.setTimeout(() => window.location.replace("/ui/"), 700);
    } catch (_error) {
      showMessage("The password could not be set. Ask for a new invitation and try again.");
      passwordInput.value = "";
      confirmInput.value = "";
      passwordInput.focus();
    } finally {
      setBusy(false);
    }
  });

  boot();
})();

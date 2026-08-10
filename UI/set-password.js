(function initializeSetPassword() {
  "use strict";

  const form = document.getElementById("setPasswordForm");
  const passwordInput = document.getElementById("newPassword");
  const confirmInput = document.getElementById("confirmPassword");
  const submitButton = document.getElementById("setPasswordSubmit");
  const alert = document.getElementById("setPasswordAlert");
  const invalidInviteMessage = "This invitation link is invalid or has expired. Ask your Reudan administrator for a new invitation.";

  function showError(message) {
    alert.textContent = message;
    alert.hidden = false;
  }

  function setBusy(busy) {
    submitButton.disabled = busy;
    submitButton.textContent = busy ? "Setting password…" : "Set password";
  }

  function disableForm() {
    form.hidden = false;
    passwordInput.disabled = true;
    confirmInput.disabled = true;
    submitButton.disabled = true;
  }

  async function verifyMembership() {
    const session = await window.RATE_DESK_AUTH.getSession();
    if (!session?.access_token) return false;
    const response = await window.fetch("/api/me", {
      headers: {
        Authorization: `Bearer ${session.access_token}`,
        Accept: "application/json",
      },
    });
    return response.ok;
  }

  async function boot() {
    try {
      const session = await window.RATE_DESK_AUTH.getSession();
      if (!session?.access_token) {
        showError(invalidInviteMessage);
        disableForm();
        return;
      }
      form.hidden = false;
    } catch (_error) {
      showError(invalidInviteMessage);
      disableForm();
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    alert.hidden = true;
    const password = passwordInput.value;
    if (password.length < 8) {
      showError("Choose a password with at least 8 characters.");
      passwordInput.focus();
      return;
    }
    if (password !== confirmInput.value) {
      showError("The passwords do not match.");
      confirmInput.focus();
      return;
    }

    setBusy(true);
    try {
      const client = await window.RATE_DESK_AUTH.getClient();
      const { error } = await client.auth.updateUser({ password });
      if (error) throw error;
      form.reset();
      if (!(await verifyMembership())) {
        showError("Your password was set, but this account does not have Rate Desk access. Contact your Reudan administrator.");
        disableForm();
        return;
      }
      window.location.replace("/ui/");
    } catch (_error) {
      showError(invalidInviteMessage);
      passwordInput.value = "";
      confirmInput.value = "";
      passwordInput.focus();
    } finally {
      if (!passwordInput.disabled) setBusy(false);
    }
  });

  boot();
})();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/static/service-worker.js").catch(() => {});
  });
}

window.addEventListener("load", () => {
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const message = form.getAttribute("data-confirm") || "Are you sure?";
      if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("form[data-control-form='true']").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button[type='submit']");
      if (button) {
        button.disabled = true;
      }
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        let payload = {};
        try {
          payload = await response.json();
        } catch (_) {}
        const message = payload.detail || payload.stderr || payload.stdout || `Control request returned ${response.status}.`;
        window.alert(message);
        window.location.reload();
      } catch (error) {
        window.alert(`Control request failed: ${error}`);
      } finally {
        if (button) {
          button.disabled = false;
        }
      }
    });
  });
});

(function () {
  const script = document.currentScript;
  const scriptUrl = new URL(script.src, window.location.href);
  const origin = (script.dataset.origin || scriptUrl.origin).replace(/\/$/, "");
  const config = window.__CLARITYOS_WIDGET_CONFIG__ || {};
  const branding = config.branding || {};
  const launcher = config.launcher || {};
  const allowedAgents = Array.isArray(config.allowed_agents) ? config.allowed_agents : [];
  const title = script.dataset.title || branding.name || "ClarityOS Assistant";
  const requestedAgent = script.dataset.agent || branding.default_agent || "researcher";
  const subtitle = script.dataset.subtitle || branding.tagline || "Ask the session-backed assistant";
  const channel = script.dataset.channel || "embed_widget";
  const accent = script.dataset.accent || branding.accent || "#176b52";
  const launcherLabel = script.dataset.label || branding.launcher_label || "Ask";
  const requestedPosition = script.dataset.position || launcher.position || "right";
  const position = requestedPosition === "left" ? "left" : "right";
  const requestedOpen = script.dataset.open;
  const startOpen = requestedOpen === "true" || (requestedOpen == null && launcher.default_open === true);
  const allowedOrigins = Array.isArray(config.allowed_origins) ? config.allowed_origins : [];
  const serviceOrigin = config.service_origin || origin;
  const enabled = config.enabled !== false;

  function resolveAgent(candidate) {
    if (!Array.isArray(allowedAgents) || allowedAgents.length === 0) {
      return candidate || branding.default_agent || "researcher";
    }
    if (candidate && allowedAgents.includes(candidate)) {
      return candidate;
    }
    if (branding.default_agent && allowedAgents.includes(branding.default_agent)) {
      return branding.default_agent;
    }
    return allowedAgents[0];
  }

  const agent = resolveAgent(requestedAgent);

  function originAllowed(requestedOrigin) {
    if (!requestedOrigin) {
      return true;
    }
    if (allowedOrigins.includes("*")) {
      return true;
    }
    if (allowedOrigins.length === 0) {
      return requestedOrigin === serviceOrigin;
    }
    return allowedOrigins.includes(requestedOrigin);
  }

  const container = document.createElement("div");
  container.style.position = "fixed";
  container.style[position] = "20px";
  container.style.bottom = "20px";
  container.style.zIndex = "2147483000";
  container.style.display = "grid";
  container.style.justifyItems = "end";
  container.style.gap = "10px";

  const iframe = document.createElement("iframe");
  iframe.title = title;
  iframe.src =
    `${origin}/widget?title=${encodeURIComponent(title)}` +
    `&agent=${encodeURIComponent(agent)}` +
    `&subtitle=${encodeURIComponent(subtitle)}` +
    `&channel=${encodeURIComponent(channel)}` +
    `&accent=${encodeURIComponent(accent)}` +
    `&parent_origin=${encodeURIComponent(window.location.origin)}`;
  iframe.style.width = "min(420px, calc(100vw - 24px))";
  iframe.style.height = "min(680px, calc(100vh - 100px))";
  iframe.style.border = "0";
  iframe.style.borderRadius = "22px";
  iframe.style.boxShadow = "0 24px 50px rgba(18, 23, 20, 0.18)";
  iframe.style.background = "transparent";
  iframe.style.display = startOpen ? "block" : "none";

  const launcher = document.createElement("button");
  launcher.type = "button";
  launcher.textContent = launcherLabel;
  launcher.setAttribute("aria-expanded", startOpen ? "true" : "false");
  launcher.style.border = "0";
  launcher.style.borderRadius = "999px";
  launcher.style.padding = "14px 18px";
  launcher.style.background = accent;
  launcher.style.color = "white";
  launcher.style.font = '600 14px Georgia, "Times New Roman", serif';
  launcher.style.cursor = "pointer";
  launcher.style.boxShadow = "0 16px 30px rgba(18, 23, 20, 0.16)";

  function setOpen(open) {
    iframe.style.display = open ? "block" : "none";
    launcher.setAttribute("aria-expanded", open ? "true" : "false");
    launcher.textContent = open ? "Close" : launcherLabel;
  }

  if (!enabled) {
    launcher.textContent = "Offline";
    launcher.disabled = true;
    launcher.style.opacity = "0.72";
    launcher.style.cursor = "not-allowed";
    launcher.title = "This deployment has disabled the widget surface.";
    container.appendChild(launcher);
    document.body.appendChild(container);
    return;
  }

  if (!originAllowed(window.location.origin)) {
    launcher.textContent = "Unavailable";
    launcher.disabled = true;
    launcher.style.opacity = "0.72";
    launcher.style.cursor = "not-allowed";
    launcher.title = "This host is not allowed to embed the widget.";
    container.appendChild(launcher);
    document.body.appendChild(container);
    return;
  }

  launcher.addEventListener("click", function () {
    const open = iframe.style.display !== "none";
    setOpen(!open);
  });

  container.appendChild(iframe);
  container.appendChild(launcher);
  document.body.appendChild(container);
})();

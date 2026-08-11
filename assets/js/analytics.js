(() => {
  "use strict";

  const config = {
    debug: location.hostname === "localhost" || location.hostname === "127.0.0.1",
    endpoint: null
  };

  function buildEvent(type, element) {
    return {
      event: type,
      label: element.dataset.trackLabel || "",
      href: element.href || "",
      page: location.pathname,
      title: document.title,
      timestamp: new Date().toISOString()
    };
  }

  function send(eventData) {
    // 将来 GA4 / Plausible / 独自エンドポイントへ差し替える境界。
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push(eventData);

    if (config.debug) {
      console.info("[analytics]", eventData);
    }

    if (config.endpoint && navigator.sendBeacon) {
      navigator.sendBeacon(
        config.endpoint,
        new Blob([JSON.stringify(eventData)], { type: "application/json" })
      );
    }
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-track]");
    if (!link) return;

    const kind = link.dataset.track;
    send(buildEvent(kind === "external" ? "external_click" : "internal_click", link));
  });

  send({
    event: "page_view",
    page: location.pathname,
    title: document.title,
    referrer: document.referrer,
    timestamp: new Date().toISOString()
  });
})();

(function () {
  "use strict";

  const euro = (n) => n.toLocaleString("de-AT") + " €";

  // Mobile nav
  const toggle = document.querySelector("[data-toggle-nav]");
  if (toggle) toggle.addEventListener("click", () => document.getElementById("main-nav").classList.toggle("open"));

  // User dropdown
  document.querySelectorAll("[data-dropdown]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      btn.parentElement.classList.toggle("open");
    });
  });
  document.addEventListener("click", () => document.querySelectorAll(".dropdown.open").forEach((d) => d.classList.remove("open")));

  // Dismiss alerts
  document.querySelectorAll("[data-dismiss]").forEach((b) => b.addEventListener("click", () => b.parentElement.remove()));

  // Confirm dialogs
  document.querySelectorAll("form[data-confirm]").forEach((f) => {
    f.addEventListener("submit", (e) => {
      if (!confirm(f.dataset.confirm)) e.preventDefault();
    });
  });

  // Booking total
  document.querySelectorAll(".booking-form").forEach((form) => {
    const price = parseInt(form.dataset.price, 10);
    const select = form.querySelector("[data-seat-select]");
    const out = form.querySelector("[data-total]");
    if (select && out) select.addEventListener("change", () => (out.textContent = euro(price * parseInt(select.value, 10))));
  });

  // Flight form: type-dependent fields + live price calculation
  const flightForm = document.querySelector("[data-flight-form]");
  if (flightForm) {
    const arrival = flightForm.querySelector("[data-arrival-field]");
    const ret = flightForm.querySelector("[data-return-fields]");
    const cost = flightForm.querySelector("[data-cost]");
    const seats = flightForm.querySelector("[data-seats]");
    const aircraft = flightForm.querySelector("[data-aircraft]");
    const priceOut = flightForm.querySelector("[data-price-out]");
    const shareOut = flightForm.querySelector("[data-pilot-share]");

    const syncType = () => {
      const t = flightForm.querySelector("input[name=flight_type]:checked").value;
      arrival.style.display = t === "roundtrip" ? "none" : "";
      ret.style.display = t === "daytrip" ? "" : "none";
    };
    const calc = () => {
      const c = parseInt(cost.value, 10);
      const s = parseInt(seats.value, 10);
      if (c > 0 && s > 0) {
        const p = Math.ceil(c / (s + 1));
        priceOut.textContent = euro(p);
        shareOut.textContent = euro(Math.max(c - p * s, 0));
      } else {
        priceOut.textContent = shareOut.textContent = "–";
      }
    };
    const syncSeats = () => {
      const opt = aircraft.selectedOptions[0];
      if (opt) {
        seats.max = opt.dataset.seats;
        if (parseInt(seats.value, 10) > parseInt(opt.dataset.seats, 10)) seats.value = opt.dataset.seats;
      }
      calc();
    };
    flightForm.querySelectorAll("input[name=flight_type]").forEach((r) => r.addEventListener("change", syncType));
    cost.addEventListener("input", calc);
    seats.addEventListener("input", calc);
    aircraft.addEventListener("change", syncSeats);
    syncType();
    syncSeats();
  }

  // Chat: scroll to bottom, Enter to send
  const chat = document.getElementById("chat-messages");
  if (chat) chat.scrollTop = chat.scrollHeight;
  document.querySelectorAll("[data-submit-on-enter]").forEach((ta) => {
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (ta.value.trim()) ta.form.submit();
      }
    });
  });

  // Share
  document.querySelectorAll("[data-share]").forEach((b) => {
    b.addEventListener("click", async () => {
      const url = b.dataset.share;
      try {
        if (navigator.share) await navigator.share({ title: document.title, url });
        else {
          await navigator.clipboard.writeText(url);
          b.textContent = "✔ Link kopiert";
        }
      } catch (e) { /* user cancelled */ }
    });
  });

  // Maps
  function initMap(el) {
    if (!window.L) return;
    let routes;
    try { routes = JSON.parse(el.dataset.routes); } catch (e) { return; }
    const map = L.map(el, { scrollWheelZoom: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    const bounds = [];
    routes.forEach((r) => {
      const same = r.from[0] === r.to[0] && r.from[1] === r.to[1];
      const popup = r.url ? `<a href="${r.url}">${escapeHtml(r.title)}</a>` : escapeHtml(r.title);
      L.circleMarker(r.from, { radius: 7, color: "#1d4ed8", fillColor: "#fff", fillOpacity: 1, weight: 3 })
        .addTo(map).bindPopup(r.fromLabel ? escapeHtml(r.fromLabel) : popup);
      bounds.push(r.from);
      if (same) {
        L.circle(r.from, { radius: 12000, color: "#7c3aed", weight: 2, dashArray: "6 6", fill: false }).addTo(map).bindPopup(popup);
        bounds.push([r.from[0] + 0.15, r.from[1] + 0.2], [r.from[0] - 0.15, r.from[1] - 0.2]);
      } else {
        L.circleMarker(r.to, { radius: 7, color: "#f97316", fillColor: "#fff", fillOpacity: 1, weight: 3 })
          .addTo(map).bindPopup(r.toLabel ? escapeHtml(r.toLabel) : popup);
        L.polyline(curve(r.from, r.to), { color: "#1d4ed8", weight: 3, dashArray: "8 6" }).addTo(map).bindPopup(popup);
        bounds.push(r.to);
      }
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 9 });
  }

  function curve(a, b) {
    const pts = [];
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const dx = b[1] - a[1], dy = b[0] - a[0];
    const ctrl = [mid[0] + dx * 0.15, mid[1] - dy * 0.15];
    for (let t = 0; t <= 1.0001; t += 0.05) {
      const lat = (1 - t) * (1 - t) * a[0] + 2 * (1 - t) * t * ctrl[0] + t * t * b[0];
      const lon = (1 - t) * (1 - t) * a[1] + 2 * (1 - t) * t * ctrl[1] + t * t * b[1];
      pts.push([lat, lon]);
    }
    return pts;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  window.addEventListener("load", () => document.querySelectorAll(".map[data-routes]").forEach(initMap));
})();

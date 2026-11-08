
(() => {
  "use strict";

  const DRIVER_DATA = {
    Suresh: {
      language: "Telugu + English",
      greeting: "నమస్కారం సురేష్ గారు.",
    },
    Amit: {
      language: "Hindi + English",
      greeting: "Namaste Amit ji.",
    },
  };

  const css = document.createElement("style");
  css.textContent = `
    #resq-driver-picker {
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 12px;
      margin: 12px 0;
      font: 13px system-ui, sans-serif;
      color: #111827;
    }
    #resq-driver-picker .resq-title {
      font-weight: 800;
      margin-bottom: 8px;
    }
    #resq-driver-picker .resq-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    #resq-driver-picker button {
      border: 1px solid #d1d5db;
      border-radius: 8px;
      background: #f8fafc;
      color: #111827;
      padding: 9px 14px;
      font-weight: 750;
      cursor: pointer;
    }
    #resq-driver-picker button.selected {
      background: #dc2626;
      border-color: #dc2626;
      color: white;
    }
    #resq-driver-picker .resq-info {
      margin-top: 8px;
      color: #64748b;
      font-size: 12px;
    }
  `;
  document.head.appendChild(css);

  function buildPicker() {
    if (document.getElementById("resq-driver-picker")) return;

    const phone = [...document.querySelectorAll("*")].find(
      element =>
        element.children.length === 0 &&
        element.textContent?.trim() === "SIGNATURE AI TELEPHONY"
    );

    if (!phone) return;

    const container = document.createElement("div");
    container.id = "resq-driver-picker";
    container.innerHTML = `
      <div class="resq-title">Choose rescue driver</div>
      <div class="resq-actions">
        <button type="button" data-driver="Suresh">Suresh · Telugu</button>
        <button type="button" data-driver="Amit">Amit · Hindi</button>
      </div>
      <div class="resq-info" role="status">
        Select a driver, then use the existing call workflow.
      </div>
    `;

    const section = phone.closest("section") || phone.parentElement;
    section.parentElement.insertBefore(container, section);

    container.addEventListener("click", event => {
      const button = event.target.closest("[data-driver]");
      if (!button) return;

      const name = button.dataset.driver;
      const driver = DRIVER_DATA[name];

      container.querySelectorAll("[data-driver]").forEach(item => {
        item.classList.toggle("selected", item === button);
      });

      container.querySelector(".resq-info").textContent =
        `${name} selected · ${driver.language}. ` +
        "Use the existing call action to start the demo.";

      // Shared selection hint for future backend integration.
      window.resqSelectedDriver = name;
      window.dispatchEvent(
        new CustomEvent("resq:driver-selected", {
          detail: { name, language: driver.language },
        })
      );
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildPicker);
  } else {
    buildPicker();
  }
})();

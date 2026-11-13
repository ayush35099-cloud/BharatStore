/**
 * BharatKart Real-Time Kafka & Event Stream Client
 * Connects to SSE stream to visualize Kafka message production and consumption.
 */

let eventCounter = 0;
let isTrayExpanded = false;

function initEventStream() {
  const trayList = document.getElementById("tray-events-list");
  const counterSpan = document.getElementById("event-counter");

  // Establish Server-Sent Events stream
  const evtSource = new EventSource("/api/events/stream");

  evtSource.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      appendEventToTray(data);
    } catch (err) {
      console.error("Error parsing SSE event:", err);
    }
  };

  evtSource.onerror = function () {
    // If SSE drops, fallback to polling every 3 seconds
    console.warn("SSE connection interrupted. Falling back to polling...");
    setTimeout(pollRecentEvents, 3000);
  };
}

async function pollRecentEvents() {
  try {
    const res = await fetch("/api/events/recent?limit=15");
    const events = await res.json();
    const trayList = document.getElementById("tray-events-list");
    trayList.innerHTML = "";
    events.forEach(evt => appendEventToTray(evt, false));
  } catch (err) {
    console.error("Error polling events:", err);
  }
}

function appendEventToTray(evt, increment = true) {
  const trayList = document.getElementById("tray-events-list");
  if (!trayList) return;

  if (increment) {
    eventCounter++;
    const counterSpan = document.getElementById("event-counter");
    if (counterSpan) counterSpan.textContent = eventCounter;
  }

  const isConsumed = evt.type === "CONSUMED";
  const item = document.createElement("div");
  item.className = `event-feed-item ${isConsumed ? "consumed" : ""}`;

  const header = `
    <div class="event-feed-header">
      <div>
        <span class="event-badge ${isConsumed ? 'cons' : 'prod'}">
          ${isConsumed ? '<i class="fa-solid fa-arrow-down"></i> KAFKA CONSUMED' : '<i class="fa-solid fa-arrow-up"></i> KAFKA PRODUCED'}
        </span>
        <strong style="color: #fff; margin-left: 6px;">[Topic: ${evt.topic || 'order-events'}]</strong>
        <span style="color: #94a3b8; font-size: 11px;">(${evt.broker || 'Apache Kafka'})</span>
      </div>
      <div>
        <span>${evt.logged_at || new Date().toLocaleTimeString()}</span>
      </div>
    </div>
  `;

  let details = "";
  if (isConsumed) {
    details = `
      <div style="font-size: 11px; color: #a7f3d0; margin-top: 4px;">
        <strong>Consumer Group:</strong> ${evt.source} | Partition: ${evt.partition} | Offset: ${evt.offset}
      </div>
      <div style="font-size: 11px; color: #cbd5e1; margin-top: 2px;">
        ${(evt.actions_triggered || []).map(a => `<div>&bull; ${a}</div>`).join('')}
      </div>
    `;
  } else {
    details = `
      <div style="font-size: 11px; color: #fecdd3; margin-top: 4px;">
        <strong>Event ID:</strong> ${evt.event_id} | Order #${evt.order_number} | Amount: ₹${evt.payload.total_amount.toLocaleString('en-IN')}
      </div>
      <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">
        Items: ${evt.payload.items.map(i => `${i.title} (x${i.qty})`).join(', ')} &rarr; Dest: ${evt.payload.shipping_city}
      </div>
    `;
  }

  item.innerHTML = header + details;
  trayList.insertBefore(item, trayList.firstChild);

  // Keep maximum 40 items in tray DOM
  if (trayList.children.length > 40) {
    trayList.removeChild(trayList.lastChild);
  }
}

function toggleEventTray() {
  const tray = document.getElementById("event-inspector-tray");
  const icon = document.getElementById("tray-toggle-icon");
  if (!tray) return;

  isTrayExpanded = !isTrayExpanded;
  if (isTrayExpanded) {
    tray.classList.add("expanded");
    if (icon) icon.innerHTML = '<i class="fa-solid fa-chevron-down"></i>';
  } else {
    tray.classList.remove("expanded");
    if (icon) icon.innerHTML = '<i class="fa-solid fa-chevron-up"></i>';
  }
}

// Start on DOM ready
document.addEventListener("DOMContentLoaded", initEventStream);

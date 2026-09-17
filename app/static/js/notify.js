// UC5: Receive Order Notification - polls the server every 3s to simulate a push notification.
let lastStatus = null;

const STATUS_HEADER_CLASS = {
  Pending: "bg-danger",
  Preparing: "bg-warning",
  Ready: "bg-success",
  Completed: "bg-secondary",
};

function paintStatus(status) {
  document.querySelectorAll(".status-step").forEach((el) => {
    const active = el.dataset.status === status;
    el.classList.toggle("bg-primary", active);
    el.classList.toggle("text-white", active);
    el.classList.toggle("fw-bold", active);
    el.classList.toggle("bg-light", !active);
    el.classList.toggle("text-muted", !active);
  });

  const header = document.querySelector(".lapar-status-header");
  if (header) {
    Object.values(STATUS_HEADER_CLASS).forEach((c) => header.classList.remove(c));
    header.classList.add(STATUS_HEADER_CLASS[status] || "bg-secondary");
  }
  const statusText = document.querySelector(".lapar-status-header h3");
  if (statusText) statusText.textContent = status;
}

async function poll() {
  try {
    const res = await fetch(`/api/order/${ORDER_ID}`);
    if (!res.ok) return;
    const data = await res.json();
    paintStatus(data.status);

    if (data.status !== lastStatus) {
      lastStatus = data.status;
      if (data.status === "Ready" && data.notification) {
        const banner = document.getElementById("notif-banner");
        banner.textContent = "🔔 " + data.notification;
        banner.hidden = false;
      }
    }
  } catch (e) {
    // network hiccup - ignore, will retry on next tick
  }
}

poll();
setInterval(poll, 3000);

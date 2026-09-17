let selectedPackagePrice = 0;

function changeQty(btn, delta) {
  const input = btn.parentElement.querySelector(".qty-input");
  let val = parseInt(input.value || "0", 10) + delta;
  if (val < 0) val = 0;
  input.value = val;
  updateTotal();
}

function changePackageQty(delta) {
  const input = document.getElementById("package_qty");
  let val = parseInt(input.value || "1", 10) + delta;
  if (val < 1) val = 1;
  input.value = val;
  updateTotal();
}

function selectPackage(packageId, price) {
  document.getElementById("package_id").value = packageId;
  selectedPackagePrice = price;
  document.querySelectorAll(".lapar-package-card").forEach((card) => {
    card.classList.toggle("selected", Number(card.dataset.packageId) === packageId);
  });
  updateTotal();
}

function updateTotal() {
  const isMeeting = document.getElementById("is_meeting").checked;
  let total = 0;

  if (isMeeting) {
    const qty = parseInt(document.getElementById("package_qty").value || "0", 10);
    total = selectedPackagePrice * qty;
  } else {
    document.querySelectorAll("#regular-menu-section .qty-input").forEach((input) => {
      const qty = parseInt(input.value || "0", 10);
      const price = parseFloat(input.dataset.price || "0");
      total += qty * price;
    });
  }

  const display = document.getElementById("total-display");
  if (display) display.textContent = "RM " + total.toFixed(2);
}

function toggleMeeting() {
  const checked = document.getElementById("is_meeting").checked;
  document.getElementById("meeting-fields").hidden = !checked;
  document.getElementById("order_type").value = checked ? "MeetingRoom" : "Counter";
  document.getElementById("regular-menu-section").hidden = checked;
  document.getElementById("catering-section").hidden = !checked;
  updateTotal();
}

document.addEventListener("DOMContentLoaded", () => {
  updateTotal();
  if (window.location.hash === "#meeting") {
    const checkbox = document.getElementById("is_meeting");
    checkbox.checked = true;
    toggleMeeting();
    document.getElementById("meeting").scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

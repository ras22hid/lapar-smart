// Meeting-room catering page (Chief Clerk only): pick a package, set how many.
let selectedPackagePrice = 0;

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
  const qty = parseInt(document.getElementById("package_qty").value || "0", 10);
  const display = document.getElementById("total-display");
  if (display) display.textContent = "RM " + (selectedPackagePrice * qty).toFixed(2);
}

document.addEventListener("DOMContentLoaded", () => {
  updateTotal();
  document.getElementById("order-form").addEventListener("submit", (e) => {
    if (!document.getElementById("package_id").value) {
      e.preventDefault();
      alert("Please choose a catering package first.");
    }
  });
});

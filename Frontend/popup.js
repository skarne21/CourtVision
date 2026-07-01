document.addEventListener('DOMContentLoaded', () => {
  const bankrollInput = document.getElementById('bankroll');

  // Load existing bankroll
  chrome.storage.local.get('bankroll', (data) => {
    if (data.bankroll !== undefined) {
      bankrollInput.value = data.bankroll;
    }
  });

  // Save bankroll on input
  bankrollInput.addEventListener('input', (e) => {
    const value = parseFloat(e.target.value);
    if (!isNaN(value) && value >= 0) {
      chrome.storage.local.set({ bankroll: value });
    } else if (e.target.value === '') {
      chrome.storage.local.set({ bankroll: 0 });
    }
  });
});
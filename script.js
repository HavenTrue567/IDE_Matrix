// Web script demo inside preview iframe
console.log("Web script loaded successfully!");

const btn = document.getElementById('action-btn');
const status = document.getElementById('status-text');

let clickCount = 0;

btn.addEventListener('click', () => {
  clickCount++;
  console.log(`Action button clicked! Count: ${clickCount}`);
  
  status.textContent = `Clicked ${clickCount} time${clickCount > 1 ? 's' : ''}!`;
  
  if (clickCount >= 5) {
    status.textContent = "Wow! You really like clicking that button!";
    console.warn("Click warning: Button usage is higher than normal!");
  }
});

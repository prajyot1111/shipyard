// The reports page: fetch the list from the api and draw it as a table.
const API = "http://127.0.0.1:8000";

async function load(query) {
  const url = query ? `${API}/reports?q=${encodeURIComponent(query)}` : `${API}/reports`;
  const response = await fetch(url);
  return response.json();
}

function draw(reports) {
  const body = document.querySelector("#reports tbody");
  body.innerHTML = "";
  for (const report of reports) {
    const row = document.createElement("tr");
    for (const value of [report.title, report.owner, report.created, report.total]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    }
    body.appendChild(row);
  }
}

document.querySelector("#search").addEventListener("input", async (event) => {
  draw(await load(event.target.value));
});

load("").then(draw);

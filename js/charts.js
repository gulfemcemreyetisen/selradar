/* ============ PentEarth · Grafikler (Chart.js) ============ */
(function () {
  "use strict";
  let rainChart = null;

  function shortDate(iso) {
    const d = new Date(iso + "T00:00:00");
    if (isNaN(d)) return iso;
    return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "short" });
  }

  function rain(data, floodDate) {
    const canvas = document.getElementById("rain-chart");
    if (!canvas || typeof Chart === "undefined") return;

    const daily = (data && Array.isArray(data.daily)) ? data.daily : [];
    const unit = (data && data.unit) || "mm";
    const labels = daily.map(d => shortDate(d.date));
    const values = daily.map(d => Number(d.mm ?? d.value ?? 0));

    let run = 0;
    const cumulative = values.map(v => (run += v));

    const barColors = daily.map(d =>
      d.date === floodDate ? "rgba(255,93,108,.9)" : "rgba(47,140,255,.75)"
    );

    if (rainChart) rainChart.destroy();

    Chart.defaults.color = "#8b9ab5";
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";

    rainChart = new Chart(canvas, {
      data: {
        labels,
        datasets: [
          {
            type: "bar",
            label: `Günlük yağış (${unit})`,
            data: values,
            backgroundColor: barColors,
            borderRadius: 4,
            yAxisID: "y"
          },
          {
            type: "line",
            label: `Kümülatif (${unit})`,
            data: cumulative,
            borderColor: "#35d0ba",
            backgroundColor: "#35d0ba",
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.3,
            yAxisID: "y2"
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { boxWidth: 10, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              afterTitle: items => {
                const d = daily[items[0].dataIndex];
                return d && d.date === floodDate ? "Sel tarihi" : "";
              }
            }
          }
        },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, grid: { color: "rgba(36,50,79,.6)" }, title: { display: true, text: unit } },
          y2: { beginAtZero: true, position: "right", grid: { display: false } }
        }
      }
    });
  }

  function empty(message) {
    const box = document.querySelector(".chart-box");
    if (box) box.innerHTML = `<p class="muted" style="padding-top:70px;text-align:center">${message}</p>`;
  }

  window.PECharts = { rain, empty };
})();
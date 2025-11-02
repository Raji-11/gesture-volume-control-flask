// Chart.js live chart: Volume (%) vs Distance (px) using distance labels
const ctx = document.getElementById('volumeChart').getContext('2d');
const chartData = {
  labels: [],
  datasets: [{
    label: 'Volume (%)',
    data: [],
    borderColor: '#00f6ea',
    backgroundColor: 'rgba(0,246,234,0.08)',
    tension: 0.25,
    fill: true,
    pointRadius: 3
  }]
};
const volumeChart = new Chart(ctx, {
  type: 'line',
  data: chartData,
  options: {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      y: { min: 0, max: 100, ticks: { color: '#9deaf1' } },
      x: { title: { display: true, text: 'Finger Distance (px)', color: '#9deaf1' }, ticks: { color: '#9deaf1' } }
    },
    plugins: { legend: { labels: { color: '#9deaf1' } } }
  }
});

// fetch metrics and update UI
async function fetchMetrics() {
  try {
    const res = await fetch('/metrics');
    if (!res.ok) throw new Error('not authorized');
    const d = await res.json();
    document.getElementById('volume').innerText = `${d.volume}%`;
    document.getElementById('distance').innerText = `${d.distance} px`;
    document.getElementById('accuracy').innerText = `${d.accuracy}%`;
    document.getElementById('response').innerText = `${d.response_time} ms`;
    document.getElementById('gesture').innerText = d.gesture;

    // add a pair: x = distance label, y = volume value
    chartData.labels.push(d.distance.toString()); // label shows distance
    chartData.datasets[0].data.push(d.volume);

    // keep last 40 points
    if (chartData.labels.length > 40) {
      chartData.labels.shift();
      chartData.datasets[0].data.shift();
    }
    volumeChart.update();
  } catch (err) {
    console.error('fetchMetrics error', err);
  } finally {
    setTimeout(fetchMetrics, 350); // ~3 updates/second
  }
}
fetchMetrics();

// Start / Stop
document.getElementById('startBtn').addEventListener('click', async () => {
  try {
    await fetch('/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ running: true }) });
  } catch (e) { console.error(e); }
});
document.getElementById('stopBtn').addEventListener('click', async () => {
  try {
    await fetch('/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ running: false }) });
  } catch (e) { console.error(e); }
});

// Save session (CSV) - will trigger server to clear session buffer (auto-reset)
document.getElementById('saveBtn').addEventListener('click', async () => {
  try {
    const resp = await fetch('/save_report');
    if (!resp.ok) throw new Error('save failed');
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `gesture_session_${new Date().toISOString().replace(/[:.]/g,'')}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    // clear chart client-side (since server cleared buffer too)
    chartData.labels = [];
    chartData.datasets[0].data = [];
    volumeChart.update();
  } catch (err) {
    alert("Could not save session. Try again.");
    console.error(err);
  }
});

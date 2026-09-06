"""Simulated model routing with priority policy and Prometheus metrics."""

import random
from threading import Event, Thread

from flask import Flask, Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

app = Flask(__name__)

cost_saved_usd = Counter(
    "ai_platform_cost_saved_usd",
    "Cumulative simulated USD saved by routing to the lightweight model.",
)
gpu_utilization = Gauge(
    "ai_platform_gpu_utilization_percentage",
    "Simulated cluster GPU utilization percentage.",
)
# Seed the gauge before the first simulator tick or scrape.
gpu_utilization.set(random.uniform(65, 90))


def simulate_gpu(stop: Event, interval: float = 5.0) -> None:
    """Update simulated GPU state independently of HTTP requests."""
    while not stop.wait(interval):
        gpu_utilization.set(random.uniform(65, 90))


@app.post("/v1/chat/completions")
def chat_completions():
    """Return a simulated routing decision for a JSON string prompt."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("prompt"), str):
        return jsonify(error="Request body must be a JSON object with a string prompt."), 400

    model = "llama-3.2-1b"
    savings = 0.0
    if len(body["prompt"]) < 50 and request.headers.get("X-Priority") == "Low":
        model = "qwen-2.5-0.5b"
        savings = 0.04
        cost_saved_usd.inc(savings)

    return jsonify(model=model, cost_saved_usd=savings, simulated=True)


@app.get("/metrics")
def metrics():
    """Expose the current metrics without changing simulated GPU state."""
    return Response(generate_latest(), content_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    stop_simulator = Event()
    simulator = Thread(target=simulate_gpu, args=(stop_simulator,), daemon=True)
    simulator.start()
    try:
        app.run(host="0.0.0.0", port=5000, use_reloader=False)
    finally:
        stop_simulator.set()
        simulator.join()

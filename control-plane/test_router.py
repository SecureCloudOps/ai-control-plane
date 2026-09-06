"""HTTP policy boundaries, input validation, and exported metrics."""

import unittest
from threading import Event, Thread
from unittest.mock import patch

from prometheus_client.parser import text_string_to_metric_families

from router import app, gpu_utilization, simulate_gpu


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def read_metrics(self):
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/plain"))
        return {
            sample.name: sample.value
            for family in text_string_to_metric_families(response.get_data(as_text=True))
            for sample in family.samples
        }

    def test_policy_and_cumulative_savings(self):
        counter = "ai_platform_cost_saved_usd_total"
        before = self.read_metrics()[counter]
        cases = [
            ("x" * 49, "Low", "qwen-2.5-0.5b", 0.04),
            ("", "Low", "qwen-2.5-0.5b", 0.04),
            ("x" * 50, "Low", "llama-3.2-1b", 0),
            ("x" * 51, "Low", "llama-3.2-1b", 0),
            ("short", "High", "llama-3.2-1b", 0),
            ("short", "Batch", "llama-3.2-1b", 0),
            ("short", "low", "llama-3.2-1b", 0),
            ("short", None, "llama-3.2-1b", 0),
        ]
        for prompt, priority, model, savings in cases:
            with self.subTest(length=len(prompt), priority=priority):
                headers = {} if priority is None else {"X-Priority": priority}
                response = self.client.post(
                    "/v1/chat/completions", json={"prompt": prompt}, headers=headers
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {
                    "model": model, "cost_saved_usd": savings, "simulated": True
                })
                before += savings
                self.assertAlmostEqual(self.read_metrics()[counter], before)

    def test_invalid_input(self):
        before = self.read_metrics()["ai_platform_cost_saved_usd_total"]
        for body in ({}, {"prompt": None}, {"prompt": 42}, [], "text"):
            with self.subTest(body=body):
                response = self.client.post("/v1/chat/completions", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json)
        response = self.client.post(
            "/v1/chat/completions", data="{", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.read_metrics()["ai_platform_cost_saved_usd_total"], before)

    def test_gpu_range(self):
        for _ in range(10):
            value = self.read_metrics()["ai_platform_gpu_utilization_percentage"]
            self.assertGreaterEqual(value, 65)
            self.assertLessEqual(value, 90)

    def test_scrapes_do_not_change_gpu_state(self):
        gpu_utilization.set(77)
        with patch("router.random.uniform") as random_value:
            for _ in range(3):
                self.assertEqual(
                    self.read_metrics()["ai_platform_gpu_utilization_percentage"], 77
                )
            random_value.assert_not_called()

    def test_simulator_updates_without_scrapes_and_stops(self):
        stop = Event()
        updated = Event()
        original_set = gpu_utilization.set

        def record_update(value):
            original_set(value)
            updated.set()

        with patch("router.random.uniform", return_value=82), patch.object(
            gpu_utilization, "set", side_effect=record_update
        ):
            simulator = Thread(target=simulate_gpu, args=(stop, 0.01), daemon=True)
            simulator.start()
            try:
                self.assertTrue(updated.wait(timeout=2), "Simulator did not update")
            finally:
                stop.set()
                simulator.join(timeout=2)
            self.assertFalse(simulator.is_alive())
        self.assertEqual(
            self.read_metrics()["ai_platform_gpu_utilization_percentage"], 82
        )


if __name__ == "__main__":
    unittest.main()

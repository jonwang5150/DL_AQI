"""驗證多步回測的時間對齊與無未來資訊補值。"""

import unittest

import numpy as np
import pandas as pd
import torch

from predict_2026_8h import predict_period, prepare_inputs


class LastObservationModel(torch.nn.Module):
    def forward(self, inputs):
        # 以窗口最後值及輸出位置編碼，讓測試能辨識基準時間及提前小時。
        return inputs[:, -1, 0:1] * 100 + torch.arange(1, 9)


class BacktestTests(unittest.TestCase):
    def test_two_days_have_all_horizons_and_correct_origins(self):
        start, end = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-03")
        query_start = start - pd.Timedelta(hours=31)
        timeline = pd.date_range(query_start, end - pd.Timedelta(hours=2), freq="h")
        inputs = np.arange(len(timeline), dtype=float).reshape(-1, 1)
        result = predict_period(LastObservationModel(), inputs, 24, 8, start, end, 7)
        self.assertEqual(len(result), 384)
        self.assertTrue(result.groupby("target_at")["horizon_hours"].nunique().eq(8).all())
        for row in result.itertuples():
            origin = pd.Timestamp(row.target_at) - pd.Timedelta(hours=row.horizon_hours)
            index = int((origin - query_start) / pd.Timedelta(hours=1))
            self.assertEqual(row.predicted_aqi, index * 100 + row.horizon_hours)

    def test_forward_fill_does_not_use_future_or_modify_observations(self):
        times = pd.date_range("2026-01-01", periods=4, freq="h")
        raw = pd.DataFrame({"日期": times, "AQI": [10., np.nan, 30., 40.]})
        inputs, _, missing = prepare_inputs(raw, ["AQI"], times[0], times[-1],
                                             np.array([0.]), np.array([1.]))
        np.testing.assert_array_equal(inputs[:, 0], [10., 10., 30., 40.])
        self.assertEqual(missing, 1)
        self.assertTrue(pd.isna(raw.loc[1, "AQI"]))

    def test_missing_tail_is_not_fabricated(self):
        times = pd.date_range("2026-01-01", periods=4, freq="h")
        raw = pd.DataFrame({"日期": times[:2], "AQI": [10., 20.]})
        with self.assertRaisesRegex(ValueError, "觀測範圍不足"):
            prepare_inputs(raw, ["AQI"], times[0], times[-1],
                           np.array([0.]), np.array([1.]))


if __name__ == "__main__":
    unittest.main()

"""驗證模型比較使用共同有效時間點與已知誤差。"""

import unittest

import numpy as np
import pandas as pd

from feature_visualizations import evaluate_prediction_data


class EvaluationTests(unittest.TestCase):
    def test_common_targets_and_known_metrics(self):
        times = pd.date_range("2026-01-01", periods=5, freq="h")
        first = pd.DataFrame({
            "日期": times, "預測AQI": [13., 16., 90., 20., np.inf],
            "實際AQI": [10., 20., np.nan, 10., 10.],
        })
        second = pd.DataFrame({
            "日期": times[[1, 0, 2, 4]], "預測AQI": [22., 8., 90., 10.],
            "實際AQI": [20., 10., np.nan, 10.],
        })
        result = evaluate_prediction_data({"single": first, "8h": second}).set_index("來源")
        self.assertEqual(result.loc["single", "有效筆數"], 2)
        self.assertEqual(result.loc["single", "未納入筆數"], 3)
        self.assertEqual(result.loc["8h", "未納入筆數"], 2)
        self.assertAlmostEqual(result.loc["single", "MAE"], 3.5)
        self.assertAlmostEqual(result.loc["single", "RMSE"], np.sqrt(12.5))
        self.assertAlmostEqual(result.loc["single", "Bias"], -0.5)
        self.assertAlmostEqual(result.loc["8h", "MAE"], 2.)
        self.assertAlmostEqual(result.loc["8h", "Bias"], 0.)

    def test_no_common_targets(self):
        first = pd.DataFrame({"日期": [pd.Timestamp("2026-01-01")],
                              "預測AQI": [1.], "實際AQI": [1.]})
        second = first.assign(日期=pd.Timestamp("2026-01-02"))
        result = evaluate_prediction_data({"single": first, "8h": second})
        self.assertTrue(result["有效筆數"].eq(0).all())
        self.assertTrue(result[["MAE", "RMSE", "Bias"]].isna().all().all())


if __name__ == "__main__":
    unittest.main()

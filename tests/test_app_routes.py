import io
import os
import sys
import tempfile
import time
import unittest


def load_isolated_app(database_path):
    os.environ["DATA_ANALYZER_DATABASE"] = database_path
    os.environ["DATA_ANALYZER_CREATE_DEFAULT_ADMIN"] = "0"
    os.environ["DATA_ANALYZER_ALLOWED_ORIGINS"] = "http://127.0.0.1:5500"

    for module_name in ["server.app", "server.database.manager", "server.config"]:
        sys.modules.pop(module_name, None)

    import server.app as app_module

    app_module.app.config.update(TESTING=True)
    return app_module


class AppRoutesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.temp_dir.name, "test.sqlite3")
        self.app_module = load_isolated_app(db_path)
        self.client = self.app_module.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def auth_headers(self):
        self.client.post("/auth/register", json={"username": "tester", "password": "secret123"})
        response = self.client.post("/auth/login", json={"username": "tester", "password": "secret123"})
        token = response.get_json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def upload_csv(self, headers):
        csv_bytes = b"feature,target,category\n1,2,a\n2,4,b\n3,6,a\n4,8,b\n5,10,a\n"
        return self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_bytes), "dataset.csv")},
            content_type="multipart/form-data",
        )

    def test_protected_routes_require_authorization(self):
        response = self.client.get("/statistics")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Unauthorized")

    def test_register_login_upload_and_statistics_flow(self):
        headers = self.auth_headers()

        upload_response = self.upload_csv(headers)
        stats_response = self.client.get("/statistics", headers=headers)

        self.assertEqual(upload_response.status_code, 200)
        self.assertEqual(upload_response.get_json()["shape"], [5, 3])
        self.assertEqual(stats_response.status_code, 200)
        self.assertIn("feature", stats_response.get_json())

    def test_upload_rejects_missing_file_wrong_extension_and_empty_csv(self):
        headers = self.auth_headers()

        missing = self.client.post("/upload", headers=headers, data={}, content_type="multipart/form-data")
        wrong_ext = self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(b"a,b\n1,2\n"), "dataset.txt")},
            content_type="multipart/form-data",
        )
        empty = self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(b"a,b\n"), "dataset.csv")},
            content_type="multipart/form-data",
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(wrong_ext.status_code, 400)
        self.assertEqual(empty.status_code, 400)

    def test_analysis_routes_validate_inputs_and_limit_dataset(self):
        headers = self.auth_headers()
        self.upload_csv(headers)

        bad_correlation = self.client.post(
            "/correlation",
            headers=headers,
            json={"col_x": "feature", "col_y": "missing", "method": "pearson"},
        )
        limit_response = self.client.post("/limit", headers=headers, json={"limit": 2})
        regression_response = self.client.post(
            "/regression",
            headers=headers,
            json={"col_x": "feature", "col_y": "target"},
        )

        self.assertEqual(bad_correlation.status_code, 400)
        self.assertEqual(limit_response.status_code, 200)
        limit_payload = limit_response.get_json()
        self.assertEqual(limit_payload["shape"], [2, 3])
        self.assertTrue(limit_payload["sample_info"]["is_limited"])
        self.assertEqual(limit_payload["sample_info"]["current_rows"], 2)
        self.assertEqual(limit_payload["sample_info"]["source_rows"], 5)
        self.assertEqual(regression_response.status_code, 200)
        regression_payload = regression_response.get_json()
        self.assertEqual(regression_payload["trend"]["kind"], "grouped")
        self.assertTrue(regression_payload["trend"]["points"])
        self.assertTrue(regression_payload["insights"])

    def test_metadata_and_summary_report_routes(self):
        headers = self.auth_headers()
        self.upload_csv(headers)

        metadata_response = self.client.post(
            "/metadata/column",
            headers=headers,
            json={
                "column": "target",
                "semantic_role": "target",
                "description": "Test target column",
                "class_descriptions": {"2": "positive"},
            },
        )
        profile_response = self.client.get("/dataset/profile", headers=headers)
        report_response = self.client.get("/report/summary", headers=headers)

        self.assertEqual(metadata_response.status_code, 200)
        self.assertEqual(metadata_response.get_json()["metadata"]["semantic_role"], "target")
        self.assertEqual(profile_response.status_code, 200)
        self.assertIn("quality_warnings", profile_response.get_json())
        self.assertEqual(report_response.status_code, 200)
        report = report_response.get_json()
        self.assertTrue(report["overview"])
        self.assertTrue(report["workflow"])
        self.assertTrue(report["recommended_actions"])

    def test_workflow_status_uses_current_dataset_actions(self):
        headers = self.auth_headers()
        self.upload_csv(headers)

        initial = self.client.get("/workflow/status", headers=headers)
        initial_steps = initial.get_json()["steps"]
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial_steps[0]["status"], "done")
        self.assertEqual(initial_steps[1]["status"], "pending")
        self.assertEqual(initial_steps[2]["status"], "pending")

        self.client.get("/cleaning/plan", headers=headers)
        self.client.post(
            "/metadata/column",
            headers=headers,
            json={"column": "target", "semantic_role": "target", "description": "Target column"},
        )

        updated = self.client.get("/workflow/status", headers=headers)
        updated_steps = updated.get_json()["steps"]
        self.assertEqual(updated_steps[1]["status"], "done")
        self.assertEqual(updated_steps[2]["status"], "done")
        self.assertEqual(updated_steps[4]["status"], "done")

    def test_cleaning_plan_apply_and_create_class_column(self):
        headers = self.auth_headers()
        csv_bytes = (
            b"feature,target,constant,text\n"
            b"0,1,5,alpha\n"
            b"2,,5,beta\n"
            b"2,,5,beta\n"
            b"6,0,5,gamma\n"
            b"9,1,5,delta\n"
        )
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_bytes), "dirty.csv")},
            content_type="multipart/form-data",
        )

        plan_response = self.client.get("/cleaning/plan", headers=headers)
        clean_response = self.client.post(
            "/cleaning/apply",
            headers=headers,
            json={
                "drop_duplicate_rows": True,
                "drop_constant_columns": True,
                "missing_strategy": "smart_fill",
                "zero_as_missing_columns": ["feature"],
            },
        )
        class_response = self.client.post(
            "/classes/create",
            headers=headers,
            json={
                "source_column": "feature",
                "new_column": "feature_class",
                "mode": "ranges",
                "rules": [
                    {"code": "0", "min": None, "max": 5, "label": "low feature"},
                    {"code": "1", "min": 6, "max": None, "label": "high feature"},
                ],
            },
        )
        options_response = self.client.get(
            "/modeling/options?target=feature_class",
            headers=headers,
        )

        self.assertEqual(plan_response.status_code, 200)
        plan = plan_response.get_json()
        self.assertEqual(plan["summary"]["duplicate_rows"], 1)
        self.assertIn("constant", plan["constant_columns"])
        self.assertEqual(clean_response.status_code, 200)
        self.assertEqual(clean_response.get_json()["shape"], [4, 3])
        self.assertTrue(clean_response.get_json()["changes"])
        self.assertEqual(class_response.status_code, 200)
        class_payload = class_response.get_json()
        self.assertEqual(class_payload["column"], "feature_class")
        self.assertEqual(class_payload["source_column"], "feature")
        self.assertEqual(class_payload["shape"], [4, 4])
        self.assertEqual(class_payload["unmatched_count"], 0)
        self.assertTrue(class_payload["class_distribution"])
        self.assertEqual(options_response.status_code, 200)
        feature_option = [
            item for item in options_response.get_json()["feature_options"]
            if item["column"] == "feature"
        ][0]
        self.assertFalse(feature_option["selected"])
        self.assertIn("витоку", feature_option["reason"])

    def test_modeling_compare_supports_regression(self):
        headers = self.auth_headers()
        csv_bytes = (
            b"area,rooms,city,price\n"
            b"100,3,a,120000\n"
            b"120,3,a,140000\n"
            b"150,4,b,190000\n"
            b"180,4,b,230000\n"
            b"210,5,c,260000\n"
            b"260,5,c,320000\n"
            b"300,6,c,390000\n"
            b"330,6,d,420000\n"
        )
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_bytes), "prices.csv")},
            content_type="multipart/form-data",
        )

        response = self.client.post(
            "/modeling/compare",
            headers=headers,
            json={
                "target": "price",
                "task_type": "regression",
                "features": ["area", "rooms", "city"],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["task_type"], "regression")
        self.assertEqual(len(payload["models"]), 2)
        self.assertIn("rmse", payload["models"][0])
        self.assertTrue(payload["feature_importance"])

    def test_auth_rejects_invalid_inputs_duplicate_user_and_bad_login(self):
        short_user = self.client.post("/auth/register", json={"username": "ab", "password": "secret123"})
        short_password = self.client.post("/auth/register", json={"username": "valid", "password": "123"})
        first = self.client.post("/auth/register", json={"username": "unique", "password": "secret123"})
        duplicate = self.client.post("/auth/register", json={"username": "unique", "password": "secret123"})
        bad_login = self.client.post("/auth/login", json={"username": "unique", "password": "wrong"})

        self.assertEqual(short_user.status_code, 400)
        self.assertEqual(short_password.status_code, 400)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(bad_login.status_code, 401)

    def test_dataset_profile_reports_roles_quality_and_metadata_coverage(self):
        headers = self.auth_headers()
        csv_text = (
            "binary,encoded,continuous,text,constant\n"
            + "\n".join(
                f"{index % 2},{index % 4},{100 + index * 7},label_{index % 3},5"
                for index in range(20)
            )
        )
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_text.encode("utf-8")), "profile.csv")},
            content_type="multipart/form-data",
        )

        response = self.client.get("/dataset/profile", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("binary", payload["binary_columns"])
        self.assertIn("encoded", payload["categorical_encoded_columns"])
        self.assertIn("continuous", payload["continuous_columns"])
        self.assertIn("constant", payload["constant_columns"])
        self.assertIn("metadata_coverage", payload)

    def test_cleaning_rejects_bad_payloads_and_can_drop_high_cardinality_text(self):
        headers = self.auth_headers()
        csv_text = "value,text\n" + "\n".join(
            f"{index},text_{index}" for index in range(60)
        )
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_text.encode("utf-8")), "dirty.csv")},
            content_type="multipart/form-data",
        )

        bad_zero_payload = self.client.post(
            "/cleaning/apply",
            headers=headers,
            json={"zero_as_missing_columns": "value"},
        )
        cleaned = self.client.post(
            "/cleaning/apply",
            headers=headers,
            json={"drop_high_cardinality_text": True},
        )

        self.assertEqual(bad_zero_payload.status_code, 400)
        self.assertEqual(cleaned.status_code, 200)
        self.assertEqual(cleaned.get_json()["shape"], [60, 1])

    def test_cleaning_rejects_strategy_that_removes_all_rows(self):
        headers = self.auth_headers()
        csv_bytes = b"a,b\n1,\n,2\n"
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_bytes), "missing.csv")},
            content_type="multipart/form-data",
        )

        response = self.client.post(
            "/cleaning/apply",
            headers=headers,
            json={"missing_strategy": "drop_rows"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("removed all rows", response.get_json()["error"])

    def test_class_creation_supports_value_rules_and_rejects_bad_ranges(self):
        headers = self.auth_headers()
        csv_bytes = b"label,value\na,10\nb,20\nc,30\na,40\n"
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_bytes), "classes.csv")},
            content_type="multipart/form-data",
        )

        value_response = self.client.post(
            "/classes/create",
            headers=headers,
            json={
                "source_column": "label",
                "new_column": "label_class",
                "mode": "values",
                "rules": [
                    {"code": "0", "values": ["a"], "label": "group a"},
                    {"code": "1", "values": ["b", "c"], "label": "group bc"},
                ],
            },
        )
        bad_range = self.client.post(
            "/classes/create",
            headers=headers,
            json={
                "source_column": "value",
                "mode": "ranges",
                "rules": [{"code": "0", "min": 10, "max": 5}],
            },
        )

        self.assertEqual(value_response.status_code, 200)
        self.assertEqual(value_response.get_json()["unmatched_count"], 0)
        self.assertEqual(bad_range.status_code, 400)

    def test_metadata_rejects_invalid_source_and_state_roundtrip(self):
        headers = self.auth_headers()
        self.upload_csv(headers)

        missing_source = self.client.post(
            "/metadata/column",
            headers=headers,
            json={"column": "target", "source_column": "missing"},
        )
        self_source = self.client.post(
            "/metadata/column",
            headers=headers,
            json={"column": "target", "source_column": "target"},
        )
        saved_state = self.client.post(
            "/state/analysis/latest",
            headers=headers,
            json={"chart": "matrix", "ready": True},
        )
        loaded_state = self.client.get("/state/analysis/latest", headers=headers)

        self.assertEqual(missing_source.status_code, 400)
        self.assertEqual(self_source.status_code, 400)
        self.assertEqual(saved_state.status_code, 200)
        self.assertEqual(loaded_state.status_code, 200)
        self.assertTrue(loaded_state.get_json()["payload"]["ready"])

    def test_upload_invalidates_cached_analysis_state(self):
        headers = self.auth_headers()
        first_upload = self.upload_csv(headers)
        first_dataset_id = first_upload.get_json()["dataset_id"]

        saved_state = self.client.post(
            "/state/analysis/latest",
            headers=headers,
            json={"chart": "old"},
        )
        loaded_state = self.client.get("/state/analysis/latest", headers=headers)
        second_upload = self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(b"new_feature,target\n10,0\n20,1\n30,0\n"), "new_dataset.csv")},
            content_type="multipart/form-data",
        )
        stale_state = self.client.get("/state/analysis/latest", headers=headers)

        self.assertEqual(saved_state.status_code, 200)
        self.assertEqual(loaded_state.status_code, 200)
        self.assertEqual(second_upload.status_code, 200)
        self.assertNotEqual(first_dataset_id, second_upload.get_json()["dataset_id"])
        self.assertEqual(stale_state.status_code, 404)

    def test_visual_analysis_routes_return_histogram_outlier_summary_and_matrix(self):
        headers = self.auth_headers()
        self.upload_csv(headers)

        histogram = self.client.post("/histogram", headers=headers, json={"column": "category", "bins": 2})
        outliers = self.client.post("/outliers", headers=headers, json={"column": "feature", "threshold": 1})
        matrix = self.client.post("/correlation/matrix", headers=headers, json={"method": "pearson"})

        self.assertEqual(histogram.status_code, 200)
        self.assertEqual(histogram.get_json()["kind"], "categorical")
        self.assertEqual(outliers.status_code, 200)
        self.assertIn("summary", outliers.get_json())
        self.assertEqual(matrix.status_code, 200)
        self.assertEqual(len(matrix.get_json()["columns"]), 2)

    def test_modeling_options_explain_classification_regression_and_exclusions(self):
        headers = self.auth_headers()
        csv_text = (
            "identifier,feature,target,price\n"
            + "\n".join(
                f"{index},{index * 10},{'a' if index % 2 else 'b'},{1000 + index * 125}"
                for index in range(25)
            )
        )
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_text.encode("utf-8")), "options.csv")},
            content_type="multipart/form-data",
        )
        self.client.post(
            "/metadata/column",
            headers=headers,
            json={"column": "identifier", "semantic_role": "identifier"},
        )

        response = self.client.get("/modeling/options?target=target", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        target_option = [item for item in payload["targets"] if item["column"] == "target"][0]
        price_option = [item for item in payload["targets"] if item["column"] == "price"][0]
        identifier_feature = [item for item in payload["feature_options"] if item["column"] == "identifier"][0]
        self.assertIn("classification", target_option["task_types"])
        self.assertIn("regression", price_option["task_types"])
        self.assertFalse(identifier_feature["selected"])

    def test_modeling_job_completes_and_report_includes_latest_model(self):
        headers = self.auth_headers()
        csv_text = (
            "feature,target,category\n"
            + "\n".join(
                f"{index},{index * 2},{'a' if index % 2 else 'b'}"
                for index in range(24)
            )
        )
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_text.encode("utf-8")), "modeling.csv")},
            content_type="multipart/form-data",
        )

        job_start = self.client.post(
            "/modeling/jobs",
            headers=headers,
            json={"target": "category", "task_type": "classification", "features": ["feature", "target"]},
        )
        self.assertEqual(job_start.status_code, 200)
        job_id = job_start.get_json()["job_id"]
        job_status = None
        for _ in range(40):
            job_status = self.client.get(f"/modeling/jobs/{job_id}", headers=headers)
            payload = job_status.get_json()
            if payload["status"] != "running":
                break
            time.sleep(0.05)
        report = self.client.get("/report/summary", headers=headers)

        self.assertEqual(job_status.status_code, 200)
        self.assertEqual(job_status.get_json()["status"], "done")
        self.assertEqual(report.status_code, 200)
        self.assertIsNotNone(report.get_json()["latest_model"])

    def test_target_correlation_job_completes_and_saves_state(self):
        headers = self.auth_headers()
        csv_text = (
            "target,signal,noise\n"
            + "\n".join(
                f"{index},{index * 2},{(index % 5) * 3}"
                for index in range(30)
            )
        )
        self.client.post(
            "/upload",
            headers=headers,
            data={"file": (io.BytesIO(csv_text.encode("utf-8")), "risk.csv")},
            content_type="multipart/form-data",
        )

        job_start = self.client.post(
            "/target-correlation/jobs",
            headers=headers,
            json={"target": "target", "method": "pearson"},
        )
        self.assertEqual(job_start.status_code, 200)
        job_id = job_start.get_json()["job_id"]
        job_status = None
        for _ in range(40):
            job_status = self.client.get(f"/target-correlation/jobs/{job_id}", headers=headers)
            payload = job_status.get_json()
            if payload["status"] != "running":
                break
            time.sleep(0.05)
        saved_state = self.client.get("/state/risk/latest", headers=headers)

        self.assertEqual(job_status.status_code, 200)
        self.assertEqual(job_status.get_json()["status"], "done")
        self.assertEqual(job_status.get_json()["result"]["items"][0]["feature"], "signal")
        self.assertEqual(saved_state.status_code, 200)
        self.assertEqual(saved_state.get_json()["payload"]["target"], "target")

    def test_missing_state_returns_404(self):
        headers = self.auth_headers()

        response = self.client.get("/state/analysis/missing", headers=headers)

        self.assertEqual(response.status_code, 404)

    def test_limit_rejects_invalid_values(self):
        headers = self.auth_headers()
        self.upload_csv(headers)

        text_limit = self.client.post("/limit", headers=headers, json={"limit": "abc"})
        negative_limit = self.client.post("/limit", headers=headers, json={"limit": -5})

        self.assertEqual(text_limit.status_code, 400)
        self.assertEqual(negative_limit.status_code, 400)

    def test_correlation_matrix_rejects_invalid_method_and_too_few_columns(self):
        headers = self.auth_headers()
        self.upload_csv(headers)

        bad_method = self.client.post("/correlation/matrix", headers=headers, json={"method": "kendall"})
        too_few = self.client.post(
            "/correlation/matrix",
            headers=headers,
            json={"method": "pearson", "columns": ["feature"]},
        )

        self.assertEqual(bad_method.status_code, 400)
        self.assertEqual(too_few.status_code, 400)

    def test_modeling_compare_rejects_empty_feature_list(self):
        headers = self.auth_headers()
        self.upload_csv(headers)

        response = self.client.post(
            "/modeling/compare",
            headers=headers,
            json={"target": "category", "task_type": "classification", "features": []},
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()

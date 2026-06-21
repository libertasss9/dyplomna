from datetime import datetime, timezone
from functools import wraps
from threading import Lock, Thread
from uuid import uuid4

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

from server.config import ALLOWED_ORIGINS, FLASK_DEBUG, MAX_UPLOAD_MB
from server.database.manager import (
    create_user,
    delete_analysis_states,
    delete_session,
    get_analysis_state,
    get_all_column_metadata,
    get_column_metadata,
    get_history,
    get_session_username,
    get_user,
    init_database,
    prune_column_metadata,
    save_analysis_state,
    save_history,
    save_column_metadata,
    save_session,
    validate_user,
)
from server.services.analysis_service import AnalysisService
from server.services.cleaning_service import (
    apply_cleaning_rules as _apply_cleaning_rules,
    build_cleaning_plan as _build_cleaning_plan,
    create_class_column as _create_class_column,
)
from server.services.data_service import DataService
from server.services.measurement_service import measure_operation as _measure_operation
from server.services.modeling_service import (
    build_modeling_options as _build_modeling_options,
    feature_options_for_target as _feature_options_for_target,
    infer_task_type as _infer_task_type,
    selected_feature_columns as _selected_feature_columns,
)
from server.services.profiling_service import infer_column_roles as _infer_column_roles
from server.services.report_service import (
    build_correlation_matrix as _build_correlation_matrix,
    build_summary_report as _compose_summary_report,
    metadata_coverage as _metadata_coverage,
    preview_records as _preview_records,
    workflow_summary as _workflow_summary,
)
from server.services.statistics_service import StatisticsService

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
CORS(app, origins=ALLOWED_ORIGINS)

# Dataset cache remains in memory for analysis performance.
datasets = {}
original_datasets = {}
dataset_ids = {}
sample_limits = {}
model_jobs = {}
model_jobs_lock = Lock()
risk_jobs = {}
risk_jobs_lock = Lock()
init_database()


def _current_dataset_id(username):
    return dataset_ids.get(username)


def _new_dataset_context(username):
    dataset_id = str(uuid4())
    dataset_ids[username] = dataset_id
    delete_analysis_states(username)
    with model_jobs_lock:
        for job_id in [key for key, job in model_jobs.items() if job.get("username") == username]:
            model_jobs.pop(job_id, None)
    with risk_jobs_lock:
        for job_id in [key for key, job in risk_jobs.items() if job.get("username") == username]:
            risk_jobs.pop(job_id, None)
    return dataset_id


def _reset_sample_limit(username):
    sample_limits.pop(username, None)


def _sample_info(username, df=None):
    current_df = df if df is not None else datasets.get(username)
    source_df = original_datasets.get(username, current_df)
    return DataService.sample_info(current_df, source_df, sample_limits.get(username))


def _with_dataset_context(username, payload):
    if isinstance(payload, dict):
        dataset_id = _current_dataset_id(username)
        if dataset_id:
            payload["dataset_id"] = dataset_id
    return payload


def _state_belongs_to_current_dataset(username, state):
    dataset_id = _current_dataset_id(username)
    if not dataset_id:
        return False
    payload = state.get("payload") if state else None
    return isinstance(payload, dict) and payload.get("dataset_id") == dataset_id


def _json_error(message, status_code=400):
    return jsonify({"error": message}), status_code


def _authorize():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.replace("Bearer ", "", 1)
    return get_session_username(token)


def _require_auth(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        username = _authorize()
        if not username:
            return _json_error("Unauthorized", 401)
        return handler(username, *args, **kwargs)

    return wrapped


def _get_user_dataframe(username):
    df = datasets.get(username)
    if df is None:
        return None, _json_error("Dataset not uploaded", 400)
    return df, None


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(_error):
    return _json_error(f"Uploaded file is larger than {MAX_UPLOAD_MB} MB", 413)


def _validate_column(df, column_name, numeric_only=False):
    if column_name not in df.columns:
        return False, f"Column '{column_name}' does not exist"
    if numeric_only and not pd.api.types.is_numeric_dtype(df[column_name]):
        return False, f"Column '{column_name}' must be numeric"
    return True, ""


def _store_history(username, action, payload):
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = _with_dataset_context(username, dict(payload or {}))
    save_history(str(uuid4()), username, action, payload, created_at)


def _metadata_payload(username, df):
    metadata = get_all_column_metadata(username)
    return {
        column: metadata[column]
        for column in df.columns
        if column in metadata
    }


def _current_dataset_history(username, limit=100):
    dataset_id = _current_dataset_id(username)
    items = get_history(username, limit=limit)
    if not dataset_id:
        return []
    return [
        item
        for item in items
        if isinstance(item.get("payload"), dict) and item["payload"].get("dataset_id") == dataset_id
    ]


def _current_analysis_states(username):
    result = {}
    for key in ("analysis/latest", "risk/latest", "modeling/latest", "report/latest"):
        state = get_analysis_state(username, key)
        if state and _state_belongs_to_current_dataset(username, state):
            result[key] = state["payload"]
    return result


def _modeling_options(username, df):
    profile = _infer_column_roles(df)
    metadata = _metadata_payload(username, df)
    return _build_modeling_options(df, profile, metadata)


def _build_summary_report(username, df):
    profile = _infer_column_roles(df)
    metadata = _metadata_payload(username, df)
    latest_model_state = get_analysis_state(username, "modeling/latest")
    if latest_model_state and not _state_belongs_to_current_dataset(username, latest_model_state):
        latest_model_state = None
    latest_model_payload = latest_model_state["payload"] if latest_model_state else None
    history_items = _current_dataset_history(username, limit=100)
    return _compose_summary_report(
        profile,
        metadata,
        latest_model_payload,
        history_items,
        _sample_info(username, df),
        _current_analysis_states(username),
    )


def _run_modeling_job(job_id, username, payload):
    job_dataset_id = payload.get("_dataset_id")

    def update(progress, step):
        with model_jobs_lock:
            if job_id in model_jobs:
                model_jobs[job_id]["progress"] = progress
                model_jobs[job_id]["step"] = step

    try:
        update(8, "Перевірка датасету та цільової колонки")
        df = datasets.get(username)
        if df is None:
            raise ValueError("Dataset not uploaded")
        if job_dataset_id and job_dataset_id != _current_dataset_id(username):
            raise ValueError("Dataset changed after the modeling job was started")

        target = str(payload.get("target", "")).strip()
        if not target:
            raise ValueError("Target is required")

        profile = _infer_column_roles(df)
        metadata = _metadata_payload(username, df)
        task_type = _infer_task_type(profile, target, payload.get("task_type"))

        update(25, "Формування списку ознак і перевірка витоку даних")
        selected_features, feature_options = _selected_feature_columns(
            df,
            profile,
            metadata,
            target,
            payload.get("features"),
        )

        update(45, "Обробка пропусків і кодування категоріальних колонок")
        with _measure_operation(
            "machine_learning.compare",
            df=df,
            job_id=job_id,
            target=target,
            task_type=task_type,
            features_count=len(selected_features),
        ):
            result = AnalysisService.compare_models(df, target, task_type, selected_features)
        if job_dataset_id and job_dataset_id != _current_dataset_id(username):
            raise ValueError("Dataset changed before modeling results were saved")
        result["dataset_id"] = job_dataset_id or _current_dataset_id(username)
        result["sample_info"] = _sample_info(username, df)
        result["feature_options"] = feature_options
        result["excluded_features"] = [
            item for item in feature_options if not item.get("selected") and item.get("column") != target
        ]

        update(92, "Збереження результатів моделювання")
        save_analysis_state(username, "modeling/latest", result)
        _store_history(
            username,
            "modeling-compare",
            {
                "target": target,
                "task_type": task_type,
                "features_count": len(selected_features),
            },
        )
        with model_jobs_lock:
            model_jobs[job_id].update(
                {
                    "status": "done",
                    "progress": 100,
                    "step": "Моделювання завершено",
                    "result": result,
                    "error": "",
                }
            )
    except Exception as exc:  # noqa: BLE001 - user-facing background job boundary.
        with model_jobs_lock:
            if job_id in model_jobs:
                model_jobs[job_id].update(
                    {
                        "status": "error",
                        "progress": 100,
                        "step": "Помилка моделювання",
                        "error": str(exc),
                    }
                )


def _run_risk_job(job_id, username, payload):
    job_dataset_id = payload.get("_dataset_id")

    def update(progress, step):
        with risk_jobs_lock:
            if job_id in risk_jobs:
                risk_jobs[job_id]["progress"] = progress
                risk_jobs[job_id]["step"] = step

    try:
        update(10, "Перевірка параметрів рейтингу")
        df = datasets.get(username)
        if df is None:
            raise ValueError("Dataset not uploaded")
        if job_dataset_id and job_dataset_id != _current_dataset_id(username):
            raise ValueError("Dataset changed after the ranking job was started")

        target = str(payload.get("target", "")).strip()
        method = str(payload.get("method", "pearson")).lower()
        if not target:
            raise ValueError("Target is required")
        if method not in {"pearson", "spearman"}:
            raise ValueError("Method must be pearson or spearman")

        numeric_count = len(df.select_dtypes(include="number").columns)
        update(35, f"Підготовка {max(0, numeric_count - 1)} числових ознак")
        update(65, f"Розрахунок {method} кореляцій")
        with _measure_operation(
            "patterns.ranking",
            df=df,
            job_id=job_id,
            method=method,
            target=target,
        ):
            result = AnalysisService.feature_correlation_with_target(df, target, method)
        if job_dataset_id and job_dataset_id != _current_dataset_id(username):
            raise ValueError("Dataset changed before ranking results were saved")
        result["input"] = {"target": target, "method": method}
        result["dataset_id"] = job_dataset_id or _current_dataset_id(username)
        result["sample_info"] = _sample_info(username, df)

        update(90, "Збереження рейтингу закономірностей")
        save_analysis_state(username, "risk/latest", result)
        _store_history(username, "target-correlation", {"target": target, "method": method})
        with risk_jobs_lock:
            risk_jobs[job_id].update(
                {
                    "status": "done",
                    "progress": 100,
                    "step": "Рейтинг закономірностей готовий",
                    "result": result,
                    "error": "",
                }
            )
    except Exception as exc:  # noqa: BLE001 - user-facing background job boundary.
        with risk_jobs_lock:
            if job_id in risk_jobs:
                risk_jobs[job_id].update(
                    {
                        "status": "error",
                        "progress": 100,
                        "step": "Помилка розрахунку рейтингу",
                        "error": str(exc),
                    }
                )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))

    if len(username) < 3:
        return _json_error("Username must have at least 3 characters")
    if len(password) < 6:
        return _json_error("Password must have at least 6 characters")
    if get_user(username):
        return _json_error("User already exists", 409)

    create_user(username, password)
    return jsonify({"message": "Registered successfully"})


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))

    if not validate_user(username, password):
        return _json_error("Invalid username or password", 401)

    token = str(uuid4())
    save_session(token, username)
    return jsonify({"token": token, "username": username})


@app.route("/auth/logout", methods=["POST"])
def logout():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return _json_error("Unauthorized", 401)
    token = auth_header.replace("Bearer ", "", 1)
    delete_session(token)
    return jsonify({"message": "Logged out"})


@app.route("/auth/me", methods=["GET"])
@_require_auth
def me(username):
    return jsonify({"username": username})


@app.route("/upload", methods=["POST"])
@_require_auth
def upload_file(username):
    if "file" not in request.files:
        return _json_error("No file provided")

    file = request.files["file"]
    if not file.filename.lower().endswith(".csv"):
        return _json_error("Only CSV files are supported")

    try:
        with _measure_operation("upload.csv_read", filename=file.filename, encoding="default"):
            df = pd.read_csv(file, low_memory=False)
    except UnicodeDecodeError:
        file.stream.seek(0)
        try:
            with _measure_operation("upload.csv_read", filename=file.filename, encoding="latin1"):
                df = pd.read_csv(file, low_memory=False, encoding="latin1")
        except Exception as exc:
            return _json_error(f"Failed to read CSV: {exc}")
    except Exception as exc:
        return _json_error(f"Failed to read CSV: {exc}")

    if df.empty:
        return _json_error("Uploaded file is empty")

    datasets[username] = df
    original_datasets[username] = df
    _reset_sample_limit(username)
    dataset_id = _new_dataset_context(username)
    prune_column_metadata(username, df.columns.tolist())
    with _measure_operation("dataset.profile", df=df, source="upload"):
        profile = _infer_column_roles(df)
    profile["dataset_id"] = dataset_id
    _store_history(
        username,
        "upload",
        {"rows": int(df.shape[0]), "columns_count": int(df.shape[1])},
    )
    return jsonify(
        {
            "message": "Dataset uploaded successfully",
            "columns": df.columns.tolist(),
            "numeric_columns": df.select_dtypes(include="number").columns.tolist(),
            "target_suggestions": profile["target_suggestions"],
            "target_profiles": profile["target_profiles"],
            "quality": profile["quality"],
            "quality_warnings": profile["quality_warnings"],
            "dataset_id": dataset_id,
            "sample_info": _sample_info(username, df),
            "shape": [int(df.shape[0]), int(df.shape[1])],
            "preview": _preview_records(df),
        }
    )


@app.route("/columns", methods=["GET"])
@_require_auth
def get_columns(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err
    profile = _infer_column_roles(df)
    profile["metadata"] = _metadata_payload(username, df)
    profile["dataset_id"] = _current_dataset_id(username)
    profile["sample_info"] = _sample_info(username, df)
    return jsonify(profile)


@app.route("/modeling/options", methods=["GET"])
@_require_auth
def modeling_options(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err
    options = _modeling_options(username, df)
    options["dataset_id"] = _current_dataset_id(username)
    options["sample_info"] = _sample_info(username, df)
    target = str(request.args.get("target", options["default_target"] or "")).strip()
    if target:
        options["feature_options"] = _feature_options_for_target(
            df,
            options["profile"],
            options["metadata"],
            target,
        )
    return jsonify(options)


@app.route("/dataset/profile", methods=["GET"])
@_require_auth
def dataset_profile(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    with _measure_operation("dataset.profile", df=df, source="profile_endpoint"):
        profile = _infer_column_roles(df)
        profile["dataset_id"] = _current_dataset_id(username)
        profile["sample_info"] = _sample_info(username, df)
        profile["memory_usage_mb"] = round(float(df.memory_usage(deep=True).sum()) / (1024 * 1024), 4)
        profile["metadata"] = _metadata_payload(username, df)
        profile["metadata_coverage"] = _metadata_coverage(profile["metadata"], profile["columns"])
    _store_history(
        username,
        "dataset-profile",
        {"rows": profile["rows_count"], "columns_count": profile["columns_count"]},
    )
    return jsonify(profile)


@app.route("/cleaning/plan", methods=["GET"])
@_require_auth
def cleaning_plan(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    with _measure_operation("data_quality.plan", df=df):
        plan = _build_cleaning_plan(df)
    plan["dataset_id"] = _current_dataset_id(username)
    plan["sample_info"] = _sample_info(username, df)
    plan["profile"]["dataset_id"] = _current_dataset_id(username)
    plan["profile"]["sample_info"] = plan["sample_info"]
    _store_history(username, "cleaning-plan", {"rows": int(df.shape[0]), "columns_count": int(df.shape[1])})
    return jsonify(plan)


@app.route("/cleaning/apply", methods=["POST"])
@_require_auth
def apply_cleaning(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    try:
        with _measure_operation("data_quality.cleaning_apply", df=df):
            cleaned, changes = _apply_cleaning_rules(df, payload)
    except ValueError as exc:
        return _json_error(str(exc))

    datasets[username] = cleaned
    original_datasets[username] = cleaned
    _reset_sample_limit(username)
    dataset_id = _new_dataset_context(username)
    prune_column_metadata(username, cleaned.columns.tolist())
    with _measure_operation("dataset.profile", df=cleaned, source="cleaning_apply"):
        profile = _infer_column_roles(cleaned)
    profile["dataset_id"] = dataset_id
    profile["sample_info"] = _sample_info(username, cleaned)
    _store_history(
        username,
        "cleaning-apply",
        {
            "rows": int(cleaned.shape[0]),
            "columns_count": int(cleaned.shape[1]),
            "changes_count": len(changes),
        },
    )
    return jsonify(
        {
            "message": "Cleaning rules applied",
            "shape": [int(cleaned.shape[0]), int(cleaned.shape[1])],
            "changes": changes,
            "profile": profile,
            "dataset_id": dataset_id,
            "sample_info": profile["sample_info"],
            "quality_warnings": profile["quality_warnings"],
            "preview": _preview_records(cleaned),
        }
    )


@app.route("/classes/create", methods=["POST"])
@_require_auth
def create_classes(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    try:
        updated, new_column, descriptions, distribution, unmatched_count = _create_class_column(df, payload)
    except ValueError as exc:
        return _json_error(str(exc))

    datasets[username] = updated
    original_datasets[username] = updated
    _reset_sample_limit(username)
    dataset_id = _new_dataset_context(username)
    profile = _infer_column_roles(updated)
    profile["dataset_id"] = dataset_id
    profile["sample_info"] = _sample_info(username, updated)
    save_column_metadata(
        username,
        new_column,
        "Класова колонка, створена користувачем за ручними правилами.",
        "target",
        descriptions,
        source_column=str(payload.get("source_column", "")).strip(),
    )
    _store_history(
        username,
        "class-create",
        {
            "source_column": str(payload.get("source_column", "")).strip(),
            "new_column": new_column,
            "mode": str(payload.get("mode", "ranges")).strip().lower(),
            "classes_count": len(distribution),
            "unmatched_count": unmatched_count,
        },
    )
    return jsonify(
        {
            "message": "Class column created",
            "column": new_column,
            "shape": [int(updated.shape[0]), int(updated.shape[1])],
            "class_descriptions": descriptions,
            "class_distribution": distribution,
            "unmatched_count": unmatched_count,
            "source_column": str(payload.get("source_column", "")).strip(),
            "profile": profile,
            "dataset_id": dataset_id,
            "sample_info": profile["sample_info"],
        }
    )


@app.route("/metadata", methods=["GET"])
@_require_auth
def metadata(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err
    return jsonify(
        {
            "columns": df.columns.tolist(),
            "metadata": _metadata_payload(username, df),
        }
    )


@app.route("/metadata/column", methods=["POST"])
@_require_auth
def save_metadata_column(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    column = str(data.get("column", "")).strip()
    if column not in df.columns:
        return _json_error(f"Column '{column}' does not exist")

    description = str(data.get("description", "")).strip()[:1500]
    semantic_role = str(data.get("semantic_role", "unspecified")).strip().lower()
    allowed_roles = {
        "unspecified",
        "feature",
        "target",
        "identifier",
        "ignore",
        "sensitive",
        "group",
    }
    if semantic_role not in allowed_roles:
        return _json_error("Unknown semantic role")

    class_descriptions = data.get("class_descriptions") or {}
    if not isinstance(class_descriptions, dict):
        return _json_error("Class descriptions must be an object")
    clean_classes = {
        str(key).strip()[:120]: str(value).strip()[:500]
        for key, value in class_descriptions.items()
        if str(key).strip() and str(value).strip()
    }
    source_column = str(data.get("source_column", "")).strip()
    if source_column and source_column not in df.columns:
        return _json_error(f"Source column '{source_column}' does not exist")
    if source_column and source_column == column:
        return _json_error("Source column must be different from the described column")

    save_column_metadata(username, column, description, semantic_role, clean_classes, source_column)
    _store_history(username, "metadata-column", {"column": column, "semantic_role": semantic_role})
    return jsonify({"metadata": get_column_metadata(username, column)})


@app.route("/workflow/status", methods=["GET"])
@_require_auth
def workflow_status(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err
    profile = _infer_column_roles(df)
    metadata = _metadata_payload(username, df)
    history_items = _current_dataset_history(username, limit=100)
    return jsonify(
        {
            "dataset_id": _current_dataset_id(username),
            "sample_info": _sample_info(username, df),
            "steps": _workflow_summary(
                profile,
                metadata,
                history_items,
                _current_analysis_states(username),
            ),
        }
    )


@app.route("/report/summary", methods=["GET"])
@_require_auth
def summary_report(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err
    report_state = {
        "dataset_id": _current_dataset_id(username),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    save_analysis_state(username, "report/latest", report_state)
    report = _build_summary_report(username, df)
    report["dataset_id"] = _current_dataset_id(username)
    report["sample_info"] = _sample_info(username, df)
    _store_history(username, "summary-report", {"sections": len(report)})
    return jsonify(report)


@app.route("/state/<path:state_key>", methods=["GET"])
@_require_auth
def get_state(username, state_key):
    state = get_analysis_state(username, state_key)
    if not state:
        return _json_error("State not found", 404)
    if not _state_belongs_to_current_dataset(username, state):
        return _json_error("State not found for current dataset", 404)
    return jsonify(state)


@app.route("/state/<path:state_key>", methods=["POST"])
@_require_auth
def save_state(username, state_key):
    payload = request.get_json(silent=True) or {}
    payload = _with_dataset_context(username, payload)
    save_analysis_state(username, state_key, payload)
    return jsonify({"message": "State saved"})


@app.route("/statistics", methods=["GET"])
@_require_auth
def statistics(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    with _measure_operation("statistics.basic", df=df):
        result = StatisticsService.basic_statistics(df)
    _store_history(username, "statistics", {"columns": len(result)})
    return jsonify(result)


@app.route("/correlation", methods=["POST"])
@_require_auth
def correlation(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    col_x = str(data.get("col_x", ""))
    col_y = str(data.get("col_y", ""))
    method = str(data.get("method", "pearson")).lower()

    if col_x == col_y:
        return _json_error("Columns must be different")
    is_valid, message = _validate_column(df, col_x, numeric_only=True)
    if not is_valid:
        return _json_error(message)
    is_valid, message = _validate_column(df, col_y, numeric_only=True)
    if not is_valid:
        return _json_error(message)

    try:
        with _measure_operation("correlation.pair", df=df, method=method, col_x=col_x, col_y=col_y):
            result = AnalysisService.correlation(df, col_x, col_y, method)
    except ValueError as exc:
        return _json_error(str(exc))
    _store_history(username, "correlation", {"col_x": col_x, "col_y": col_y, "method": method})
    return jsonify(result)


@app.route("/correlation/matrix", methods=["POST"])
@_require_auth
def correlation_matrix(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    method = str(data.get("method", "pearson")).lower()
    if method not in {"pearson", "spearman"}:
        return _json_error("Method must be pearson or spearman")
    columns = data.get("columns") or None
    try:
        with _measure_operation("correlation.matrix", df=df, method=method):
            result = _build_correlation_matrix(df, method, columns)
    except ValueError as exc:
        return _json_error(str(exc))
    _store_history(username, "correlation-matrix", {"method": method, "columns": len(result["columns"])})
    return jsonify(result)


@app.route("/regression", methods=["POST"])
@_require_auth
def regression(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    col_x = str(data.get("col_x", ""))
    col_y = str(data.get("col_y", ""))

    if col_x == col_y:
        return _json_error("Columns must be different")
    is_valid, message = _validate_column(df, col_x, numeric_only=True)
    if not is_valid:
        return _json_error(message)
    is_valid, message = _validate_column(df, col_y, numeric_only=True)
    if not is_valid:
        return _json_error(message)

    try:
        result = AnalysisService.linear_regression(df, col_x, col_y)
    except ValueError as exc:
        return _json_error(str(exc))
    _store_history(username, "regression", {"col_x": col_x, "col_y": col_y})
    return jsonify(result)


@app.route("/limit", methods=["POST"])
@_require_auth
def limit_rows(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    try:
        limit = DataService.parse_row_limit(data.get("limit"))
    except ValueError as exc:
        return _json_error(str(exc))

    source_df = original_datasets.get(username, df)
    new_df = DataService.apply_limit(source_df, limit)
    datasets[username] = new_df
    if limit is None:
        _reset_sample_limit(username)
    else:
        sample_limits[username] = limit
    dataset_id = _new_dataset_context(username)
    sample_info = _sample_info(username, new_df)
    _store_history(
        username,
        "limit",
        {
            "limit": limit,
            "current_rows": sample_info["current_rows"],
            "source_rows": sample_info["source_rows"],
        },
    )
    return jsonify(
        {
            "limit": limit,
            "dataset_id": dataset_id,
            "sample_info": sample_info,
            "shape": [int(new_df.shape[0]), int(new_df.shape[1])],
        }
    )


@app.route("/histogram", methods=["POST"])
@_require_auth
def histogram(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    column = str(data.get("column", ""))
    bins = int(data.get("bins", 10))
    if bins < 2:
        return _json_error("Bins must be at least 2")
    is_valid, message = _validate_column(df, column, numeric_only=False)
    if not is_valid:
        return _json_error(message)

    try:
        result = AnalysisService.histogram(df, column, bins)
    except ValueError as exc:
        return _json_error(str(exc))
    _store_history(username, "histogram", {"column": column, "bins": bins})
    return jsonify(result)


@app.route("/missing-values", methods=["GET"])
@_require_auth
def missing_values(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    result = AnalysisService.missing_values(df)
    _store_history(username, "missing-values", {"rows": result["rows"]})
    return jsonify(result)


@app.route("/target-correlation", methods=["POST"])
@_require_auth
def target_correlation(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    target = str(data.get("target", ""))
    method = str(data.get("method", "pearson")).lower()
    if method not in {"pearson", "spearman"}:
        return _json_error("Method must be pearson or spearman")

    try:
        with _measure_operation("patterns.ranking", df=df, method=method, target=target):
            result = AnalysisService.feature_correlation_with_target(df, target, method)
    except ValueError as exc:
        return _json_error(str(exc))
    result["input"] = {"target": target, "method": method}
    result["dataset_id"] = _current_dataset_id(username)
    result["sample_info"] = _sample_info(username, df)
    save_analysis_state(username, "risk/latest", result)
    _store_history(username, "target-correlation", {"target": target, "method": method})
    return jsonify(result)


@app.route("/target-correlation/jobs", methods=["POST"])
@_require_auth
def start_target_correlation_job(username):
    payload = request.get_json(silent=True) or {}
    payload["_dataset_id"] = _current_dataset_id(username)
    job_id = str(uuid4())
    with risk_jobs_lock:
        risk_jobs[job_id] = {
            "id": job_id,
            "username": username,
            "status": "running",
            "progress": 1,
            "step": "Задачу рейтингу закономірностей поставлено в чергу",
            "result": None,
            "error": "",
        }
    worker = Thread(target=_run_risk_job, args=(job_id, username, payload), daemon=True)
    worker.start()
    return jsonify({"job_id": job_id, "status": "running"})


@app.route("/target-correlation/jobs/<job_id>", methods=["GET"])
@_require_auth
def get_target_correlation_job(username, job_id):
    with risk_jobs_lock:
        job = risk_jobs.get(job_id)
        if not job or job["username"] != username:
            return _json_error("Target correlation job not found", 404)
        return jsonify(
            {
                "id": job["id"],
                "status": job["status"],
                "progress": job["progress"],
                "step": job["step"],
                "result": job.get("result"),
                "error": job.get("error", ""),
            }
        )


@app.route("/modeling/compare", methods=["POST"])
@_require_auth
def compare_models(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    target = str(data.get("target", ""))
    if not target:
        return _json_error("Target is required")

    try:
        profile = _infer_column_roles(df)
        metadata = _metadata_payload(username, df)
        task_type = _infer_task_type(profile, target, data.get("task_type"))
        selected_features, feature_options = _selected_feature_columns(
            df,
            profile,
            metadata,
            target,
            data.get("features"),
        )
        with _measure_operation(
            "machine_learning.compare",
            df=df,
            target=target,
            task_type=task_type,
            features_count=len(selected_features),
        ):
            result = AnalysisService.compare_models(df, target, task_type, selected_features)
    except ValueError as exc:
        return _json_error(str(exc))
    result["dataset_id"] = _current_dataset_id(username)
    result["sample_info"] = _sample_info(username, df)
    result["feature_options"] = feature_options
    result["excluded_features"] = [
        item for item in feature_options if not item.get("selected") and item.get("column") != target
    ]
    save_analysis_state(username, "modeling/latest", result)
    _store_history(
        username,
        "modeling-compare",
        {"target": target, "task_type": result["task_type"], "features_count": len(selected_features)},
    )
    return jsonify(result)


@app.route("/modeling/jobs", methods=["POST"])
@_require_auth
def start_modeling_job(username):
    payload = request.get_json(silent=True) or {}
    payload["_dataset_id"] = _current_dataset_id(username)
    job_id = str(uuid4())
    with model_jobs_lock:
        model_jobs[job_id] = {
            "id": job_id,
            "username": username,
            "status": "running",
            "progress": 1,
            "step": "Задачу моделювання поставлено в чергу",
            "result": None,
            "error": "",
        }
    worker = Thread(target=_run_modeling_job, args=(job_id, username, payload), daemon=True)
    worker.start()
    return jsonify({"job_id": job_id, "status": "running"})


@app.route("/modeling/jobs/<job_id>", methods=["GET"])
@_require_auth
def get_modeling_job(username, job_id):
    with model_jobs_lock:
        job = model_jobs.get(job_id)
        if not job or job["username"] != username:
            return _json_error("Modeling job not found", 404)
        return jsonify(
            {
                "id": job["id"],
                "status": job["status"],
                "progress": job["progress"],
                "step": job["step"],
                "result": job.get("result"),
                "error": job.get("error", ""),
            }
        )


@app.route("/outliers", methods=["POST"])
@_require_auth
def outliers(username):
    df, err = _get_user_dataframe(username)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    column = str(data.get("column", ""))
    threshold = float(data.get("threshold", 3))
    if threshold <= 0:
        return _json_error("Threshold must be greater than 0")

    is_valid, message = _validate_column(df, column, numeric_only=True)
    if not is_valid:
        return _json_error(message)

    try:
        result = AnalysisService.detect_outliers(df, column, threshold)
    except ValueError as exc:
        return _json_error(str(exc))
    _store_history(username, "outliers", {"column": column, "threshold": threshold})
    return jsonify(result)


@app.route("/history", methods=["GET"])
@_require_auth
def history(username):
    return jsonify({"items": get_history(username, limit=100)})


if __name__ == "__main__":
    app.run(debug=FLASK_DEBUG)

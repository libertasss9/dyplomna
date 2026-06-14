import pandas as pd

from server.services.measurement_service import measure_operation


def _is_integer_like(series):
    if pd.api.types.is_integer_dtype(series):
        return True
    if not pd.api.types.is_numeric_dtype(series):
        return False
    values = pd.to_numeric(series.dropna(), errors="coerce").dropna()
    if values.empty:
        return False
    return bool((values % 1 == 0).all())


def _target_profile(df, column, rows_count):
    series = df[column].dropna()
    counts = series.value_counts().head(20)
    total = int(series.shape[0])
    items = [
        {
            "value": str(value),
            "count": int(count),
            "percent": round((int(count) / total) * 100, 4) if total else 0.0,
        }
        for value, count in counts.items()
    ]
    min_count = int(counts.min()) if not counts.empty else 0
    max_count = int(counts.max()) if not counts.empty else 0
    imbalance_ratio = round(max_count / min_count, 4) if min_count else 0.0
    return {
        "column": column,
        "non_missing_rows": total,
        "classes_count": int(df[column].nunique(dropna=True)),
        "items": items,
        "imbalance_ratio": imbalance_ratio,
        "coverage_percent": round((total / rows_count) * 100, 4) if rows_count else 0.0,
    }


def high_cardinality_text_columns(profile):
    return [
        item["name"]
        for item in profile["column_profiles"]
        if item["role"] == "text" and item["unique_count"] > max(50, profile["rows_count"] * 0.2)
    ]


def build_quality_warnings(profile):
    warnings = []
    quality = profile["quality"]

    if quality["missing_total"] > 0:
        level = "warning" if quality["missing_percent"] >= 5 else "info"
        warnings.append(
            {
                "level": level,
                "title": "Є пропущені значення",
                "message": (
                    f"У наборі даних пропущено {quality['missing_total']} клітинок "
                    f"({quality['missing_percent']}%). Перед моделюванням варто перевірити "
                    "причину пропусків і спосіб їх обробки."
                ),
            }
        )

    if quality["duplicate_rows"] > 0:
        level = "warning" if quality["duplicate_percent"] >= 2 else "info"
        warnings.append(
            {
                "level": level,
                "title": "Виявлено дублікати рядків",
                "message": (
                    f"Знайдено {quality['duplicate_rows']} повних дублікатів "
                    f"({quality['duplicate_percent']}%). Їх варто переглянути, щоб не "
                    "спотворити статистику та навчання моделей."
                ),
            }
        )

    if profile["constant_columns"]:
        warnings.append(
            {
                "level": "warning",
                "title": "Є константні колонки",
                "message": (
                    "Колонки без варіативності не допомагають знаходити закономірності "
                    "і можуть бути вилучені з моделювання."
                ),
                "columns": profile["constant_columns"][:10],
            }
        )

    if profile["categorical_encoded_columns"]:
        warnings.append(
            {
                "level": "info",
                "title": "Є закодовані категоріальні ознаки",
                "message": (
                    "Числові коди можуть означати класи або категорії. Для коректної "
                    "інтерпретації бажано описати їх у словнику колонок."
                ),
                "columns": profile["categorical_encoded_columns"][:10],
            }
        )

    high_cardinality = high_cardinality_text_columns(profile)
    if high_cardinality:
        warnings.append(
            {
                "level": "info",
                "title": "Є текстові або ідентифікаційні колонки з високою унікальністю",
                "message": (
                    "Такі поля часто є ідентифікаторами або довільним текстом. Перед "
                    "моделюванням варто позначити їх роль у словнику колонок."
                ),
                "columns": high_cardinality[:10],
            }
        )

    if not profile["target_suggestions"]:
        warnings.append(
            {
                "level": "warning",
                "title": "Цільову ознаку не визначено автоматично",
                "message": (
                    "Система не знайшла очевидної бінарної або категоріальної цілі. "
                    "Оберіть ціль вручну або уточніть ролі колонок у словнику."
                ),
            }
        )

    imbalanced_targets = [
        item
        for item in profile.get("target_profiles", [])
        if item["classes_count"] > 1 and item["imbalance_ratio"] >= 5
    ]
    if imbalanced_targets:
        warnings.append(
            {
                "level": "warning",
                "title": "Можливий дисбаланс класів",
                "message": (
                    "Для частини потенційних цільових колонок один клас суттєво переважає. "
                    "У такому випадку accuracy може бути оманливою, тому слід дивитися "
                    "balanced accuracy, macro F1 і матрицю помилок."
                ),
                "columns": [item["column"] for item in imbalanced_targets[:10]],
            }
        )

    if not warnings:
        warnings.append(
            {
                "level": "ok",
                "title": "Критичних проблем якості не виявлено",
                "message": "Базовий профіль даних не показав пропусків, дублікатів або константних колонок.",
            }
        )

    return warnings


def infer_column_roles(df):
    rows_count = int(len(df.index))
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    binary_columns = []
    categorical_encoded_columns = []
    continuous_columns = []
    categorical_columns = []
    text_columns = []
    constant_columns = []
    column_profiles = []

    for column in df.columns:
        series = df[column]
        missing_count = int(series.isna().sum())
        unique_count = int(series.nunique(dropna=True))
        is_numeric = column in numeric_columns
        role = "continuous" if is_numeric else "text"

        if unique_count <= 1:
            role = "constant"
            constant_columns.append(column)
        elif is_numeric:
            values = pd.to_numeric(series.dropna(), errors="coerce").dropna().unique().tolist()
            if unique_count <= 2 and set(values).issubset({0, 1, 0.0, 1.0}):
                role = "binary"
                binary_columns.append(column)
            elif unique_count <= 15 and _is_integer_like(series):
                role = "categorical_encoded"
                categorical_encoded_columns.append(column)
            else:
                continuous_columns.append(column)
        elif unique_count <= max(20, int(rows_count * 0.05)):
            role = "categorical"
            categorical_columns.append(column)
        else:
            text_columns.append(column)

        column_profiles.append(
            {
                "name": column,
                "dtype": str(series.dtype),
                "role": role,
                "missing_count": missing_count,
                "missing_percent": round((missing_count / rows_count) * 100, 4) if rows_count else 0.0,
                "unique_count": unique_count,
            }
        )

    max_target_classes = min(20, max(3, rows_count // 5 if rows_count else 3))
    target_suggestions = [
        profile["name"]
        for profile in sorted(
            column_profiles,
            key=lambda item: (
                0
                if item["role"] == "binary"
                else 1
                if item["role"] in {"categorical_encoded", "categorical"}
                else 2,
                item["unique_count"],
                item["name"].lower(),
            ),
        )
        if 2 <= profile["unique_count"] <= max_target_classes
        and profile["role"] in {"binary", "categorical_encoded", "categorical"}
    ]

    missing_total = int(df.isna().sum().sum())
    duplicate_rows = int(df.duplicated().sum())
    total_cells = max(rows_count * max(len(df.columns), 1), 1)
    missing_percent = round((missing_total / total_cells) * 100, 4)
    duplicate_percent = round((duplicate_rows / rows_count) * 100, 4) if rows_count else 0.0
    target_profiles = [_target_profile(df, column, rows_count) for column in target_suggestions[:10]]

    profile = {
        "rows_count": rows_count,
        "columns_count": int(len(df.columns)),
        "columns": df.columns.tolist(),
        "numeric_columns": numeric_columns,
        "binary_columns": binary_columns,
        "categorical_encoded_columns": categorical_encoded_columns,
        "categorical_columns": categorical_columns,
        "continuous_columns": continuous_columns,
        "text_columns": text_columns,
        "constant_columns": constant_columns,
        "target_suggestions": target_suggestions,
        "target_profiles": target_profiles,
        "column_profiles": column_profiles,
        "quality": {
            "missing_total": missing_total,
            "missing_percent": missing_percent,
            "duplicate_rows": duplicate_rows,
            "duplicate_percent": duplicate_percent,
        },
    }
    with measure_operation(
        "data_quality.warnings",
        rows_count=rows_count,
        columns_count=len(df.columns),
    ):
        profile["quality_warnings"] = build_quality_warnings(profile)
    return profile


def profile_by_column(profile):
    return {item["name"]: item for item in profile["column_profiles"]}


def column_task_support(column_profile):
    role = column_profile["role"]
    unique_count = column_profile["unique_count"]
    is_numeric = role in {"continuous", "binary", "categorical_encoded"}
    supports_classification = role in {"binary", "categorical", "categorical_encoded"} and 2 <= unique_count <= 20
    supports_regression = role == "continuous" and unique_count >= 5
    return supports_classification, supports_regression, is_numeric

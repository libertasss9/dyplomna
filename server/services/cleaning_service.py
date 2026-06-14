import pandas as pd

from server.services.profiling_service import (
    high_cardinality_text_columns,
    infer_column_roles,
)


def _zero_candidates(df, profile):
    binary_columns = set(profile["binary_columns"])
    candidates = []
    rows_count = max(int(df.shape[0]), 1)
    for column in profile["numeric_columns"]:
        if column in binary_columns:
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        zero_count = int((values == 0).sum())
        if zero_count:
            candidates.append(
                {
                    "column": column,
                    "zero_count": zero_count,
                    "zero_percent": round((zero_count / rows_count) * 100, 4),
                }
            )
    candidates.sort(key=lambda item: item["zero_count"], reverse=True)
    return candidates


def _numeric_class_sources(df, profile):
    sources = []
    for column in profile["numeric_columns"]:
        unique_count = int(pd.to_numeric(df[column], errors="coerce").dropna().nunique())
        if unique_count >= 5:
            sources.append({"column": column, "unique_count": unique_count})
    return sources


def _manual_class_sources(df, profile):
    sources = []
    profiles_by_name = {item["name"]: item for item in profile["column_profiles"]}
    for column in profile["columns"]:
        column_profile = profiles_by_name[column]
        if column_profile["unique_count"] < 2:
            continue

        series = df[column]
        top_values = [
            {"value": str(value), "count": int(count)}
            for value, count in series.dropna().astype(str).value_counts().head(12).items()
        ]
        item = {
            "column": column,
            "dtype": column_profile["dtype"],
            "role": column_profile["role"],
            "unique_count": column_profile["unique_count"],
            "missing_count": column_profile["missing_count"],
            "top_values": top_values,
            "is_numeric": column in profile["numeric_columns"],
        }

        if item["is_numeric"]:
            values = pd.to_numeric(series, errors="coerce").dropna()
            if not values.empty:
                quantiles = values.quantile([0.25, 0.5, 0.75]).to_dict()
                item.update(
                    {
                        "min": float(values.min()),
                        "max": float(values.max()),
                        "q25": float(quantiles.get(0.25)),
                        "median": float(quantiles.get(0.5)),
                        "q75": float(quantiles.get(0.75)),
                    }
                )
        sources.append(item)
    return sources


def _cleaning_recommendations(profile, zero_candidates):
    recommendations = []
    quality = profile["quality"]

    if quality["missing_total"]:
        recommendations.append(
            {
                "level": "warning",
                "title": "Є пропущені значення",
                "message": (
                    "Перед моделюванням варто обрати стратегію: видалити неповні рядки або "
                    "заповнити числові колонки медіаною, а категоріальні - найчастішим значенням."
                ),
            }
        )
    if quality["duplicate_rows"]:
        recommendations.append(
            {
                "level": "warning",
                "title": "Є дублікати рядків",
                "message": "Повні дублікати можуть спотворювати статистику, тому їх бажано видалити.",
            }
        )
    if profile["constant_columns"]:
        recommendations.append(
            {
                "level": "warning",
                "title": "Є константні колонки",
                "message": "Колонки без варіативності не допомагають знаходити закономірності.",
                "columns": profile["constant_columns"][:10],
            }
        )
    high_cardinality = high_cardinality_text_columns(profile)
    if high_cardinality:
        recommendations.append(
            {
                "level": "info",
                "title": "Є текстові колонки з високою унікальністю",
                "message": (
                    "Такі поля часто є ідентифікаторами або довільним текстом. Їх варто виключити "
                    "з моделювання або залишити лише для описового аналізу."
                ),
                "columns": high_cardinality[:10],
            }
        )
    if zero_candidates:
        recommendations.append(
            {
                "level": "info",
                "title": "Є нулі в числових колонках",
                "message": (
                    "Нуль може бути коректним значенням або прихованим пропуском. Позначайте нулі "
                    "як пропуски тільки для колонок, де це справді відповідає змісту даних."
                ),
                "columns": [item["column"] for item in zero_candidates[:10]],
            }
        )
    if not profile["target_suggestions"]:
        recommendations.append(
            {
                "level": "warning",
                "title": "Класову колонку не знайдено автоматично",
                "message": (
                    "Для класифікаційного моделювання можна вручну обрати категоріальну ціль "
                    "або створити технічні класи з числової колонки."
                ),
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "level": "ok",
                "title": "Дані готові до базового аналізу",
                "message": "Критичних проблем якості не виявлено, але метадані колонок усе одно варто уточнити.",
            }
        )
    return recommendations


def build_cleaning_plan(df):
    profile = infer_column_roles(df)
    zero_items = _zero_candidates(df, profile)
    high_cardinality = high_cardinality_text_columns(profile)
    return {
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "profile": profile,
        "summary": {
            "rows_count": profile["rows_count"],
            "columns_count": profile["columns_count"],
            "missing_total": profile["quality"]["missing_total"],
            "duplicate_rows": profile["quality"]["duplicate_rows"],
            "constant_columns_count": len(profile["constant_columns"]),
            "high_cardinality_text_count": len(high_cardinality),
            "zero_candidate_columns_count": len(zero_items),
        },
        "recommendations": _cleaning_recommendations(profile, zero_items),
        "zero_candidates": zero_items,
        "high_cardinality_text_columns": high_cardinality,
        "constant_columns": profile["constant_columns"],
        "numeric_class_sources": _numeric_class_sources(df, profile),
        "class_source_columns": _manual_class_sources(df, profile),
    }


def _mode_value(series):
    mode = series.dropna().mode()
    if mode.empty:
        return None
    return mode.iloc[0]


def apply_cleaning_rules(df, payload):
    cleaned = df.copy()
    changes = []

    zero_columns = payload.get("zero_as_missing_columns") or []
    if not isinstance(zero_columns, list):
        raise ValueError("zero_as_missing_columns must be a list")
    for column in zero_columns:
        if column not in cleaned.columns:
            continue
        if not pd.api.types.is_numeric_dtype(cleaned[column]):
            continue
        zero_count = int((pd.to_numeric(cleaned[column], errors="coerce") == 0).sum())
        if zero_count:
            cleaned[column] = cleaned[column].mask(cleaned[column] == 0)
            changes.append(f"У колонці {column} позначено як пропуски {zero_count} нульових значень.")

    drop_columns = payload.get("drop_columns") or []
    if not isinstance(drop_columns, list):
        raise ValueError("drop_columns must be a list")
    columns_to_drop = [column for column in drop_columns if column in cleaned.columns]

    if payload.get("drop_constant_columns"):
        constants = [column for column in cleaned.columns if cleaned[column].nunique(dropna=True) <= 1]
        columns_to_drop.extend(constants)

    if payload.get("drop_high_cardinality_text"):
        profile = infer_column_roles(cleaned)
        columns_to_drop.extend(high_cardinality_text_columns(profile))

    unique_drop_columns = []
    for column in columns_to_drop:
        if column not in unique_drop_columns:
            unique_drop_columns.append(column)
    if unique_drop_columns:
        cleaned = cleaned.drop(columns=unique_drop_columns)
        changes.append(f"Видалено колонки: {', '.join(unique_drop_columns)}.")

    if payload.get("drop_duplicate_rows"):
        before = int(cleaned.shape[0])
        cleaned = cleaned.drop_duplicates()
        removed = before - int(cleaned.shape[0])
        if removed:
            changes.append(f"Видалено {removed} повних дублікатів рядків.")

    missing_strategy = str(payload.get("missing_strategy", "none")).strip().lower()
    if missing_strategy == "drop_rows":
        before = int(cleaned.shape[0])
        cleaned = cleaned.dropna()
        removed = before - int(cleaned.shape[0])
        if removed:
            changes.append(f"Видалено {removed} рядків із пропущеними значеннями.")
    elif missing_strategy in {"smart_fill", "fill_median", "fill_mean"}:
        for column in cleaned.columns:
            if not cleaned[column].isna().any():
                continue
            if pd.api.types.is_numeric_dtype(cleaned[column]):
                values = pd.to_numeric(cleaned[column], errors="coerce")
                fill_value = values.mean() if missing_strategy == "fill_mean" else values.median()
            else:
                fill_value = _mode_value(cleaned[column])
            if fill_value is not None and not pd.isna(fill_value):
                missing_count = int(cleaned[column].isna().sum())
                cleaned[column] = cleaned[column].fillna(fill_value)
                changes.append(f"У колонці {column} заповнено {missing_count} пропусків.")
    elif missing_strategy != "none":
        raise ValueError("Unknown missing value strategy")

    if cleaned.empty:
        raise ValueError("Cleaning removed all rows. Choose a softer cleaning strategy")
    if len(cleaned.columns) == 0:
        raise ValueError("Cleaning removed all columns. Keep at least one column")
    if not changes:
        changes.append("Дані не змінено: вибрані правила не знайшли застосовних проблем.")
    return cleaned, changes


def _unique_column_name(df, preferred):
    base = str(preferred or "").strip() or "generated_class"
    candidate = base
    index = 2
    while candidate in df.columns:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def create_class_column(df, payload):
    source_column = str(payload.get("source_column", "")).strip()
    if source_column not in df.columns:
        raise ValueError("Source column does not exist")

    mode = str(payload.get("mode", "ranges")).strip().lower()
    rules = payload.get("rules") or []
    if mode not in {"ranges", "values"}:
        raise ValueError("Class creation mode must be ranges or values")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Class rules are required")
    if len(rules) > 30:
        raise ValueError("Too many class rules. Use up to 30 rules")

    new_column = _unique_column_name(df, payload.get("new_column") or f"{source_column}_class")
    result = df.copy()
    class_values = pd.Series(pd.NA, index=result.index, dtype="string")
    descriptions = {}

    if mode == "ranges":
        if not pd.api.types.is_numeric_dtype(result[source_column]):
            raise ValueError("Range rules require a numeric source column")
        source_values = pd.to_numeric(result[source_column], errors="coerce")
        for rule in rules:
            code = str(rule.get("code", "")).strip()
            if not code:
                raise ValueError("Each class rule must have a code")
            min_value = rule.get("min")
            max_value = rule.get("max")
            if min_value in ("", None) and max_value in ("", None):
                raise ValueError("Range rule must have at least min or max value")
            try:
                min_number = float(min_value) if min_value not in ("", None) else None
                max_number = float(max_value) if max_value not in ("", None) else None
            except (TypeError, ValueError) as exc:
                raise ValueError("Range boundaries must be numeric") from exc
            if min_number is not None and max_number is not None and min_number > max_number:
                raise ValueError("Range min value cannot be greater than max value")

            mask = source_values.notna()
            if min_number is not None:
                mask &= source_values >= min_number
            if max_number is not None:
                mask &= source_values <= max_number
            class_values.loc[mask] = code
            label = str(rule.get("label", "")).strip()
            fallback = (
                f"{'-∞' if min_number is None else min_number} - "
                f"{'∞' if max_number is None else max_number}"
            )
            descriptions[code] = label or fallback
    else:
        source_series = result[source_column]
        source_values = source_series.astype(str).str.strip()
        for rule in rules:
            code = str(rule.get("code", "")).strip()
            if not code:
                raise ValueError("Each class rule must have a code")
            values = [
                str(value).strip()
                for value in rule.get("values", [])
                if str(value).strip()
            ]
            if not values:
                raise ValueError("Value rule must contain at least one source value")
            mask = source_series.notna() & source_values.isin(values)
            class_values.loc[mask] = code
            label = str(rule.get("label", "")).strip()
            descriptions[code] = label or ", ".join(values[:5])

    assigned = class_values.dropna()
    if assigned.empty:
        raise ValueError("Class rules did not match any rows")
    if assigned.nunique(dropna=True) < 2:
        raise ValueError("Class rules must produce at least two classes")

    result[new_column] = class_values
    distribution = {
        str(label): int(count)
        for label, count in result[new_column].value_counts(dropna=True).sort_index().items()
    }
    unmatched_count = int(result[new_column].isna().sum())
    return result, new_column, descriptions, distribution, unmatched_count

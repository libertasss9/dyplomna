from server.services.profiling_service import (
    column_task_support,
    high_cardinality_text_columns,
    profile_by_column,
)


def source_column_for_target(metadata, target):
    source = metadata.get(target, {}).get("source_column", "")
    return source if source else ""


def target_option_explanation(column_profile, metadata):
    column = column_profile["name"]
    user_role = metadata.get(column, {}).get("semantic_role", "unspecified")
    supports_classification, supports_regression, _ = column_task_support(column_profile)
    task_types = []
    reasons = []

    if user_role in {"identifier", "ignore", "sensitive"}:
        return {
            "column": column,
            "task_types": [],
            "recommended": False,
            "reason": f"Колонку позначено у словнику як '{user_role}', тому вона не пропонується як ціль.",
        }

    if supports_classification:
        task_types.append("classification")
        reasons.append("має обмежену кількість класів")
    if supports_regression:
        task_types.append("regression")
        reasons.append("має неперервні числові значення")

    if not task_types:
        if column_profile["role"] == "text":
            reason = "текстова колонка має багато унікальних значень або не є класовою ціллю"
        elif column_profile["role"] == "constant":
            reason = "колонка має одне значення і не може бути ціллю"
        elif column_profile["role"] == "continuous":
            reason = (
                "числова колонка не підходить для класифікації; "
                "для неї варто обрати режим регресії або створити класи"
            )
        else:
            reason = "колонка не відповідає критеріям цільової ознаки"
        return {
            "column": column,
            "task_types": [],
            "recommended": False,
            "reason": reason,
        }

    return {
        "column": column,
        "task_types": task_types,
        "recommended": user_role == "target" or bool(task_types),
        "reason": "Колонка пропонується, оскільки " + " і ".join(reasons) + ".",
    }


def feature_options_for_target(df, profile, metadata, target):
    source_column = source_column_for_target(metadata, target)
    high_cardinality = set(high_cardinality_text_columns(profile))
    profile_map = profile_by_column(profile)
    options = []

    for column in profile["columns"]:
        if column == target:
            options.append(
                {
                    "column": column,
                    "selected": False,
                    "locked": True,
                    "reason": "Цільова колонка не може бути ознакою.",
                }
            )
            continue

        role = profile_map[column]["role"]
        user_role = metadata.get(column, {}).get("semantic_role", "unspecified")
        selected = True
        reason = "Ознака буде використана у моделюванні."

        if source_column and column == source_column:
            selected = False
            reason = f"Колонка є джерелом для створеної цілі {target}, тому її виключено для запобігання витоку даних."
        elif user_role in {"identifier", "ignore", "sensitive"}:
            selected = False
            reason = f"Колонку позначено у словнику як '{user_role}'."
        elif role == "constant":
            selected = False
            reason = "Константна колонка не має корисної варіативності."
        elif column in high_cardinality:
            selected = False
            reason = "Текстова колонка має занадто багато унікальних значень."

        options.append(
            {
                "column": column,
                "selected": selected,
                "locked": False,
                "role": role,
                "semantic_role": user_role,
                "reason": reason,
            }
        )
    return options


def build_modeling_options(df, profile, metadata):
    profile_map = profile_by_column(profile)
    targets = [
        target_option_explanation(profile_map[column], metadata)
        for column in profile["columns"]
    ]
    suggested_targets = [item for item in targets if item["task_types"]]
    default_target = suggested_targets[0]["column"] if suggested_targets else ""
    return {
        "targets": targets,
        "suggested_targets": suggested_targets,
        "default_target": default_target,
        "feature_options": feature_options_for_target(df, profile, metadata, default_target) if default_target else [],
        "metadata": metadata,
        "profile": profile,
    }


def selected_feature_columns(df, profile, metadata, target, requested_features):
    options = feature_options_for_target(df, profile, metadata, target)
    allowed = {item["column"] for item in options if not item.get("locked")}
    default_selected = [item["column"] for item in options if item.get("selected") and item["column"] in allowed]
    if requested_features is None:
        return default_selected, options
    if not isinstance(requested_features, list):
        raise ValueError("Features must be a list")
    selected = []
    for column in requested_features:
        column = str(column).strip()
        if column in allowed and column not in selected:
            selected.append(column)
    if not selected:
        raise ValueError("Choose at least one feature column")
    return selected, options


def infer_task_type(profile, target, requested_task):
    requested_task = str(requested_task or "auto").lower()
    if requested_task in {"classification", "regression"}:
        return requested_task
    profile_map = profile_by_column(profile)
    if target not in profile_map:
        raise ValueError("Target column does not exist")
    supports_classification, supports_regression, _ = column_task_support(profile_map[target])
    if supports_classification:
        return "classification"
    if supports_regression:
        return "regression"
    raise ValueError("Selected target is not suitable for classification or regression")

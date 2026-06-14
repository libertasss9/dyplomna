import pandas as pd


def metadata_coverage(metadata, columns):
    meaningful = [
        column
        for column in columns
        if metadata.get(column, {}).get("description")
        or metadata.get(column, {}).get("semantic_role") not in {None, "", "unspecified"}
        or metadata.get(column, {}).get("class_descriptions")
    ]
    total = len(columns)
    return {
        "documented_columns": len(meaningful),
        "columns_count": total,
        "percent": round((len(meaningful) / total) * 100, 4) if total else 0.0,
    }


def preview_records(df, limit=10):
    preview = df.head(limit).astype(object)
    preview = preview.where(pd.notna(preview), None)
    return preview.to_dict(orient="records")


def workflow_summary(profile, metadata, history_items):
    actions = {item["action"] for item in history_items}
    coverage = metadata_coverage(metadata, profile["columns"])
    quality_done = actions.intersection({"cleaning-apply", "class-create"})
    exploration_done = actions.intersection(
        {"statistics", "histogram", "correlation", "regression", "outliers", "target-correlation"}
    )
    return [
        {
            "step": "Набір даних прийнято",
            "status": "done",
            "detail": f"{profile['rows_count']} рядків, {profile['columns_count']} колонок",
        },
        {
            "step": "Якість даних перевірено",
            "status": "done" if quality_done else "pending",
            "detail": (
                "Правила очищення або створення класів уже застосовувалися"
                if quality_done
                else "Перевірте пропуски, дублікати, нулі та потребу у класовій колонці"
            ),
        },
        {
            "step": "Зміст колонок описано",
            "status": "done",
            "detail": (
                f"{len(profile['quality_warnings'])} повідомлень якості; "
                f"описано {coverage['documented_columns']} з {coverage['columns_count']} колонок"
            ),
        },
        {
            "step": "Закономірності досліджено",
            "status": "done" if exploration_done else "pending",
            "detail": (
                "Є статистика, розподіли, викиди, кореляції або рейтинг ознак"
                if exploration_done
                else "Побудуйте розподіли, heatmap кореляцій, перевірку викидів або рейтинг ознак"
            ),
        },
        {
            "step": "Ціль аналізу визначено",
            "status": "done" if "target-correlation" in actions else "pending",
            "detail": (
                "Рейтинг ознак уже побудовано"
                if "target-correlation" in actions
                else "Оберіть цільову колонку та тип задачі"
            ),
        },
        {
            "step": "Моделі оцінено",
            "status": "done" if "modeling-compare" in actions else "pending",
            "detail": (
                "Моделі вже порівнювалися"
                if "modeling-compare" in actions
                else "Порівняйте моделі класифікації або регресії"
            ),
        },
        {
            "step": "Висновок сформовано",
            "status": "done" if "summary-report" in actions else "pending",
            "detail": (
                "Звіт уже формувався"
                if "summary-report" in actions
                else "Сформуйте підсумковий звіт після аналізу"
            ),
        },
    ]


def recommended_actions(profile, metadata):
    actions = []
    warning_levels = {item["level"] for item in profile["quality_warnings"]}
    if "warning" in warning_levels:
        actions.append("Переглянути попередження якості даних перед остаточними висновками.")
    if profile["target_suggestions"]:
        actions.append(
            f"Почати дослідження з цільової колонки {profile['target_suggestions'][0]} "
            "або обрати іншу за змістом задачі."
        )
    else:
        actions.append("Вручну визначити цільову колонку у словнику метаданих.")
    if metadata_coverage(metadata, profile["columns"])["percent"] < 30:
        actions.append("Описати ключові колонки та коди класів у словнику метаданих.")
    if profile["categorical_encoded_columns"]:
        actions.append("Перевірити закодовані категорії, щоб не трактувати коди як неперервні величини.")
    actions.append("Порівняти Pearson і Spearman для важливих числових ознак.")
    actions.append("Після вибору цілі порівняти Logistic Regression і Random Forest за balanced accuracy та F1.")
    return actions


def _sample_overview(sample_info):
    if not sample_info:
        return None
    if sample_info.get("is_limited"):
        return (
            "Аналіз виконується на обмеженій вибірці: "
            f"{sample_info['current_rows']} з {sample_info['source_rows']} рядків "
            f"({sample_info['percent']}%)."
        )
    return f"Використовується повний набір даних: {sample_info.get('current_rows', 0)} рядків."


def build_summary_report(profile, metadata, latest_model_payload, history_items, sample_info=None):
    coverage = metadata_coverage(metadata, profile["columns"])
    target_summaries = []

    for target in profile["target_profiles"][:5]:
        column_meta = metadata.get(target["column"], {})
        class_descriptions = column_meta.get("class_descriptions", {})
        target_summaries.append(
            {
                **target,
                "description": column_meta.get("description", ""),
                "classes": [
                    {
                        **item,
                        "description": class_descriptions.get(str(item["value"]), ""),
                    }
                    for item in target["items"]
                ],
            }
        )

    overview = [
            f"Набір містить {profile['rows_count']} рядків і {profile['columns_count']} колонок.",
            (
                f"Числових колонок: {len(profile['numeric_columns'])}; "
                f"категоріальних або закодованих: "
                f"{len(profile['categorical_columns']) + len(profile['categorical_encoded_columns'])}."
            ),
            f"Покриття словника метаданих: {coverage['percent']}% колонок.",
    ]
    sample_text = _sample_overview(sample_info)
    if sample_text:
        overview.append(sample_text)

    return {
        "overview": overview,
        "workflow": workflow_summary(profile, metadata, history_items),
        "quality_warnings": profile["quality_warnings"],
        "recommended_actions": recommended_actions(profile, metadata),
        "target_summaries": target_summaries,
        "metadata_coverage": coverage,
        "sample_info": sample_info,
        "latest_model": latest_model_payload,
    }


def build_correlation_matrix(df, method="pearson", columns=None, max_columns=14):
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    if columns:
        requested = [column for column in columns if column in numeric_columns]
    else:
        requested = numeric_columns
    if len(requested) < 2:
        raise ValueError("At least two numeric columns are required for a correlation matrix")
    requested = requested[:max_columns]
    numeric_df = df[requested].apply(pd.to_numeric, errors="coerce")
    matrix = numeric_df.corr(method=method).fillna(0)
    return {
        "method": method,
        "columns": requested,
        "matrix": [
            [round(float(matrix.loc[row, column]), 4) for column in requested]
            for row in requested
        ],
    }

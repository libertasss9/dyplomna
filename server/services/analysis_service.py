import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.linear_model import LinearRegression
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
import numpy as np


class AnalysisService:
    TREND_BIN_LIMIT = 12

    @staticmethod
    def _numeric_pair(df, col_x, col_y):
        pair = df[[col_x, col_y]].dropna().copy()
        pair[col_x] = pd.to_numeric(pair[col_x], errors="coerce")
        pair[col_y] = pd.to_numeric(pair[col_y], errors="coerce")
        pair = pair.dropna()
        if len(pair) < 2:
            raise ValueError("Not enough numeric rows for analysis")
        return pair

    @staticmethod
    def _format_bin_label(value):
        if hasattr(value, "left") and hasattr(value, "right"):
            return f"{float(value.left):.2f} - {float(value.right):.2f}"
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.2f}"

    @staticmethod
    def _trend_summary(pair, col_x, col_y):
        unique_x = pair[col_x].nunique(dropna=True)
        if unique_x <= AnalysisService.TREND_BIN_LIMIT:
            grouped = (
                pair.groupby(col_x, dropna=True)[col_y]
                .agg(["mean", "count"])
                .reset_index()
                .sort_values(col_x)
            )
            points = [
                {
                    "label": AnalysisService._format_bin_label(row[col_x]),
                    "x": float(row[col_x]),
                    "y": float(row["mean"]),
                    "count": int(row["count"]),
                }
                for _, row in grouped.iterrows()
            ]
            return {
                "trend": {
                    "kind": "grouped",
                    "x_label": col_x,
                    "y_label": f"Average {col_y}",
                    "points": points,
                }
            }

        bin_count = min(AnalysisService.TREND_BIN_LIMIT, max(4, int(np.sqrt(len(pair)))))
        try:
            bins = pd.qcut(pair[col_x], q=bin_count, duplicates="drop")
        except ValueError:
            bins = pd.cut(pair[col_x], bins=bin_count, duplicates="drop")

        frame = pair.assign(_bin=bins)
        grouped = (
            frame.groupby("_bin", observed=True)
            .agg(x_mid=(col_x, "mean"), y_mean=(col_y, "mean"), count=(col_y, "size"))
            .reset_index()
        )
        points = [
            {
                "label": AnalysisService._format_bin_label(row["_bin"]),
                "x": float(row["x_mid"]),
                "y": float(row["y_mean"]),
                "count": int(row["count"]),
            }
            for _, row in grouped.iterrows()
            if not pd.isna(row["x_mid"]) and not pd.isna(row["y_mean"])
        ]
        return {
            "trend": {
                "kind": "binned",
                "x_label": col_x,
                "y_label": f"Average {col_y}",
                "points": points,
            }
        }

    @staticmethod
    def _strength_label(value):
        absolute = abs(value)
        if absolute < 0.1:
            return "майже відсутній"
        if absolute < 0.3:
            return "слабкий"
        if absolute < 0.5:
            return "помірний"
        if absolute < 0.7:
            return "помітний"
        return "сильний"

    @staticmethod
    def _trend_extremes(trend):
        points = trend.get("points", [])
        if not points:
            return None, None
        lowest = min(points, key=lambda item: item["y"])
        highest = max(points, key=lambda item: item["y"])
        return lowest, highest

    @staticmethod
    def _correlation_insights(col_x, col_y, method, coefficient, trend):
        direction = "прямий" if coefficient > 0 else "обернений"
        strength = AnalysisService._strength_label(coefficient)
        insights = [
            (
                f"Метод {method} показує {strength} {direction} статистичний зв'язок "
                f"між {col_x} і {col_y}: коефіцієнт {coefficient:.4f}."
            )
        ]
        lowest, highest = AnalysisService._trend_extremes(trend)
        if lowest and highest:
            insights.append(
                f"На агрегованому графіку найбільше середнє значення {col_y} у групі "
                f"'{highest['label']}', найменше - у групі '{lowest['label']}'."
            )
        insights.append(
            "Кореляція не доводить причинно-наслідковий зв'язок, але допомагає відібрати ознаки для подальшої перевірки."
        )
        return insights

    @staticmethod
    def _regression_insights(col_x, col_y, slope, r2, trend):
        direction = "зростає" if slope > 0 else "зменшується"
        fit = "слабко" if r2 < 0.2 else "помірно" if r2 < 0.5 else "добре"
        insights = [
            (
                f"За лінійною моделлю {col_y} у середньому {direction} при збільшенні "
                f"{col_x}; нахил дорівнює {slope:.4f}."
            ),
            (
                f"R2 = {r2:.4f}, тобто проста лінійна модель {fit} пояснює зміну цільової колонки."
            ),
        ]
        lowest, highest = AnalysisService._trend_extremes(trend)
        if lowest and highest:
            insights.append(
                f"Агрегований тренд показує діапазон із найвищим середнім {col_y}: '{highest['label']}'."
            )
        return insights

    @staticmethod
    def _target_correlation_insights(target_column, method, items):
        if not items:
            return ["Не знайдено числових ознак із визначеним коефіцієнтом кореляції для обраної цілі."]
        strongest = items[0]
        direction = "прямий" if strongest["coefficient"] >= 0 else "обернений"
        insights = [
            (
                f"Найсильніший зв'язок із {target_column} має ознака {strongest['feature']} "
                f"({direction}, коефіцієнт {strongest['coefficient']:.4f})."
            ),
            f"Рейтинг побудовано методом {method}; ознаки відсортовано за абсолютною силою зв'язку.",
        ]
        if len(items) >= 3:
            top_names = ", ".join(item["feature"] for item in items[:3])
            insights.append(f"Перші кандидати для подальшої перевірки: {top_names}.")
        return insights

    @staticmethod
    def _modeling_insights(result):
        if result.get("task_type") == "regression":
            models = result["models"]
            best = max(models, key=lambda item: item["r2"])
            insights = [
                (
                    f"Найкращий результат за R2 показує {best['name']}: "
                    f"{best['r2']:.4f}."
                )
            ]
            if result["feature_importance"]:
                top = result["feature_importance"][0]
                insights.append(
                    f"За Random Forest Regressor найбільший внесок у прогноз має ознака {top['feature']} "
                    f"(важливість {top['importance']:.4f})."
                )
            insights.append(
                "Регресійні метрики показують якість числового прогнозу; вони не доводять причинність, але допомагають перевірити силу закономірностей."
            )
            return insights

        models = result["models"]
        best = max(models, key=lambda item: item["balanced_accuracy"])
        class_counts = list(result["class_distribution"].values())
        insights = [
            (
                f"Найкращий результат за balanced accuracy показує {best['name']}: "
                f"{best['balanced_accuracy']:.4f}."
            )
        ]
        if class_counts and min(class_counts) > 0 and max(class_counts) / min(class_counts) >= 3:
            insights.append(
                "Розподіл класів незбалансований, тому balanced accuracy і macro F1 важливіші за звичайну accuracy."
            )
        if result["feature_importance"]:
            top = result["feature_importance"][0]
            insights.append(
                f"За Random Forest найбільший внесок у прогноз має ознака {top['feature']} "
                f"(важливість {top['importance']:.4f})."
            )
        insights.append(
            "Порівняння моделей слід використовувати як дослідницький орієнтир, а не як остаточний доказ причинності."
        )
        return insights

    @staticmethod
    def _numeric_series(df, column):
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if values.empty:
            raise ValueError("Column has no numeric values")
        return values

    @staticmethod
    def _normalise_feature_columns(df, target_column, feature_columns=None):
        if target_column not in df.columns:
            raise ValueError(f"Column '{target_column}' does not exist")
        if feature_columns is None:
            selected = [column for column in df.columns if column != target_column]
        else:
            if not isinstance(feature_columns, list):
                raise ValueError("Feature columns must be a list")
            selected = []
            for column in feature_columns:
                column = str(column).strip()
                if not column or column == target_column:
                    continue
                if column not in df.columns:
                    raise ValueError(f"Feature column '{column}' does not exist")
                if column not in selected:
                    selected.append(column)
        if not selected:
            raise ValueError("No feature columns selected")
        return selected

    @staticmethod
    def _prepare_model_data(df, target_column, feature_columns=None, task_type="classification"):
        selected = AnalysisService._normalise_feature_columns(df, target_column, feature_columns)
        frame = df[[target_column, *selected]].copy()
        frame = frame.dropna(subset=[target_column])
        if frame.empty:
            raise ValueError("Target column has no usable values")

        y = frame[target_column]
        if task_type == "regression":
            y = pd.to_numeric(y, errors="coerce")
            valid_target = y.notna()
            frame = frame.loc[valid_target].copy()
            y = y.loc[valid_target]
            if frame.empty:
                raise ValueError("Regression target has no numeric values")

        x_raw = frame[selected].copy()
        missing_actions = []
        encoded_parts = []
        source_map = {}

        for column in selected:
            series = x_raw[column]
            missing_count = int(series.isna().sum())
            if pd.api.types.is_numeric_dtype(series):
                numeric = pd.to_numeric(series, errors="coerce")
                missing_count = int(numeric.isna().sum())
                fill_value = numeric.median()
                if pd.isna(fill_value):
                    fill_value = 0
                if missing_count:
                    missing_actions.append(
                        f"{column}: заповнено {missing_count} числових пропусків медіаною"
                    )
                encoded_parts.append(numeric.fillna(fill_value).rename(column).to_frame())
                source_map[column] = column
            else:
                categorical = series.astype("string").fillna("__missing__")
                if missing_count:
                    missing_actions.append(
                        f"{column}: заповнено {missing_count} категоріальних пропусків окремою позначкою"
                    )
                dummies = pd.get_dummies(categorical, prefix=column, prefix_sep="__", drop_first=True)
                if dummies.empty:
                    continue
                for feature in dummies.columns:
                    source_map[feature] = column
                encoded_parts.append(dummies.astype(float))

        if not encoded_parts:
            raise ValueError("No feature columns available after preprocessing")

        x = pd.concat(encoded_parts, axis=1)
        constant_columns = [column for column in x.columns if x[column].nunique(dropna=False) <= 1]
        if constant_columns:
            x = x.drop(columns=constant_columns)
        if x.empty:
            raise ValueError("No variable feature columns available after preprocessing")

        return x, y, {
            "selected_features": selected,
            "encoded_features_count": int(x.shape[1]),
            "missing_actions": missing_actions,
            "source_map": source_map,
        }

    @staticmethod
    def _aggregate_importances(feature_names, importances, source_map):
        grouped = {}
        for feature, importance in zip(feature_names, importances):
            source = source_map.get(feature, feature)
            grouped[source] = grouped.get(source, 0.0) + float(importance)
        items = [
            {"feature": feature, "importance": importance}
            for feature, importance in grouped.items()
        ]
        items.sort(key=lambda item: item["importance"], reverse=True)
        return items

    @staticmethod
    def correlation(df, col_x, col_y, method="pearson"):
        pair = AnalysisService._numeric_pair(df, col_x, col_y)
        x = pair[col_x]
        y = pair[col_y]

        if method == "pearson":
            coef, _ = pearsonr(x, y)
        elif method == "spearman":
            coef, _ = spearmanr(x, y)
        else:
            raise ValueError("Unknown correlation method")
        if np.isnan(coef):
            raise ValueError("Correlation is undefined for constant columns")
        trend_payload = AnalysisService._trend_summary(pair, col_x, col_y)

        return {
            "method": method,
            "coefficient": float(coef),
            "rows_used": int(len(pair)),
            **trend_payload,
            "insights": AnalysisService._correlation_insights(
                col_x, col_y, method, float(coef), trend_payload["trend"]
            ),
        }

    @staticmethod
    def linear_regression(df, col_x, col_y):
        pair = AnalysisService._numeric_pair(df, col_x, col_y)
        X = pair[[col_x]].values
        y = pair[col_y].values

        model = LinearRegression()
        model.fit(X, y)

        slope = float(model.coef_[0])
        intercept = float(model.intercept_)
        r2 = float(model.score(X, y))
        trend_payload = AnalysisService._trend_summary(pair, col_x, col_y)

        return {
            "slope": slope,
            "intercept": intercept,
            "r2": r2,
            "rows_used": int(len(pair)),
            **trend_payload,
            "insights": AnalysisService._regression_insights(
                col_x, col_y, slope, r2, trend_payload["trend"]
            ),
        }

    @staticmethod
    def histogram(df, column, bins=10):
        if pd.api.types.is_numeric_dtype(df[column]):
            values = AnalysisService._numeric_series(df, column)
        else:
            counts = df[column].astype(str).value_counts().head(bins)
            return {
                "column": column,
                "bins": int(bins),
                "counts": counts.values.astype(int).tolist(),
                "labels": counts.index.tolist(),
                "kind": "categorical",
            }

        hist, edges = np.histogram(values, bins=bins)
        return {
            "column": column,
            "bins": int(bins),
            "counts": hist.astype(int).tolist(),
            "edges": [float(item) for item in edges.tolist()],
            "kind": "numeric",
        }

    @staticmethod
    def detect_outliers(df, column, threshold=3):
        values = AnalysisService._numeric_series(df, column)
        std = values.std(ddof=0)
        q1 = float(values.quantile(0.25))
        median = float(values.quantile(0.5))
        q3 = float(values.quantile(0.75))
        iqr = q3 - q1
        summary = {
            "min": float(values.min()),
            "q1": q1,
            "median": median,
            "q3": q3,
            "max": float(values.max()),
            "iqr_lower": float(q1 - 1.5 * iqr),
            "iqr_upper": float(q3 + 1.5 * iqr),
        }
        if std == 0 or np.isnan(std):
            return {
                "column": column,
                "threshold": float(threshold),
                "outliers_count": 0,
                "outliers": [],
                "summary": summary,
            }
        z_scores = np.abs((values - values.mean()) / std)
        outlier_values = values[z_scores > threshold]
        return {
            "column": column,
            "threshold": float(threshold),
            "outliers_count": int(outlier_values.shape[0]),
            "outliers": [float(item) for item in outlier_values.head(100).tolist()],
            "summary": summary,
        }

    @staticmethod
    def missing_values(df):
        missing = df.isna().sum()
        result = []
        rows_count = len(df.index)
        for column, count in missing.items():
            result.append(
                {
                    "column": column,
                    "missing_count": int(count),
                    "missing_percent": round((float(count) / rows_count) * 100, 4) if rows_count else 0.0,
                }
            )
        result.sort(key=lambda item: item["missing_count"], reverse=True)
        return {"rows": rows_count, "items": result}

    @staticmethod
    def feature_correlation_with_target(df, target_column, method="pearson"):
        if target_column not in df.columns:
            raise ValueError(f"Column '{target_column}' does not exist")

        numeric_df = df.select_dtypes(include="number")
        if target_column not in numeric_df.columns:
            raise ValueError(f"Target '{target_column}' must be numeric")

        target = pd.to_numeric(numeric_df[target_column], errors="coerce")
        if target.dropna().shape[0] < 2:
            raise ValueError("Not enough numeric target values for correlation")

        items = []
        for column in numeric_df.columns:
            if column == target_column:
                continue
            values = pd.to_numeric(numeric_df[column], errors="coerce")
            pair = pd.DataFrame({"feature": values, "target": target}).dropna()
            if len(pair.index) < 2:
                continue
            if method == "spearman":
                coef, _ = spearmanr(pair["feature"], pair["target"])
            else:
                coef, _ = pearsonr(pair["feature"], pair["target"])
            if np.isnan(coef):
                continue
            items.append(
                {
                    "feature": column,
                    "coefficient": float(coef),
                    "abs_coefficient": float(abs(coef)),
                    "rows_used": int(len(pair.index)),
                }
            )

        items.sort(key=lambda item: item["abs_coefficient"], reverse=True)
        items = items[:20]
        return {
            "target": target_column,
            "method": method,
            "items": items,
            "insights": AnalysisService._target_correlation_insights(target_column, method, items),
        }

    @staticmethod
    def compare_models(df, target_column, task_type="classification", feature_columns=None):
        task_type = str(task_type or "classification").lower()
        if task_type not in {"classification", "regression"}:
            raise ValueError("Modeling task must be classification or regression")

        x, y, preprocessing = AnalysisService._prepare_model_data(
            df, target_column, feature_columns, task_type
        )
        if len(y) < 5:
            raise ValueError("Not enough rows for model comparison")

        if task_type == "regression":
            x_train, x_test, y_train, y_test = train_test_split(
                x, y, test_size=0.2, random_state=42
            )
            linear = LinearRegression()
            linear.fit(x_train, y_train)
            linear_pred = linear.predict(x_test)

            forest = RandomForestRegressor(
                n_estimators=160,
                random_state=42,
                n_jobs=-1,
            )
            forest.fit(x_train, y_train)
            forest_pred = forest.predict(x_test)
            importances = AnalysisService._aggregate_importances(
                x.columns, forest.feature_importances_, preprocessing["source_map"]
            )

            def regression_metrics(name, predictions):
                mse = mean_squared_error(y_test, predictions)
                return {
                    "name": name,
                    "mae": float(mean_absolute_error(y_test, predictions)),
                    "rmse": float(np.sqrt(mse)),
                    "r2": float(r2_score(y_test, predictions)),
                }

            result = {
                "task_type": "regression",
                "target": target_column,
                "rows_train": int(len(x_train)),
                "rows_test": int(len(x_test)),
                "target_summary": {
                    "min": float(y.min()),
                    "median": float(y.median()),
                    "max": float(y.max()),
                    "mean": float(y.mean()),
                },
                "preprocessing": {
                    "selected_features": preprocessing["selected_features"],
                    "encoded_features_count": preprocessing["encoded_features_count"],
                    "missing_actions": preprocessing["missing_actions"],
                },
                "feature_importance": importances[:10],
                "models": [
                    regression_metrics("Linear Regression", linear_pred),
                    regression_metrics("Random Forest Regressor", forest_pred),
                ],
            }
            result["insights"] = AnalysisService._modeling_insights(result)
            return result

        class_count = y.nunique(dropna=True)
        if class_count < 2:
            raise ValueError("Target must contain at least two classes")
        if class_count > max(20, int(len(y) * 0.2)):
            raise ValueError("Target should be categorical for classification models")

        y = y.astype(str)
        stratify = y if y.value_counts().min() >= 2 else None
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=0.2, random_state=42, stratify=stratify
        )

        logistic = LogisticRegression(max_iter=1500, class_weight="balanced")
        logistic.fit(x_train, y_train)
        logistic_pred = logistic.predict(x_test)

        forest = RandomForestClassifier(
            n_estimators=200,
            random_state=42,
            class_weight="balanced_subsample",
            n_jobs=-1,
        )
        forest.fit(x_train, y_train)
        forest_pred = forest.predict(x_test)
        importances = AnalysisService._aggregate_importances(
            x.columns, forest.feature_importances_, preprocessing["source_map"]
        )
        labels = sorted(y.dropna().unique().tolist(), key=lambda label: str(label))

        def classification_metrics(name, predictions):
            report = classification_report(
                y_test, predictions, output_dict=True, zero_division=0
            )
            return {
                "name": name,
                "accuracy": float(accuracy_score(y_test, predictions)),
                "balanced_accuracy": float(balanced_accuracy_score(y_test, predictions)),
                "precision_macro": float(
                    precision_score(y_test, predictions, average="macro", zero_division=0)
                ),
                "recall_macro": float(
                    recall_score(y_test, predictions, average="macro", zero_division=0)
                ),
                "f1_macro": float(
                    f1_score(y_test, predictions, average="macro", zero_division=0)
                ),
                "f1_weighted": float(
                    f1_score(y_test, predictions, average="weighted", zero_division=0)
                ),
                "labels": [str(label) for label in labels],
                "confusion_matrix": confusion_matrix(
                    y_test, predictions, labels=labels
                ).astype(int).tolist(),
                "classification_report": report,
            }

        result = {
            "task_type": "classification",
            "target": target_column,
            "rows_train": int(len(x_train)),
            "rows_test": int(len(x_test)),
            "class_distribution": {
                str(label): int(count) for label, count in y.value_counts().sort_index().items()
            },
            "preprocessing": {
                "selected_features": preprocessing["selected_features"],
                "encoded_features_count": preprocessing["encoded_features_count"],
                "missing_actions": preprocessing["missing_actions"],
            },
            "feature_importance": importances[:10],
            "models": [
                classification_metrics("Logistic Regression", logistic_pred),
                classification_metrics("Random Forest", forest_pred),
            ],
        }
        result["insights"] = AnalysisService._modeling_insights(result)
        return result

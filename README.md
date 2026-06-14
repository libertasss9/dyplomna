# PatternLab Data Analyzer

Client-server software for analysis and pattern detection in tabular CSV datasets.

The system is dataset-independent: users upload a CSV file, inspect its profile, clean data, document column meaning, explore statistical patterns, compare models, and generate a summary report. The diabetes health indicators CSV is used as a testing and research dataset, not as a fixed product domain.

## Structure

- `client/` - static HTML, CSS, and JavaScript user interface.
- `server/` - Flask REST API, authentication, dataset state, and route layer.
- `server/services/` - profiling, cleaning, analysis, modeling, reporting, and measurement logic.
- `server/database/` - SQLite database manager and local persistence.
- `tests/` - unit and route tests for the main server workflows.
- `docs/` - project documentation used for the qualification report.

## Main Capabilities

- User registration, login, session validation, and protected private pages.
- CSV upload with file type, size, and empty dataset validation.
- Automatic dataset profiling: column roles, missing values, duplicates, target suggestions, and quality warnings.
- Dataset cleaning: missing values, duplicates, zero-like values, column deletion, and manual target class creation.
- Column dictionary: descriptions, semantic roles, class labels, and source-column tracking for created targets.
- Sample limiting and restoration with visible `sample_info` for analysis and modeling results.
- Descriptive statistics, histograms, categorical distributions, Pearson/Spearman correlations, and correlation heatmap.
- Linear regression for numeric column pairs and Z-score outlier detection.
- Feature-to-target ranking with asynchronous progress polling.
- Classification and regression model comparison with Logistic Regression / Linear Regression and Random Forest.
- Saved analysis state, model results, report summary, and action history in SQLite.
- Console-only performance measurements for upload, profiling, data quality, correlations, ranking, and machine learning.

## Local Startup

Install dependencies from the project root:

```powershell
pip install -r requirements.txt
```

Run the Flask API from the project root:

```powershell
python -m flask --app server.app run
```

Run the static client in a second terminal:

```powershell
cd client
python -m http.server 5500
```

Open the application at:

```text
http://127.0.0.1:5500/login.html
```

The API base URL is configured in `client/api.js` and currently points to `http://127.0.0.1:5000`.

## Tests

Run the automated tests from the project root:

```powershell
python -m unittest discover -s tests
```

The tests cover authentication, CSV upload, profiling, cleaning, metadata, sample limiting, analysis routes, ranking, modeling, state isolation, and report summary behavior.


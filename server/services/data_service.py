class DataService:

    @staticmethod
    def apply_limit(df, limit):
        if df is None:
            return None
        if limit:
            return df.head(int(limit))
        return df

    @staticmethod
    def parse_row_limit(value):
        if value in (None, "", "all"):
            return None
        try:
            limit = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Limit must be a positive integer or empty") from exc
        if limit <= 0:
            raise ValueError("Limit must be greater than 0")
        return limit

    @staticmethod
    def sample_info(active_df, source_df=None, requested_limit=None):
        source_df = source_df if source_df is not None else active_df
        current_rows = int(active_df.shape[0]) if active_df is not None else 0
        columns_count = int(active_df.shape[1]) if active_df is not None else 0
        source_rows = int(source_df.shape[0]) if source_df is not None else current_rows
        is_limited = requested_limit is not None and current_rows < source_rows
        percent = round((current_rows / source_rows) * 100, 4) if source_rows else 0.0

        return {
            "mode": "limited" if is_limited else "full",
            "is_limited": is_limited,
            "requested_limit": requested_limit,
            "current_rows": current_rows,
            "source_rows": source_rows,
            "columns_count": columns_count,
            "percent": percent,
        }

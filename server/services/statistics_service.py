class StatisticsService:

    @staticmethod
    def basic_statistics(df):
        summary = df.describe(include="all").fillna("").to_dict()
        return summary

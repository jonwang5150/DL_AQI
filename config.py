class Settings:
    # 連線資訊直接寫在下一行。
    database_url = 'postgresql+psycopg://postgres:abc123@localhost:5432/postgres'
    csv_path = 'aqi_hour_concat.csv'
    csv_encoding = 'utf-8-sig'
    batch_size = 1000
    dry_run = False


settings = Settings()

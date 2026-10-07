class Settings:
    # 連線資訊直接寫在下一行。
    database_url = 'postgresql+psycopg://postgres:abc123@localhost:5432/postgres'
    batch_size = 1000
    dry_run = False


settings = Settings()

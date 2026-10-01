#!/usr/bin/env python3
"""爬取 AQI，每批直接呼叫 update_db 更新資料庫，不儲存 CSV 或試算表。

python crawl_to_db.py --stations all --start 2026-08-01 --end 2026-09-06
加上 --dry-run 只驗證、不連線資料庫。設定沿用 config.py。
每個最多 30 天的下載批次各自提交；後續失敗不影響先前批次，可重新爬取更新。
依賴：requests beautifulsoup4 pandas odfpy SQLAlchemy psycopg[binary]
Excel 格式另需 openpyxl（xlsx）或 xlrd（xls）。
"""
from __future__ import annotations

import argparse
import re
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Iterable, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import update_db

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment]


URL = "https://www.tldep.gov.taipei/Public/DownLoad/AqiHour.aspx"
MAX_DAYS_PER_REQUEST = 30
DATE_FIELD_START = "ctl00$CPH_Content$tbx_start"
DATE_FIELD_END = "ctl00$CPH_Content$tbx_end"
DOWNLOAD_BUTTON = "ctl00$CPH_Content$btn_download"


@dataclass(frozen=True)
class StationField:
    name: str
    value: str


@dataclass(frozen=True)
class FormData:
    hidden: dict[str, str]
    stations: dict[str, StationField]


class CompatibleTLSAdapter(HTTPAdapter):
    """相容目標網站的舊式憑證，同時保留 CA 與主機名稱驗證。"""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        # 新版 OpenSSL 的 strict 模式會因該站憑證缺少 SKI 而拒絕連線。
        # 只停用 X509 strict；不使用 verify=False。
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        pool_kwargs["ssl_context"] = context
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)


def parse_date(value: str) -> date:
    normalized = value.strip().replace("/", "-")
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"日期格式錯誤：{value!r}，請使用 YYYY-MM-DD 或 YYYY/MM/DD"
        ) from exc


def split_date_range(start: date, end: date) -> Iterable[tuple[date, date]]:
    """切成每批最多 30 個日曆日，開始日與結束日都計入。"""
    if start > end:
        raise ValueError("開始日期不可晚於結束日期")

    batch_start = start
    while batch_start <= end:
        batch_end = min(batch_start + timedelta(days=MAX_DAYS_PER_REQUEST - 1), end)
        yield batch_start, batch_end
        batch_start = batch_end + timedelta(days=1)


def make_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET",)),
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/140.0 Safari/537.36"
            ),
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        }
    )
    session.mount("https://", CompatibleTLSAdapter(max_retries=retry))
    return session


def parse_form(html: str) -> FormData:
    """以 BeautifulSoup 擷取 ASP.NET 隱藏欄位及測站 checkbox。"""
    if BeautifulSoup is None:
        raise RuntimeError(
            "缺少 BeautifulSoup，請先執行：pip install beautifulsoup4"
        )

    soup = BeautifulSoup(html, "html.parser")

    hidden: dict[str, str] = {}
    for element in soup.select('input[type="hidden"][name]'):
        name = element.get("name")
        if isinstance(name, str):
            value = element.get("value", "")
            hidden[name] = value if isinstance(value, str) else ""

    stations: dict[str, StationField] = {}
    selector = '#CPH_Content_cbl_site input[type="checkbox"][name]'
    for checkbox in soup.select(selector):
        element_id = checkbox.get("id")
        field_name = checkbox.get("name")
        if not isinstance(element_id, str) or not isinstance(field_name, str):
            continue

        label = soup.find("label", attrs={"for": element_id})
        if label is None:
            continue
        station_name = label.get_text(" ", strip=True)
        field_value = checkbox.get("value", "on")
        if station_name:
            stations[station_name] = StationField(
                name=field_name,
                value=field_value if isinstance(field_value, str) else "on",
            )

    if "__VIEWSTATE" not in hidden or not stations:
        raise RuntimeError("無法解析下載表單；網站版面或欄位可能已變更")
    return FormData(hidden=hidden, stations=stations)


def read_form(session: requests.Session, timeout: float) -> FormData:
    response = session.get(URL, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return parse_form(response.text)


def normalize_station_names(raw: str, available: Iterable[str]) -> list[str]:
    available_list = list(available)
    value = raw.strip()
    if value.lower() in {"all", "*", "全部", "全選"}:
        return available_list

    names = [part.strip() for part in re.split(r"[,，、]", value) if part.strip()]
    unknown = [name for name in names if name not in available_list]
    if unknown:
        raise ValueError(
            f"找不到測站：{', '.join(unknown)}；可用測站：{', '.join(available_list)}"
        )
    if not names:
        raise ValueError("至少需要選擇一個測站")
    return list(dict.fromkeys(names))


def looks_like_html(response: requests.Response) -> bool:
    content_type = response.headers.get("Content-Type", "").lower()
    prefix = response.content[:512].lstrip().lower()
    return "text/html" in content_type or prefix.startswith((b"<!doctype html", b"<html"))


def extract_page_message(response: requests.Response) -> str:
    """利用 BeautifulSoup 將伺服器錯誤頁面轉成簡短純文字。"""
    if BeautifulSoup is None:
        return "無法解析網站錯誤頁面"
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["script", "style"]):
        #把這些元素及其內容完全移除，避免錯誤摘要包含 JavaScript 或css
        element.decompose()

    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:300]
    # re.sub(搜尋規則, 替換內容, 原始文字)
    # soup.get_text(" ", strip=True) 取得網頁中的純文字，以空格分隔不同元素，並移除前後空白。
    

def download_batch(
    session: requests.Session,
    stations: list[str],
    batch_start: date,
    batch_end: date,
    timeout: float,
) -> requests.Response:
    # 每批重新讀取頁面，以取得仍有效的 ViewState 和 EventValidation。
    form = read_form(session, timeout)
    missing = [name for name in stations if name not in form.stations]
    if missing:
        raise RuntimeError(f"網站已找不到測站：{', '.join(missing)}")

    payload: list[tuple[str, str]] = list(form.hidden.items())
    for station_name in stations:
        field = form.stations[station_name]
        payload.append((field.name, field.value))
    payload.extend(
        [
            (DATE_FIELD_START, batch_start.strftime("%Y/%m/%d")),
            (DATE_FIELD_END, batch_end.strftime("%Y/%m/%d")),
            (DOWNLOAD_BUTTON, "下載"),
        ]
    )

    response = session.post(
        URL,
        data=payload,
        headers={"Referer": URL},
        timeout=timeout,
    )
    response.raise_for_status()
    if looks_like_html(response):
        raise RuntimeError(
            "網站未回傳試算表。頁面內容摘要：" + extract_page_message(response)
        )
    if not response.content:
        raise RuntimeError("網站回傳空白檔案")

    return response


def read_download_rows(content: bytes) -> Iterator[dict]:
    """在記憶體解析 ODS／Excel，沿用 update_db 的驗證規則。"""
    try:
        import pandas as pd
        frame = pd.read_excel(BytesIO(content), dtype=str, keep_default_na=False)
    except ImportError as exc:
        raise RuntimeError("請安裝 pandas odfpy；Excel 格式另需 openpyxl 或 xlrd。") from exc
    columns = [str(name).strip() for name in frame.columns]
    if len(set(columns)) != len(columns) or set(columns) != set(update_db.COLUMNS):
        raise ValueError(f"下載資料欄位必須為 {', '.join(update_db.COLUMNS)}")
    for line, values in enumerate(frame.itertuples(index=False, name=None), start=2):
        raw = dict(zip(columns, values))
        # 原生日期儲存格可能被解析為 ISO 格式文字。
        try:
            raw["日期"] = datetime.fromisoformat(raw["日期"]).strftime("%Y/%m/%d %H:%M")
        except ValueError:
            pass
        try:
            yield update_db.parse_row(raw)
        except ValueError as exc:
            raise ValueError(f"下載資料第 {line} 行：{exc}") from exc


def build_argument_parser(settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stations", help="測站名稱，以逗號分隔；all 代表全部")
    parser.add_argument("--start", type=parse_date, help="開始日期：YYYY-MM-DD")
    parser.add_argument("--end", type=parse_date, help="結束日期：YYYY-MM-DD")
    parser.add_argument("--delay", type=float, default=1.0, help="批次間等待秒數（預設：1）")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP 逾時秒數（預設：60）")
    parser.add_argument("--list-stations", action="store_true", help="列出測站後結束")
    parser.add_argument("--batch-size", type=int, default=settings.batch_size, help="每批資料庫寫入筆數")
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=settings.dry_run,
                        help="只驗證；--no-dry-run 強制執行匯入")
    return parser


def main() -> int:
    from config import settings

    parser = build_argument_parser(settings)
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay 不可小於 0")
    if args.timeout <= 0:
        parser.error("--timeout 必須大於 0")
    if args.batch_size <= 0:
        parser.error("--batch-size 必須大於 0")

    with make_session() as session:
        available = list(read_form(session, args.timeout).stations)
        if args.list_stations:
            print("可用測站：" + "、".join(available))
            return 0
        station_input = args.stations
        if station_input is None:
            print("可用測站：" + "、".join(available))
            station_input = input("請輸入測站（逗號分隔；all 代表全部）：")
        stations = normalize_station_names(station_input, available)
        start = args.start or parse_date(input("開始日期（YYYY-MM-DD）："))
        end = args.end or parse_date(input("結束日期（YYYY-MM-DD）："))
        batches = list(split_date_range(start, end))
        total = 0
        for index, (batch_start, batch_end) in enumerate(batches, start=1):
            print(f"[{index}/{len(batches)}] 爬取 {batch_start} 至 {batch_end} ...", flush=True)
            try:
                with download_batch(session, stations, batch_start, batch_end, args.timeout) as response:
                    rows = read_download_rows(response.content)
                    if args.dry_run:
                        count = sum(1 for _ in rows)
                    else:
                        count = update_db.update_rows(rows, settings=settings, batch_size=args.batch_size)
            except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(f"批次 {batch_start} 至 {batch_end} 失敗：{exc}") from exc
            total += count
            action = "驗證通過" if args.dry_run else "已提交至資料庫"
            print(f"    {action}：{count:,} 筆")
            if index < len(batches) and args.delay:
                time.sleep(args.delay)
        print(f"全部完成：共 {total:,} 筆" + ("；未連線資料庫。" if args.dry_run else "。"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (requests.RequestException, OSError, RuntimeError, ValueError, LookupError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)

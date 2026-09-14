#!/usr/bin/env python3
"""批次下載臺北市環境品質資訊網的 AQI 小時資料。

網站：https://www.tldep.gov.taipei/Public/DownLoad/AqiHour.aspx

範例：
    python serch.py --stations 中正,大安 --start 2026-08-01 --end 2026-09-06
    python serch.py --stations all --start 2026/08/01 --end 2026/09/06

若未提供參數，程式會以互動方式詢問測站與日期。網站輸出為 Excel 可開啟的
OpenDocument 試算表（.ods）。
"""

from __future__ import annotations

import argparse
import re
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


URL = "https://www.tldep.gov.taipei/Public/DownLoad/AqiHour.aspx"
MAX_DAYS_PER_REQUEST = 30
DATE_FIELD_START = "ctl00$CPH_Content$tbx_start"
DATE_FIELD_END = "ctl00$CPH_Content$tbx_end"
DOWNLOAD_BUTTON = "ctl00$CPH_Content$btn_download"


@dataclass(frozen=True)
class StationField:
    name: str
    value: str


class AqiFormParser(HTMLParser):
    """只解析下載表單所需的 hidden 欄位與測站 checkbox。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: dict[str, str] = {}
        self._checkboxes_by_id: dict[str, StationField] = {}
        self.stations: dict[str, StationField] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "input":
            input_type = (attributes.get("type") or "text").lower()
            name = attributes.get("name")
            if input_type == "hidden" and name:
                self.hidden[name] = attributes.get("value") or ""
            elif input_type == "checkbox" and name:
                element_id = attributes.get("id")
                if element_id:
                    self._checkboxes_by_id[element_id] = StationField(
                        name=name,
                        value=attributes.get("value") or "on",
                    )
        elif tag == "label":
            self._label_for = attributes.get("for")
            self._label_text = []

    def handle_data(self, data: str) -> None:
        if self._label_for is not None:
            self._label_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_for is not None:
            label = "".join(self._label_text).strip()
            field = self._checkboxes_by_id.get(self._label_for)
            if label and field:
                self.stations[label] = field
            self._label_for = None
            self._label_text = []


class CompatibleTLSAdapter(HTTPAdapter):
    """相容缺少 Subject Key Identifier、但憑證鏈仍有效的舊式站台。"""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        # Python 3.13 / OpenSSL 3 的嚴格模式會拒絕目標站目前的憑證。
        # 僅關閉 X509 strict；CA 憑證鏈與 hostname 驗證仍維持開啟。
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
    """切成每批最多 30 個日曆日（起訖日都計入）。"""
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


def read_form(session: requests.Session, timeout: float) -> AqiFormParser:
    response = session.get(URL, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"

    parser = AqiFormParser()
    parser.feed(response.text)
    if "__VIEWSTATE" not in parser.hidden or not parser.stations:
        raise RuntimeError("無法解析下載表單；網站版面或欄位可能已變更")
    return parser


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


def extension_from_response(response: requests.Response) -> str:
    content_type = response.headers.get("Content-Type", "").lower()
    disposition = response.headers.get("Content-Disposition", "")
    filename_match = re.search(
        r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)",
        disposition,
        flags=re.IGNORECASE,
    )
    if filename_match:
        filename = unquote(filename_match.group(1) or filename_match.group(2)).strip()
        suffix = Path(filename).suffix
        if suffix and re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
            return suffix.lower()
    if "spreadsheetml" in content_type:
        return ".xlsx"
    if "ms-excel" in content_type:
        return ".xls"
    return ".ods"


def looks_like_html(response: requests.Response) -> bool:
    content_type = response.headers.get("Content-Type", "").lower()
    prefix = response.content[:512].lstrip().lower()
    return "text/html" in content_type or prefix.startswith((b"<!doctype html", b"<html"))


def extract_page_message(content: bytes, encoding: str | None) -> str:
    text = content.decode(encoding or "utf-8", errors="replace")
    # 將伺服器回傳的 HTML 濃縮，方便看出驗證失敗或維護訊息。
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:300]


def download_batch(
    session: requests.Session,
    stations: list[str],
    batch_start: date,
    batch_end: date,
    output_dir: Path,
    timeout: float,
) -> Path:
    # 每批重新 GET，以取得仍有效的 ASP.NET ViewState/EventValidation。
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
        message = extract_page_message(response.content, response.encoding)
        raise RuntimeError(f"網站未回傳試算表。頁面內容摘要：{message}")
    if not response.content:
        raise RuntimeError("網站回傳空白檔案")

    suffix = extension_from_response(response)
    filename = f"aqi_hour_{batch_start:%Y%m%d}_{batch_end:%Y%m%d}{suffix}"
    destination = output_dir / filename
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(response.content)
    temporary.replace(destination)
    return destination


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="下載臺北市環境品質資訊網 AQI 小時資料（自動切成每批最多 30 日）"
    )
    parser.add_argument(
        "--stations",
        help="測站名稱，以逗號分隔；輸入 all 代表全部測站，例如：中正,大安",
    )
    parser.add_argument("--start", type=parse_date, help="開始日期，YYYY-MM-DD")
    parser.add_argument("--end", type=parse_date, help="結束日期，YYYY-MM-DD")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("downloads"),
        help="下載目錄（預設：downloads）",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="批次之間等待秒數（預設：1）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="每個 HTTP 請求的逾時秒數（預設：60）",
    )
    parser.add_argument(
        "--list-stations",
        action="store_true",
        help="列出網站目前的測站後結束",
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    if args.delay < 0:
        raise ValueError("--delay 不可小於 0")
    if args.timeout <= 0:
        raise ValueError("--timeout 必須大於 0")

    session = make_session()
    try:
        initial_form = read_form(session, args.timeout)
        available = list(initial_form.stations)

        if args.list_stations:
            print("可用測站：" + "、".join(available))
            return 0

        station_input = args.stations
        if station_input is None:
            print("可用測站：" + "、".join(available))
            station_input = input("請輸入測站（逗號分隔，all 代表全部）：")
        stations = normalize_station_names(station_input, available)

        start = args.start or parse_date(input("開始日期（YYYY-MM-DD）："))
        end = args.end or parse_date(input("結束日期（YYYY-MM-DD）："))
        batches = list(split_date_range(start, end))

        args.output.mkdir(parents=True, exist_ok=True)
        print(f"測站：{', '.join(stations)}")
        print(f"日期：{start} 至 {end}，共 {len(batches)} 批")

        downloaded: list[Path] = []
        for index, (batch_start, batch_end) in enumerate(batches, start=1):
            print(f"[{index}/{len(batches)}] 下載 {batch_start} 至 {batch_end} ...", flush=True)
            path = download_batch(
                session,
                stations,
                batch_start,
                batch_end,
                args.output,
                args.timeout,
            )
            downloaded.append(path)
            print(f"    完成：{path} ({path.stat().st_size:,} bytes)")
            if index < len(batches) and args.delay:
                time.sleep(args.delay)

        print(f"全部完成，共下載 {len(downloaded)} 個檔案。")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)

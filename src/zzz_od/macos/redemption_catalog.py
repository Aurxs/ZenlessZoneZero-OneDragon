"""只读读取上游国服兑换码目录；预览不登录、不兑换。"""

from __future__ import annotations

import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPMessage, HTTPResponse

import yaml

UPSTREAM_CATALOG = (
    'https://raw.githubusercontent.com/OneDragon-Anything/'
    'ZenlessZoneZero-OneDragon/main/config/redemption_codes.sample.yml'
)
MAX_BYTES = 65536


def normalize_code(value: str) -> str:
    """只接收一枚明确的 ASCII 字母数字兑换码。"""
    text = value.strip()
    if re.fullmatch(r'[A-Za-z0-9]{5,32}', text, flags=re.ASCII) is None:
        raise ValueError('请明确提供一枚 5–32 位 ASCII 字母数字兑换码')
    return text.upper()


def parse_cn_catalog(payload: bytes, today: date) -> list[dict[str, str]]:
    """只接受上游 codes 映射的有效日期；不执行或解析其它指令。"""
    if len(payload) > MAX_BYTES:
        raise ValueError('上游兑换码目录超出大小限制')
    root = yaml.safe_load(payload)
    if not isinstance(root, dict) or not isinstance(root.get('codes'), dict):
        raise ValueError('上游兑换码目录缺少 codes 映射')
    result: dict[str, str] = {}
    for code, expiry in root['codes'].items():
        if not isinstance(code, str) or type(expiry) not in (int, str):
            continue
        try:
            code = normalize_code(code)
            value = str(expiry)
            if not re.fullmatch(r'[0-9]{8}', value):
                continue
            end_date = datetime.strptime(value, '%Y%m%d').date()
        except ValueError:
            continue
        if end_date >= today:
            previous = result.get(code)
            date_iso = end_date.isoformat()
            result[code] = min(date_iso, previous) if previous else date_iso
    return [{'code': code, 'expiry_date_beijing': end} for code, end in result.items()]


def fetch_cn_catalog() -> list[dict[str, str]]:
    """仅从固定 HTTPS 目录取公开数据，不发送账号或机器信息。"""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self, req: urllib.request.Request, fp: HTTPResponse, code: int,
            msg: str, headers: HTTPMessage, newurl: str,
        ) -> None:
            return None

    request = urllib.request.Request(
        UPSTREAM_CATALOG, headers={'Accept': 'text/plain', 'User-Agent': 'OneDragon-Mac-CLI'},
    )
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
        payload = response.read(MAX_BYTES + 1)
    today = datetime.now(timezone(timedelta(hours=8))).date()
    return parse_cn_catalog(payload, today)

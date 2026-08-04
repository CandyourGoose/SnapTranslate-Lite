from collections import OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
import json
import threading
import time
from urllib.parse import quote

import requests

from .domain import TranslationFailure, TranslationResult, TranslationSource


GOOGLE_GTX = "https://translate.googleapis.com/translate_a/single"
GOOGLE_CLIENTS5 = "https://clients5.google.com/translate_a/t"
MYMEMORY = "https://api.mymemory.translated.net/get"
LINGVA_BASES = (
    "https://lingva.ml",
    "https://translate.plausibility.cloud",
)
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SnapTranslate/1.0",
}
TRANSLATE_TIMEOUT = (6, 22)
TRANSLATE_RETRIES = 2
CACHE_LIMIT = 2048
AUTO_TRANSLATE_DEADLINE = 8.0

Backend = Callable[[str], str]


def parse_google_clients5_payload(data: object) -> str:
    if isinstance(data, str):
        return data.strip()
    if not isinstance(data, list):
        return ""
    parts: list[str] = []
    for row in data:
        if isinstance(row, (list, tuple)) and row:
            cell = row[0]
            if isinstance(cell, str) and cell:
                parts.append(cell)
        elif isinstance(row, str) and row:
            parts.append(row)
    return "".join(parts).strip()


def mymemory_langpairs(text: str) -> tuple[str, ...]:
    if any("A" <= char <= "Z" or "a" <= char <= "z" for char in text):
        return "en|zh-CN", "Autodetect|zh-CN"
    return "Autodetect|zh-CN", "en|zh-CN"


def is_valid_translation(text: str) -> bool:
    value = text.strip()
    upper = value.upper()
    return (
        bool(value)
        and value != "(无翻译结果)"
        and "MYMEMORY WARNING" not in upper
        and not ("QUOTA" in upper and "EXCEED" in upper)
    )


class HttpBackends:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(HTTP_HEADERS)

    def _get(self, url: str, **kwargs) -> requests.Response:
        last_error: BaseException | None = None
        for attempt in range(TRANSLATE_RETRIES):
            try:
                response = self.session.get(url, timeout=TRANSLATE_TIMEOUT, **kwargs)
                response.raise_for_status()
                return response
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt + 1 < TRANSLATE_RETRIES:
                    time.sleep(0.75 * (attempt + 1))
        if last_error is not None:
            raise last_error
        raise TranslationFailure("翻译请求未完成")

    def google_gtx(self, text: str) -> str:
        response = self._get(
            GOOGLE_GTX,
            params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text},
        )
        data = response.json()
        if not isinstance(data, list) or not data or not isinstance(data[0], list):
            return ""
        return "".join(
            part[0]
            for part in data[0]
            if isinstance(part, list) and part and isinstance(part[0], str)
        ).strip()

    def google_clients5(self, text: str) -> str:
        url = (
            f"{GOOGLE_CLIENTS5}?client=dict-chrome-ex&sl=auto&tl=zh-CN"
            f"&q={quote(text, safe='')}"
        )
        return parse_google_clients5_payload(json.loads(self._get(url).text))

    def mymemory(self, text: str) -> str:
        for langpair in mymemory_langpairs(text):
            try:
                response = self._get(MYMEMORY, params={"q": text, "langpair": langpair})
                data = response.json()
            except (requests.exceptions.RequestException, ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            response_data = data.get("responseData") or {}
            if not isinstance(response_data, dict):
                continue
            candidate = str(response_data.get("translatedText") or "").strip()
            if is_valid_translation(candidate):
                return candidate
            if candidate:
                raise TranslationFailure(candidate)
        return ""

    def lingva(self, base: str, text: str) -> str:
        encoded = quote(text, safe="")
        if len(encoded) > 1400:
            return ""
        try:
            data = self._get(f"{base.rstrip('/')}/api/v1/auto/zh/{encoded}").json()
        except (requests.exceptions.RequestException, ValueError, TypeError):
            return ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("translation") or "").strip()

    def close(self) -> None:
        self.session.close()


class Translator:
    def __init__(self, backends: Mapping[str, Backend] | None = None) -> None:
        self._http: HttpBackends | None = None
        if backends is None:
            self._http = HttpBackends()
            configured: dict[str, Backend] = {
                "google": self._http.google_gtx,
                "google_clients5": self._http.google_clients5,
                "mymemory": self._http.mymemory,
            }
            for base in LINGVA_BASES:
                host = base.split("//", 1)[-1]
                configured[f"lingva:{host}"] = lambda text, endpoint=base: self._http.lingva(
                    endpoint, text
                )
            self._backends = configured
        else:
            self._backends = dict(backends)
        self._executors = {
            name: ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"translate-{name.split(':', 1)[0]}",
            )
            for name in self._backends
        }
        self._cache: OrderedDict[tuple[TranslationSource, str], TranslationResult] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._closed = False

    def _cache_get(self, key: tuple[TranslationSource, str]) -> TranslationResult | None:
        with self._cache_lock:
            result = self._cache.get(key)
            if result is not None:
                self._cache.move_to_end(key)
            return result

    def _cache_put(self, key: tuple[TranslationSource, str], result: TranslationResult) -> None:
        with self._cache_lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_LIMIT:
                self._cache.popitem(last=False)

    def translate(self, text: str, mode: TranslationSource) -> TranslationResult:
        key = (mode, text)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        if self._closed:
            raise TranslationFailure("翻译服务已经关闭")

        if mode is TranslationSource.MYMEMORY:
            backend = self._backends.get("mymemory")
            if backend is None:
                raise TranslationFailure("MyMemory 翻译线路不可用")
            future = self._executors["mymemory"].submit(backend, text)
            try:
                candidate = future.result(timeout=AUTO_TRANSLATE_DEADLINE)
            except BaseException as exc:
                raise TranslationFailure("翻译服务暂时不可用，请检查网络或切换翻译源") from exc
            finally:
                if not future.done():
                    future.cancel()
            if not is_valid_translation(candidate):
                raise TranslationFailure("翻译服务暂时不可用，请检查网络或切换翻译源")
            result = TranslationResult(candidate.strip(), "mymemory")
            self._cache_put(key, result)
            return result

        future_to_name: dict[Future[str], str] = {
            self._executors[name].submit(backend, text): name
            for name, backend in self._backends.items()
        }
        try:
            for future in as_completed(
                future_to_name,
                timeout=AUTO_TRANSLATE_DEADLINE,
            ):
                try:
                    candidate = future.result()
                except BaseException:
                    continue
                if is_valid_translation(candidate):
                    result = TranslationResult(candidate.strip(), future_to_name[future])
                    self._cache_put(key, result)
                    return result
        except FuturesTimeoutError:
            pass
        finally:
            for future in future_to_name:
                if not future.done():
                    future.cancel()
        raise TranslationFailure("翻译服务暂时不可用，请检查网络或切换翻译源")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for executor in self._executors.values():
            executor.shutdown(wait=False, cancel_futures=True)
        if self._http is not None:
            self._http.close()

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from enum import StrEnum
import threading
from typing import Protocol


class SelectionKind(StrEnum):
    TEXT = "text"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class SelectionProbeResult:
    kind: SelectionKind
    text: str = ""


class UnsupportedSelection(RuntimeError):
    pass


class UiaBackend(Protocol):
    def selected_ranges(self, point: tuple[int, int]) -> list[str]: ...


class ComtypesUiaBackend:
    def __init__(self) -> None:
        self._local = threading.local()

    def _automation(self):
        automation = getattr(self._local, "automation", None)
        if automation is not None:
            return automation

        import comtypes.client

        module = comtypes.client.GetModule("UIAutomationCore.dll")
        automation = comtypes.client.CreateObject(
            module.CUIAutomation,
            interface=module.IUIAutomation,
        )
        self._local.module = module
        self._local.automation = automation
        return automation

    def selected_ranges(self, point: tuple[int, int]) -> list[str]:
        try:
            automation = self._automation()
            module = self._local.module
            element = automation.ElementFromPoint(module.tagPOINT(*point))
            if not element:
                raise UnsupportedSelection()
            pattern_unknown = element.GetCurrentPattern(module.UIA_TextPatternId)
            if not pattern_unknown:
                raise UnsupportedSelection()
            pattern = pattern_unknown.QueryInterface(module.IUIAutomationTextPattern)
            ranges = pattern.GetSelection()
            if not ranges:
                return []
            return [
                ranges.GetElement(index).GetText(121)
                for index in range(ranges.Length)
            ]
        except UnsupportedSelection:
            raise
        except Exception as exc:
            raise UnsupportedSelection() from exc


class SelectionProbe:
    def __init__(self, backend: UiaBackend | None = None) -> None:
        self._backend = backend or ComtypesUiaBackend()
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="uia-selection",
        )
        self._closed = False

    def _query(self, point: tuple[int, int]) -> SelectionProbeResult:
        try:
            ranges = self._backend.selected_ranges(point)
        except UnsupportedSelection:
            return SelectionProbeResult(SelectionKind.UNSUPPORTED)
        text = "".join(ranges).strip()[:121]
        if not text:
            return SelectionProbeResult(SelectionKind.EMPTY)
        return SelectionProbeResult(SelectionKind.TEXT, text)

    def query(
        self,
        point: tuple[int, int],
        timeout: float = 0.18,
    ) -> SelectionProbeResult:
        if self._closed:
            return SelectionProbeResult(SelectionKind.UNSUPPORTED)
        future = self._executor.submit(self._query, point)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            return SelectionProbeResult(SelectionKind.TIMEOUT)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

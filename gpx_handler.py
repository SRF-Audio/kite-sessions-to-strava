from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pprint import pformat



class GPXHandler:
    """Light‑weight manager for a directory of ``*.gpx`` files.

    The constructor normalises *gpx_dir* by expanding ``~`` and resolving any
    relative segments, so invocations such as ``GPXHandler('./exports')`` or
    ``GPXHandler('~/Downloads/gpx')`` work exactly as expected.

    Parameters
    ----------
    gpx_dir : str | Path
        Path (absolute or relative) to the directory that should contain GPX
        files.

    Raises
    ------
    FileNotFoundError
        If *gpx_dir* does not exist.
    NotADirectoryError
        If *gpx_dir* exists but is not a directory.
    """

    # XML namespace map (only default GPX namespace needed for our queries)
    _NS = {"g": "http://www.topografix.com/GPX/1/1"}


    def __init__(self, gpx_dir: str | Path) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.directory: Path = Path(gpx_dir).expanduser().resolve()

        if not self.directory.exists():
            raise FileNotFoundError(f"Directory '{self.directory}' does not exist.")
        if not self.directory.is_dir():
            raise NotADirectoryError(f"Path '{self.directory}' is not a directory.")

        # Deterministic ordering helps with testing & reproducibility.
        self.gpx_files: List[Path] = sorted(self.directory.glob("*.gpx"))
        self.total_gpx_files: int = len(self.gpx_files)

        self.logger.info(
            "Discovered %d GPX file%s in '%s'.",
            self.total_gpx_files,
            "" if self.total_gpx_files == 1 else "s",
            self.directory,
        )

    def __iter__(self) -> Iterable[Path]:
        return iter(self.gpx_files)

    def __len__(self) -> int:
        return self.total_gpx_files

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"{self.__class__.__name__}(directory='{self.directory}', "
            f"files={self.total_gpx_files})"
        )

    # ------------------------------------------------------------------
    # GPX parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_iso8601_to_utc(ts: str) -> datetime:
        """Convert an ISO‑8601 string to an *aware* UTC ``datetime``."""

        ts = ts.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).astimezone(timezone.utc)

    @staticmethod
    def _detect_source_app(creator: str | None) -> str:
        """Return ``"Hoolan"``, ``"Woo"``, or ``"Unknown"`` from a GPX *creator* attr."""

        if not creator:
            return "Unknown"
        creator_low = creator.lower()
        if "hoolan" in creator_low:
            return "Hoolan"
        if "woo" in creator_low:
            return "Woo"
        return "Unknown"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def parse_gpx(self, gpx_file: str | Path) -> Dict[str, Any]:
        """Parse *gpx_file* and return a summary dictionary.

        The returned mapping contains:
            ``path`` (Path),
            ``source_app`` (str),
            ``activity_type`` (str),
            ``start_ts_utc`` (datetime, aware, UTC),
            ``end_ts_utc`` (datetime, aware, UTC),
            ``trk_count`` (int),
            ``start_latlng`` (tuple[float, float]),
            ``end_latlng`` (tuple[float, float]).
        """

        path = Path(gpx_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)

        tree = ET.parse(path)
        root = tree.getroot()

        summary: Dict[str, Any] = {"path": path}

        # --------------------------------------------------------------
        # Source application
        # --------------------------------------------------------------
        summary["source_app"] = self._detect_source_app(root.attrib.get("creator"))

        # --------------------------------------------------------------
        # Activity name / type
        # --------------------------------------------------------------
        name_el = root.find("g:metadata/g:name", self._NS)
        summary["activity_type"] = (
            name_el.text.strip() if name_el is not None and name_el.text else "Unknown Activity"
        )

        # --------------------------------------------------------------
        # Start timestamp (metadata > first trkpt fallback)
        # --------------------------------------------------------------
        meta_time_el = root.find("g:metadata/g:time", self._NS)
        if meta_time_el is not None and meta_time_el.text:
            start_ts = self._parse_iso8601_to_utc(meta_time_el.text)
        else:
            first_time_el = root.find("g:trk/g:trkseg/g:trkpt/g:time", self._NS)
            if first_time_el is None or not first_time_el.text:
                raise ValueError(f"No <time> tag found in '{path.name}'.")
            start_ts = self._parse_iso8601_to_utc(first_time_el.text)
        summary["start_ts_utc"] = start_ts

        # --------------------------------------------------------------
        # Track‑point iteration for counts & final values
        # --------------------------------------------------------------
        trkpts = root.findall(".//g:trkpt", self._NS)
        if not trkpts:
            raise ValueError(f"No <trkpt> elements found in '{path.name}'.")

        summary["trk_count"] = len(trkpts)

        first_pt, last_pt = trkpts[0], trkpts[-1]
        summary["start_latlng"] = (
            float(first_pt.attrib["lat"]),
            float(first_pt.attrib["lon"]),
        )
        summary["end_latlng"] = (
            float(last_pt.attrib["lat"]),
            float(last_pt.attrib["lon"]),
        )

        last_time_el = last_pt.find("g:time", self._NS)
        if last_time_el is None or not last_time_el.text:
            raise ValueError(f"Last <trkpt> missing <time> in '{path.name}'.")
        summary["end_ts_utc"] = self._parse_iso8601_to_utc(last_time_el.text)

        return summary

    # ------------------------------------------------------------------
    # Public API – display helpers
    # ------------------------------------------------------------------
    def display_gpx(self, gpx_file: str | Path) -> Dict[str, Any]:
        """Parse *gpx_file*, log & pretty‑print the extracted summary, and return it."""

        summary = self.parse_gpx(gpx_file)
        pretty = pformat(summary, indent=2, compact=False, sort_dicts=False)
        self.logger.info("GPX summary for %s:\n%s", Path(gpx_file).name, pretty)
        return summary

    def display_all_gpx(self) -> List[Dict[str, Any]]:
        """Iterate over all discovered GPX files and pretty‑print each summary."""

        all_summaries: List[Dict[str, Any]] = []
        for path in self.gpx_files:
            all_summaries.append(self.display_gpx(path))
        self.logger.info("Displayed %d GPX summaries from '%s'.", len(all_summaries), self.directory)
        return all_summaries

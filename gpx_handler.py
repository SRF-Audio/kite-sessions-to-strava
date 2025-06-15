from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from pprint import pformat
from typing import Any, Dict, Iterable, List


class GPXHandler:
    """Manage a directory of ``*.gpx`` files and offer quick inspection utilities."""

    # Namespace map **must** include *every* prefix we reference in XPath queries.
    _NS: Dict[str, str] = {
        "g": "http://www.topografix.com/GPX/1/1",
        "gpxtpx": "http://www.garmin.com/xmlschemas/TrackPointExtension/v2",
    }

    # ---------------------------------------------------------------------
    # Construction helpers
    # ---------------------------------------------------------------------
    def __init__(self, gpx_dir: str | Path) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.directory: Path = Path(gpx_dir).expanduser().resolve()

        if not self.directory.exists():
            raise FileNotFoundError(f"Directory '{self.directory}' does not exist.")
        if not self.directory.is_dir():
            raise NotADirectoryError(f"Path '{self.directory}' is not a directory.")

        self.gpx_files: List[Path] = sorted(self.directory.glob("*.gpx"))
        self.logger.info(
            "Discovered %d GPX file%s in '%s'.",
            len(self),
            "" if len(self) == 1 else "s",
            self.directory,
        )

    # ---------------------------------------------------------------------
    # Dunder niceties
    # ---------------------------------------------------------------------
    def __iter__(self) -> Iterable[Path]:
        return iter(self.gpx_files)

    def __len__(self) -> int:  # noqa: D401
        return len(self.gpx_files)

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.__class__.__name__}(directory='{self.directory}', files={len(self)})"

    # ---------------------------------------------------------------------
    # Private utils
    # ---------------------------------------------------------------------
    @staticmethod
    def _parse_iso8601_to_utc(ts: str) -> datetime:
        """Return an *aware* UTC datetime for any RFC 3339 / ISO‑8601 string."""
        ts = ts.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).astimezone(timezone.utc)

    @staticmethod
    def _detect_source_app(creator: str | None) -> str:
        if not creator:
            return "Unknown"
        c = creator.lower()
        if "hoolan" in c:
            return "Hoolan"
        if "woo" in c:
            return "Woo"
        return "Unknown"

    # ---------------------------------------------------------------------
    # Core parsing
    # ---------------------------------------------------------------------
    def parse_gpx(self, gpx_file: str | Path) -> Dict[str, Any]:
        """Extract key session metadata from *gpx_file*."""
        path = Path(gpx_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)

        root = ET.parse(path).getroot()

        summary: Dict[str, Any] = {
            "path": path,
            "source_app": self._detect_source_app(root.get("creator")),
            "activity_type": "Unknown Activity",
        }

        name_el = root.find("g:metadata/g:name", self._NS)
        if name_el is not None and name_el.text:
            summary["activity_type"] = name_el.text.strip()

        meta_time_el = root.find("g:metadata/g:time", self._NS)
        if meta_time_el is not None and meta_time_el.text:
            start_ts = self._parse_iso8601_to_utc(meta_time_el.text)
        else:
            first_time_el = root.find("g:trk/g:trkseg/g:trkpt/g:time", self._NS)
            if first_time_el is None or not first_time_el.text:
                raise ValueError(f"No <time> tag found in '{path.name}'.")
            start_ts = self._parse_iso8601_to_utc(first_time_el.text)
        summary["start_ts_utc"] = start_ts

        trkpts = root.findall(".//g:trkpt", self._NS)
        if not trkpts:
            raise ValueError(f"No <trkpt> elements found in '{path.name}'.")

        summary["trk_count"] = len(trkpts)
        first_pt, last_pt = trkpts[0], trkpts[-1]
        summary["start_latlng"] = (float(first_pt.get("lat")), float(first_pt.get("lon")))
        summary["end_latlng"] = (float(last_pt.get("lat")), float(last_pt.get("lon")))

        last_time_el = last_pt.find("g:time", self._NS)
        if last_time_el is None or not last_time_el.text:
            raise ValueError(f"Last <trkpt> missing <time> in '{path.name}'.")
        summary["end_ts_utc"] = self._parse_iso8601_to_utc(last_time_el.text)

        return summary

    # ---------------------------------------------------------------------
    # Extension‑property inspector
    # ---------------------------------------------------------------------
    def _extension_counts(self, root: ET.Element) -> Dict[str, int]:
        """Return counts of each sub‑tag inside ``<gpxtpx:TrackPointExtension>``."""
        counts: Dict[str, int] = {}
        xpath = ".//g:trkpt/g:extensions/gpxtpx:TrackPointExtension"
        for ext_el in root.findall(xpath, self._NS):
            for child in ext_el:
                tag_local = child.tag.rpartition("}")[2]  # strip namespace
                counts[tag_local] = counts.get(tag_local, 0) + 1
        return counts

    # ---------------------------------------------------------------------
    # Public display helpers
    # ---------------------------------------------------------------------
    def display_gpx(self, gpx_file: str | Path) -> Dict[str, Any]:
        summary = self.parse_gpx(gpx_file)
        self.logger.info("GPX summary for %s:\n%s", Path(gpx_file).name, pformat(summary, indent=2, sort_dicts=False))
        return summary

    def display_unique_trkpt_properties(self, gpx_file: str | Path) -> Dict[str, Any]:
        path = Path(gpx_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)

        root = ET.parse(path).getroot()
        counts = self._extension_counts(root)
        summary = {"file_name": path.name, "unique_extension_properties": counts}
        self.logger.info(
            "Extension property counts for %s:\n%s", path.name, pformat(summary, indent=2, sort_dicts=False)
        )
        return summary

    def display_all_gpx(self) -> List[Dict[str, Any]]:
        """Log a merged core‑metadata + extension‑property summary for every file."""
        combined: List[Dict[str, Any]] = []
        for path in self.gpx_files:
            root = ET.parse(path).getroot()
            meta = self.parse_gpx(path)
            meta["unique_extension_properties"] = self._extension_counts(root)
            self.logger.info("Full summary for %s:\n%s", path.name, pformat(meta, indent=2, sort_dicts=False))
            combined.append(meta)
        self.logger.info("Displayed %d combined summaries from '%s'.", len(combined), self.directory)
        return combined

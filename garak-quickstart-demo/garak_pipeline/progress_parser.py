"""Progress parser for Garak scan output"""

import re
import logging
from typing import Dict, Set, List, Optional

logger = logging.getLogger(__name__)


class ProgressParser:
    """Reusable progress parser for Garak scan output"""

    def __init__(self, job_id: str, job_metadata: Dict):
        self.job_id = job_id
        self.job_metadata = job_metadata
        self.total_probes = 0
        self.completed_probes = 0
        self.current_probe = None
        self.seen_probes: Set[str] = set()
        self.probe_list: List[str] = []

        # Patterns
        self.queue_pattern = re.compile(r'(?:🕵️\s*)?queue of probes:\s*(.+)', re.IGNORECASE)
        self.probe_result_pattern = re.compile(
            r'^(\S+)\s+(\S+):\s+(PASS|FAIL)\s+ok on\s+(\d+)/\s*(\d+)\s*(?:\(failure rate:\s*([\d.]+)%\))?',
            re.IGNORECASE
        )
        self.tqdm_pattern = re.compile(
            r'probes\.(\S+):\s+(\d+)%\|[^\|]*\|\s+(\d+)/(\d+)\s+\[([0-9:]+)<([0-9:]+)(?:,\s+([0-9.]+)(s/it|it/s))?',
            re.IGNORECASE
        )
        self.complete_pattern = re.compile(r'(?:✔️\s*)?garak run complete in ([\d.]+)s', re.IGNORECASE)

    @staticmethod
    def strip_ansi(text: str) -> str:
        """Remove ANSI escape codes from text"""
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        return ansi_escape.sub('', text)

    @staticmethod
    def time_to_seconds(time_str: str) -> int:
        """Convert time string in HH:MM:SS format to seconds"""
        parts = time_str.split(':')
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            logger.debug(f"Unexpected time format: {time_str}")
        return 0

    def parse_line(self, line: str) -> Optional[Dict]:
        """Parse a line and update metadata, return progress if updated"""
        line_clean = self.strip_ansi(line.strip())

        if not line_clean:
            return None

        # Queue pattern
        if match := self.queue_pattern.search(line_clean):
            probes_str = match.group(1)
            self.probe_list = [p.strip() for p in probes_str.split(',')]
            self.total_probes = len(self.probe_list)
            self.current_probe = self.probe_list[0] if self.probe_list else None
            logger.info(f"Job {self.job_id}: {self.total_probes} probes queued")
            self.job_metadata[self.job_id]["total_probes"] = self.total_probes
            self.job_metadata[self.job_id]["probe_list"] = self.probe_list
            self.job_metadata[self.job_id]["progress"] = {
                "percent": 0.0,
                "completed_probes": self.completed_probes,
                "total_probes": self.total_probes,
                "current_probe": self.current_probe,
            }
            return self.job_metadata[self.job_id].get("progress")

        # tqdm pattern
        elif match := self.tqdm_pattern.search(line_clean):
            probe_name = match.group(1)
            probe_percent = int(match.group(2))
            current_attempts = int(match.group(3))
            total_attempts = int(match.group(4))
            elapsed_str = match.group(5)
            remaining_str = match.group(6)
            speed_value = match.group(7) if len(match.groups()) >= 7 else None
            speed_unit = match.group(8) if len(match.groups()) >= 8 else None

            probe_elapsed_seconds = self.time_to_seconds(elapsed_str)
            probe_eta_seconds = self.time_to_seconds(remaining_str)

            # Calculate overall progress
            if self.total_probes > 0:
                probe_weight = 100.0 / self.total_probes
                base_progress = self.completed_probes * probe_weight
                current_probe_contribution = (probe_percent / 100.0) * probe_weight
                overall_percent = base_progress + current_probe_contribution
            else:
                overall_percent = 0

            # update
            self.job_metadata[self.job_id]["progress"] = {
                "percent": round(overall_percent, 1),
                "completed_probes": self.completed_probes,
                "total_probes": self.total_probes,
                "current_probe": probe_name,
                "current_probe_progress": {
                    "probe": probe_name,
                    "percent": probe_percent,
                    "attempts_current": current_attempts,
                    "attempts_total": total_attempts,
                    "probe_elapsed_seconds": probe_elapsed_seconds,
                    "probe_eta_seconds": probe_eta_seconds,
                    "speed": f"{speed_value}{speed_unit}" if speed_value else None
                }
            }
            return self.job_metadata[self.job_id].get("progress")

        # Probe result pattern
        elif match := self.probe_result_pattern.match(line_clean):
            probe_name = match.group(1)
            detector = match.group(2)
            status = match.group(3)
            passed = int(match.group(4))
            total_attempts = int(match.group(5))
            failure_rate = float(match.group(6)) if match.group(6) else 0.0

            if probe_name not in self.seen_probes:
                self.seen_probes.add(probe_name)
                self.completed_probes = len(self.seen_probes)

                if self.completed_probes < self.total_probes and self.probe_list:
                    for p in self.probe_list:
                        if p not in self.seen_probes:
                            self.current_probe = p
                            break

            progress_pct = (self.completed_probes / self.total_probes * 100) if self.total_probes > 0 else 0

            self.job_metadata[self.job_id]["progress"] = {
                "percent": round(progress_pct, 1),
                "completed_probes": self.completed_probes,
                "total_probes": self.total_probes,
                "current_probe": self.current_probe,
                "last_result": {
                    "probe": probe_name,
                    "detector": detector,
                    "status": status,
                    "passed": passed,
                    "total_attempts": total_attempts,
                    "failure_rate": failure_rate
                }
            }
            return self.job_metadata[self.job_id].get("progress")

        # Complete pattern
        elif match := self.complete_pattern.search(line_clean):
            duration = float(match.group(1))
            if "progress" in self.job_metadata[self.job_id]:
                self.job_metadata[self.job_id]["progress"]["percent"] = 100.0
                self.job_metadata[self.job_id]["progress"]["completed_probes"] = self.total_probes
                self.job_metadata[self.job_id]["progress"].pop("current_probe_progress", None)
            self.job_metadata[self.job_id]["duration_seconds"] = duration
            logger.info(f"Job {self.job_id}: Completed in {duration}s")
            return self.job_metadata[self.job_id].get("progress")

        return None


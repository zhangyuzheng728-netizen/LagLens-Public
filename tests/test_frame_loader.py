import json
import tempfile
import unittest

from pathlib import Path

import telemetry
from frame_stats import compute_stats
from frame_viewer import load_frames


HEADER = (
    "Application,ProcessID,SwapChainAddress,"
    "CPUStartTime,FrameTime,DisplayedTime\n"
)

QPC_HEADER = (
    "Application,ProcessID,SwapChainAddress,"
    "CPUStartQPCTime,FrameTime,DisplayedTime\n"
)


def row(
    application="game.exe",
    pid="100",
    swap_chain="0x1",
    start="1.0",
    frame_time="16.7",
    displayed="16.0",
):
    return (
        f"{application},{pid},{swap_chain},"
        f"{start},{frame_time},{displayed}\n"
    )


class LoadFramesTests(unittest.TestCase):

    def _write(self, folder, text, name="frames.csv"):

        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_loads_largest_swap_chain_and_sorts_by_time(self):

        with tempfile.TemporaryDirectory() as folder:

            # CPUStartTime is in milliseconds.  Both chains present at
            # the same time, so they must not be merged.
            path = self._write(
                folder,
                HEADER
                # Swap chain A has three rows, deliberately not sorted.
                + row(start="3000", frame_time="30.0")
                + row(start="1000", frame_time="10.0")
                + row(start="2000", frame_time="20.0")
                # Swap chain B has two rows.
                + row(swap_chain="0x2", start="1000")
                + row(swap_chain="0x2", start="2000"),
            )

            frames = load_frames(path)

            self.assertEqual(len(frames), 3)
            self.assertEqual(
                [frame["duration"] for frame in frames],
                [10.0, 20.0, 30.0],
            )
            self.assertTrue(
                all(
                    frame["row"]["SwapChainAddress"] == "0x1"
                    for frame in frames
                )
            )

    def test_sequential_swap_chains_are_merged(self):
        """A recreated swap chain must not hide the other frames.

        A player can recreate its swap chain when switching videos, so a
        capture may contain several chains one after another.
        """

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + row(swap_chain="0x1", start="1000")
                + row(swap_chain="0x1", start="2000")
                + row(swap_chain="0x1", start="3000")
                # New chain, created after the first one ended.
                + row(swap_chain="0x2", start="5000")
                + row(swap_chain="0x2", start="6000"),
            )

            frames = load_frames(path)

            self.assertEqual(len(frames), 5)
            self.assertEqual(
                [frame["time"] for frame in frames],
                [1000.0, 2000.0, 3000.0, 5000.0, 6000.0],
            )

    def test_legacy_frames_expose_relative_timebase(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER + row(start="1000") + row(start="1016.7"),
            )

            frames = load_frames(path)

            self.assertEqual(
                frames[0]["timebase_kind"],
                "relative",
            )
            self.assertEqual(
                frames[0]["sync_quality"],
                "exact_relative",
            )
            self.assertEqual(
                frames[0]["raw_time"],
                1000.0,
            )
            self.assertFalse(
                frames[0]["absolute_mapping_trusted"]
            )

    def test_qpc_frames_without_sidecar_use_first_frame_origin(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                QPC_HEADER
                + row(start="10016.7", frame_time="16.7")
                + row(start="10033.4", frame_time="16.7"),
            )

            frames = load_frames(path)

            self.assertEqual(len(frames), 2)
            self.assertAlmostEqual(
                frames[0]["time"],
                0.0,
            )
            self.assertAlmostEqual(
                frames[1]["time"],
                16.7,
            )
            self.assertAlmostEqual(
                frames[0]["raw_time"],
                10016.7,
            )
            self.assertEqual(
                frames[0]["timebase_kind"],
                "qpc_ms",
            )
            self.assertEqual(
                frames[0]["sync_quality"],
                "inferred_qpc",
            )
            self.assertFalse(
                frames[0]["absolute_mapping_trusted"]
            )

            stats = compute_stats(frames)

            self.assertEqual(stats.frame_count, 2)
            self.assertGreater(stats.duration_s, 0.0)

    def test_qpc_frames_with_sidecar_use_capture_start_origin(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                QPC_HEADER
                + row(start="10016.7", frame_time="16.7")
                + row(start="10033.4", frame_time="16.7"),
            )

            telemetry.telemetry_path(path).write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "metadata",
                                "schema_version": 1,
                                "capture": {
                                    "csv_name": path.name,
                                    "started_monotonic_ns": (
                                        10_000_000_000
                                    ),
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "timebase",
                                "frame_timebase": {
                                    "kind": "qpc_ms",
                                    "raw_column": (
                                        "CPUStartQPCTime"
                                    ),
                                    "origin_kind": (
                                        "capture_start"
                                    ),
                                    "origin_qpc_ms": 10_000.0,
                                    "capture_started_monotonic_ns": (
                                        10_000_000_000
                                    ),
                                    "sync_quality": (
                                        "verified_qpc"
                                    ),
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "end",
                                "reason": "finished",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            frames = load_frames(path)

            self.assertEqual(len(frames), 2)
            self.assertAlmostEqual(
                frames[0]["time"],
                16.7,
            )
            self.assertAlmostEqual(
                frames[1]["time"],
                33.4,
            )
            self.assertEqual(
                frames[0]["timebase_kind"],
                "qpc_ms",
            )
            self.assertEqual(
                frames[0]["sync_quality"],
                "verified_qpc",
            )
            self.assertTrue(
                frames[0]["absolute_mapping_trusted"]
            )

    def test_displayed_flag(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + row(displayed="16.0")
                + row(start="2.0", displayed="NA"),
            )

            frames = load_frames(path)

            self.assertTrue(frames[0]["displayed"])
            self.assertFalse(frames[1]["displayed"])

    def test_invalid_rows_are_skipped(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + row(frame_time="not-a-number")
                + row(start="2.0", frame_time="0")
                + row(start="3.0", frame_time="16.0"),
            )

            frames = load_frames(path)

            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0]["duration"], 16.0)

    def test_missing_required_columns_raises(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                "Application,FrameTime\n"
                "game.exe,16.7\n",
            )

            with self.assertRaises(ValueError):
                load_frames(path)

    def test_header_only_raises(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(folder, HEADER)

            with self.assertRaises(ValueError):
                load_frames(path)

    def test_utf8_bom_is_accepted(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "bom.csv"

            path.write_text(
                HEADER + row(),
                encoding="utf-8-sig",
            )

            frames = load_frames(path)

            self.assertEqual(len(frames), 1)


if __name__ == "__main__":
    unittest.main()

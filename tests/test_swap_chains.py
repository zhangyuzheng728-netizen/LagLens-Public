"""P2-3 part 1: swap-chain discovery and selection.

The algorithm must:

* keep every original CSV row untouched
* group frames by process + swap chain
* split reused identifiers at long inactivity gaps
* merge only chains that never presented at the same time
* recommend the likely primary view with an explanation
* report "uncertain" when candidates are too close
* accept a manual chain or sequential-group override
"""

import copy
import csv
import tempfile
import unittest

from pathlib import Path

import capture_core
import frame_stats
import swap_chains
from frame_viewer import load_frames

def make_row(
    application="game.exe",
    pid="100",
    swap_chain="0x1",
    start=0.0,
    frame_time=16.7,
    displayed="16.0",
):

    return {
        "Application": application,
        "ProcessID": pid,
        "SwapChainAddress": swap_chain,
        "CPUStartTime": str(start),
        "FrameTime": str(frame_time),
        "DisplayedTime": displayed,
    }


def frames(
    swap_chain="0x1",
    count=5,
    start=0.0,
    step=16.0,
    application="game.exe",
    pid="100",
):

    return [
        make_row(
            application=application,
            pid=pid,
            swap_chain=swap_chain,
            start=start + index * step,
            frame_time=step,
        )
        for index in range(count)
    ]


def ids(selection):

    return [
        (chain.swap_chain, chain.segment)
        for chain in selection.selected.chains
    ]


class IndexTests(unittest.TestCase):

    def test_groups_by_process_and_swap_chain(self):

        rows = (
            frames("0x1", 3)
            + frames("0x2", 2)
            + frames("0x1", 2, pid="200")
        )

        index = swap_chains.build_index(rows)

        self.assertEqual(len(index.chains), 3)
        self.assertEqual(index.total_frames, 7)

        keys = {
            (
                chain.application,
                chain.process_id,
                chain.swap_chain,
            )
            for chain in index.chains
        }

        self.assertEqual(
            keys,
            {
                ("game.exe", "100", "0x1"),
                ("game.exe", "100", "0x2"),
                ("game.exe", "200", "0x1"),
            },
        )

    def test_reused_identifier_is_split_at_a_long_gap(self):

        rows = (
            frames("0x1", 5, start=0.0)
            + frames("0x1", 5, start=40000.0)
        )

        index = swap_chains.build_index(rows)

        self.assertEqual(len(index.chains), 2)
        self.assertEqual(
            [chain.segment for chain in index.chains],
            [0, 1],
        )
        self.assertTrue(
            all(
                chain.swap_chain == "0x1"
                for chain in index.chains
            )
        )

    def test_original_rows_are_not_modified(self):

        rows = frames("0x1", 5)
        snapshot = copy.deepcopy(rows)

        index = swap_chains.build_index(rows)
        swap_chains.recommend(index)

        self.assertEqual(rows, snapshot)

        for record in index.frames:

            self.assertIs(record.row, rows[record.index])

    def test_missing_required_columns_raise(self):

        with self.assertRaises(ValueError):

            swap_chains.build_index(
                [{"Application": "game.exe"}]
            )

    def test_no_valid_frames_raises(self):

        with self.assertRaises(ValueError):

            swap_chains.build_index(
                [
                    make_row(frame_time="NA"),
                    make_row(frame_time="0"),
                ]
            )


class RecommendationTests(unittest.TestCase):

    def test_single_chain_is_recommended(self):

        selection = swap_chains.recommend(
            swap_chains.build_index(
                frames("0x1", 5)
            )
        )

        self.assertEqual(selection.frame_count, 5)
        self.assertEqual(ids(selection), [("0x1", 0)])
        self.assertEqual(selection.confidence, "high")
        self.assertFalse(selection.uncertain)
        self.assertFalse(selection.overridden)
        self.assertIn(
            "one swap chain",
            selection.reason.lower(),
        )

    def test_sequential_replacement_is_merged(self):

        rows = (
            frames("0x1", 3, start=1000.0)
            + frames("0x2", 3, start=1500.0)
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(selection.frame_count, 6)
        self.assertEqual(len(selection.selected.chains), 2)
        self.assertTrue(selection.selected.merged)
        self.assertEqual(selection.confidence, "high")
        self.assertIn("sequential", selection.reason.lower())

        times = [frame.time_ms for frame in selection.frames]

        self.assertEqual(times, sorted(times))

    def test_concurrent_chains_select_only_one(self):

        # Real spans (seconds) so the overlap is larger than the
        # 250 ms transition tolerance.
        rows = (
            frames("0x1", 100, start=0.0)
            + frames("0x2", 50, start=0.0)
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(len(selection.selected.chains), 1)
        self.assertEqual(selection.selected.chains[0].swap_chain, "0x1")
        self.assertEqual(selection.frame_count, 100)
        self.assertTrue(selection.selected.concurrent_activity)
        self.assertIn("concurrent", selection.reason.lower())

    def test_overlap_just_below_tolerance_is_merged(self):

        rows = (
            frames("0x1", 11, start=0.0, step=100.0)
            + frames("0x2", 11, start=800.0, step=100.0)
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(len(selection.selected.chains), 2)
        self.assertTrue(selection.selected.merged)

    def test_overlap_just_above_tolerance_is_concurrent(self):

        rows = (
            frames("0x1", 11, start=0.0, step=100.0)
            + frames("0x2", 11, start=700.0, step=100.0)
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(len(selection.selected.chains), 1)

    def test_overlap_equal_to_tolerance_is_sequential(self):

        rows = (
            frames("0x1", 11, start=0.0, step=100.0)
            + frames("0x2", 11, start=750.0, step=100.0)
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(len(selection.selected.chains), 2)

    def test_auxiliary_overlay_does_not_block_main_chain_merge(self):
        """An overlay that overlaps two sequential main chains must not
        prevent the two main chains from being merged."""

        main_a = frames("0xA", 300, start=0.0, step=33.3)
        main_b = frames("0xB", 300, start=10000.0, step=33.3)
        overlay = frames("0xX", 50, start=0.0, step=400.0)

        selection = swap_chains.recommend(
            swap_chains.build_index(
                main_a + main_b + overlay
            )
        )

        selected_ids = {
            chain.swap_chain
            for chain in selection.selected.chains
        }

        self.assertEqual(selected_ids, {"0xA", "0xB"})
        self.assertEqual(selection.frame_count, 600)
        self.assertTrue(selection.selected.merged)
        self.assertIn(
            "concurrent",
            selection.reason.lower(),
        )
        self.assertIn(
            "sequential",
            selection.reason.lower(),
        )

        candidate_ids = {
            chain.swap_chain
            for group in selection.candidates
            for chain in group.chains
        }

        self.assertIn("0xX", candidate_ids)

    def test_close_candidates_are_reported_as_uncertain(self):

        # Same count, same span, same tail activity -> equal scores.
        rows = (
            frames("0x1", 100, start=0.0)
            + frames("0x2", 100, start=10.0)
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertTrue(selection.uncertain)
        self.assertEqual(selection.confidence, "uncertain")
        self.assertEqual(len(selection.selected.chains), 1)
        self.assertIn("uncertain", selection.reason.lower())

    def test_long_inactive_gap_is_kept_and_reported(self):
        """A paused game is still the same chain; segments stay in the
        group and the long activity hole is reported."""

        rows = (
            frames("0x1", 7, start=0.0)
            + frames("0x1", 7, start=40000.0)
        )

        index = swap_chains.build_index(rows)
        selection = swap_chains.recommend(index)

        self.assertEqual(len(index.chains), 2)
        self.assertEqual(len(selection.selected.chains), 2)
        self.assertEqual(selection.frame_count, 14)

        times = {
            frame.time_ms
            for frame in selection.frames
        }

        self.assertIn(0.0, times)
        self.assertIn(40000.0, times)
        self.assertIn("inactive", selection.reason.lower())

    def test_activity_coverage_uses_buckets_not_span(self):

        rows = frames("0x1", 2, start=0.0, step=60000.0)

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertLess(
            selection.activity_coverage,
            0.1,
        )
        self.assertIn(
            "activity coverage",
            selection.reason.lower(),
        )

    def test_dense_activity_beats_sparse_same_span(self):

        sparse = [
            make_row(swap_chain="0x1", start=start)
            for start in (0.0, 5000.0, 60000.0)
        ]

        dense = frames(
            "0x2",
            61,
            start=0.0,
            step=1000.0,
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(sparse + dense)
        )

        self.assertEqual(
            selection.selected.chains[0].swap_chain,
            "0x2",
        )
        self.assertGreater(
            selection.activity_coverage,
            0.9,
        )

    def test_missing_or_zero_identifier_is_low_confidence(self):

        rows = frames("0x0", 10, start=0.0)

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(selection.confidence, "low")
        self.assertFalse(
            selection.selected.chains[0].identifier_ok
        )
        self.assertIn(
            "identifier",
            selection.reason.lower(),
        )

    def test_zero_chain_is_selected_but_never_high_confidence(self):

        rows = (
            frames("0x0", 400, start=0.0)
            + frames("0xAA", 20, start=0.0)
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        # The dominant chain is not hidden just because its address
        # is unreliable; the low confidence is the warning.
        self.assertEqual(
            selection.selected.chains[0].swap_chain,
            "0x0",
        )
        self.assertEqual(selection.confidence, "low")
        self.assertIn(
            "identifier",
            selection.reason.lower(),
        )

    def test_reliable_identifier_alone_is_not_high_confidence(self):

        rows = (
            frames("0x0", 100, start=0.0)
            + frames("0xAA", 100, start=0.0)
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(
            selection.selected.chains[0].swap_chain,
            "0xAA",
        )
        self.assertEqual(selection.confidence, "medium")
        self.assertIn(
            "identifier",
            selection.reason.lower(),
        )

    def test_longest_span_wins_over_most_frames(self):
        """Requirement: most frames is not automatically the main view."""

        rows = (
            frames("0x1", 100, start=0.0, step=600.0)   # 0..59.4 s
            + frames(
                "0x2",
                1000,
                start=0.0,
                step=1.0,
            )  # 1 s burst
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(
            selection.selected.chains[0].swap_chain,
            "0x1",
        )

    def test_multiple_processes_use_coverage_not_frame_count(self):

        rows = (
            frames(
                "0x1",
                100,
                start=0.0,
                step=600.0,
                pid="100",
            )
            + frames(
                "0x2",
                1000,
                start=0.0,
                step=1.0,
                pid="200",
            )
        )

        selection = swap_chains.recommend(
            swap_chains.build_index(rows)
        )

        self.assertEqual(selection.selected.process_id, "100")
        self.assertIn("100", selection.reason)


class OverrideTests(unittest.TestCase):

    def setUp(self):

        self.index = swap_chains.build_index(
            frames("0x1", 100, start=0.0)
            + frames("0x2", 50, start=0.0)
        )

    def test_manual_chain_override(self):

        selection = swap_chains.recommend(
            self.index,
            swap_chains.SelectionOverride(
                swap_chains=("0x2",)
            ),
        )

        self.assertTrue(selection.overridden)
        self.assertEqual(selection.confidence, "user")
        self.assertFalse(selection.uncertain)
        self.assertEqual(ids(selection), [("0x2", 0)])
        self.assertEqual(selection.frame_count, 50)
        self.assertIn("user", selection.reason.lower())

    def test_sequential_group_override(self):

        index = swap_chains.build_index(
            frames("0x1", 3, start=1000.0)
            + frames("0x2", 3, start=1500.0)
        )

        selection = swap_chains.recommend(
            index,
            swap_chains.SelectionOverride(
                swap_chains=("0x1", "0x2")
            ),
        )

        self.assertTrue(selection.overridden)
        self.assertEqual(selection.frame_count, 6)
        self.assertEqual(len(selection.selected.chains), 2)

    def test_overlapping_override_is_rejected(self):

        with self.assertRaises(ValueError):

            swap_chains.recommend(
                self.index,
                swap_chains.SelectionOverride(
                    swap_chains=("0x1", "0x2")
                ),
            )

    def test_unknown_override_is_rejected(self):

        with self.assertRaises(ValueError):

            swap_chains.recommend(
                self.index,
                swap_chains.SelectionOverride(
                    swap_chains=("0xNOPE",)
                ),
            )

    def test_override_selects_one_reused_segment(self):

        index = swap_chains.build_index(
            frames("0x1", 5, start=0.0)
            + frames("0x1", 5, start=40000.0)
        )

        selection = swap_chains.recommend(
            index,
            swap_chains.SelectionOverride(
                swap_chains=(("0x1", 1),)
            ),
        )

        self.assertTrue(selection.overridden)
        self.assertEqual(selection.frame_count, 5)
        self.assertTrue(
            all(
                frame.time_ms >= 40000.0
                for frame in selection.frames
            )
        )
        self.assertIn(
            "segment 2",
            selection.reason,
        )

    def test_override_can_select_all_segments_by_address(self):

        index = swap_chains.build_index(
            frames("0x1", 5, start=0.0)
            + frames("0x1", 5, start=40000.0)
        )

        selection = swap_chains.recommend(
            index,
            swap_chains.SelectionOverride(
                swap_chains=("0x1",)
            ),
        )

        self.assertEqual(selection.frame_count, 10)

    def test_override_unknown_segment_is_rejected(self):

        index = swap_chains.build_index(
            frames("0x1", 5, start=0.0)
            + frames("0x1", 5, start=40000.0)
        )

        with self.assertRaises(ValueError):

            swap_chains.recommend(
                index,
                swap_chains.SelectionOverride(
                    swap_chains=(("0x1", 7),)
                ),
            )

    def test_override_mixed_segment_and_other_chain(self):

        index = swap_chains.build_index(
            frames("0x1", 5, start=0.0)
            + frames("0x1", 5, start=40000.0)
            + frames("0x2", 5, start=80000.0)
        )

        selection = swap_chains.recommend(
            index,
            swap_chains.SelectionOverride(
                swap_chains=(("0x1", 0), "0x2")
            ),
        )

        self.assertEqual(selection.frame_count, 10)
        self.assertEqual(len(selection.selected.chains), 2)

    def test_restoring_automatic_selection(self):

        automatic = swap_chains.recommend(self.index)

        swap_chains.recommend(
            self.index,
            swap_chains.SelectionOverride(
                swap_chains=("0x2",)
            ),
        )

        restored = swap_chains.recommend(self.index)

        self.assertEqual(
            ids(automatic),
            ids(restored),
        )
        self.assertFalse(restored.overridden)


class ChoiceTests(unittest.TestCase):

    def test_choices_include_merged_group_and_individual_chains(self):

        index = swap_chains.build_index(
            frames("0x1", 3, start=1000.0)
            + frames("0x2", 3, start=1500.0)
        )

        choices = swap_chains.list_choices(index)
        labels = [choice.label for choice in choices]

        self.assertTrue(
            any("2 chains" in label for label in labels)
        )
        self.assertTrue(
            any("0x1" in label for label in labels)
        )
        self.assertTrue(
            any("0x2" in label for label in labels)
        )
        self.assertTrue(
            all(
                "frames" in label and " s" in label
                for label in labels
            )
        )

    def test_choices_distinguish_reused_segments(self):

        index = swap_chains.build_index(
            frames("0x1", 5, start=0.0)
            + frames("0x1", 5, start=40000.0)
        )

        labels = [
            choice.label
            for choice in swap_chains.list_choices(index)
        ]

        self.assertTrue(
            any("segment 2" in label for label in labels)
        )

    def test_concurrent_choices_have_no_merged_group(self):

        index = swap_chains.build_index(
            frames("0x1", 100, start=0.0)
            + frames("0x2", 50, start=0.0)
        )

        choices = swap_chains.list_choices(index)

        self.assertEqual(len(choices), 2)
        self.assertTrue(
            all(
                len(choice.group.chains) == 1
                for choice in choices
            )
        )


class ReasonPartTests(unittest.TestCase):

    def test_single_chain_reason_parts(self):

        selection = swap_chains.recommend(
            swap_chains.build_index(
                frames("0x1", 5)
            )
        )

        keys = [
            key for key, _ in selection.reason_parts
        ]

        self.assertIn(
            "chain.reason.frames_one",
            keys,
        )
        self.assertIn(
            "chain.reason.coverage",
            keys,
        )
        self.assertIn(
            "chain.reason.process",
            keys,
        )
        self.assertIn(
            "one swap chain",
            selection.reason,
        )

    def test_sequential_and_uncertain_parts(self):

        sequential = swap_chains.recommend(
            swap_chains.build_index(
                frames("0x1", 3, start=1000.0)
                + frames("0x2", 3, start=1500.0)
            )
        )

        keys = [
            key for key, _ in sequential.reason_parts
        ]

        self.assertIn(
            "chain.reason.sequential",
            keys,
        )

        ambiguous = swap_chains.recommend(
            swap_chains.build_index(
                frames("0x1", 100, start=0.0)
                + frames("0x2", 100, start=10.0)
            )
        )

        keys = [
            key for key, _ in ambiguous.reason_parts
        ]

        self.assertIn(
            "chain.reason.uncertain",
            keys,
        )

    def test_override_reason_parts(self):

        index = swap_chains.build_index(
            frames("0x1", 100, start=0.0)
            + frames("0x2", 50, start=0.0)
        )

        selection = swap_chains.recommend(
            index,
            swap_chains.SelectionOverride(
                swap_chains=("0x2",)
            ),
        )

        self.assertEqual(
            selection.reason_parts[0][0],
            "chain.reason.user",
        )
        self.assertIn(
            "User selection",
            selection.reason,
        )


class CompatibilityTests(unittest.TestCase):

    def test_legacy_frames_feed_the_statistics_engine(self):

        selection = swap_chains.recommend(
            swap_chains.build_index(
                frames("0x1", 20, step=16.7)
            )
        )

        legacy = selection.legacy_frames()

        self.assertEqual(len(legacy), 20)
        self.assertIn("row", legacy[0])

        stats = frame_stats.compute_stats(legacy)

        self.assertEqual(stats.frame_count, 20)

    def test_load_frames_still_returns_legacy_dicts(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "capture.csv"
            header = (
                "Application,ProcessID,SwapChainAddress,"
                "CPUStartTime,FrameTime,DisplayedTime\n"
            )

            body = "".join(
                f"game.exe,100,0x1,{1000 + i * 16},16.0,16.0\n"
                for i in range(5)
            )

            path.write_text(
                header + body,
                encoding="utf-8",
            )

            loaded = load_frames(path)

            self.assertEqual(len(loaded), 5)
            self.assertEqual(loaded[0]["duration"], 16.0)
            self.assertIn("row", loaded[0])

            validation = capture_core.validate_capture(path)

            self.assertTrue(validation.ok)
            self.assertEqual(validation.valid_frames, 5)

    def test_synthetic_four_chain_capture(self):

        rows = [
            row
            for index, count in enumerate((380, 381, 380, 382))
            for row in frames(
                swap_chain=f"0x{index + 1}",
                count=count,
                start=index * 6400.0,
            )
        ]

        index = swap_chains.build_index(rows)
        selection = swap_chains.recommend(index)

        self.assertEqual(len(index.chains), 4)
        self.assertEqual(len(selection.selected.chains), 4)
        self.assertTrue(selection.selected.merged)
        self.assertEqual(selection.frame_count, 1523)
        self.assertEqual(selection.confidence, "high")

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.csv"
            with path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            loaded = load_frames(path)

        self.assertEqual(len(loaded), 1523)


if __name__ == "__main__":
    unittest.main()

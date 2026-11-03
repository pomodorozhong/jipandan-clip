import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jipandan.core.round_backups import MANIFEST, backup_data, backup_file, missing_backups, round_backup_folder
from jipandan.core.round_files import build_round_file, build_update_file

from test_round_files import RECORDING, SOURCE, clip, finished_round


def round_file(seed="s1", number=2, recording=RECORDING):
    item = finished_round(seed=seed, number=number, roles={"1": "top"})
    return build_round_file(item, recording, SOURCE, {"1": clip(1, 1000, 2000)}, {}, [], [], 0, 1)


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


class RoundBackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "round-backups"
        self.sha = RECORDING["sha256"]

    def files(self, seed="s1"):
        return sorted(path.name for path in round_backup_folder(self.root, self.sha, seed).iterdir())

    def test_a_copy_is_stored_by_recording_and_round_and_says_where_it_came_from(self):
        content = encoded(round_file())
        path = backup_file(self.root, "a.round-02.json", content, "/project/a.round-02.json")
        self.assertEqual(path, self.root / self.sha / "s1" / "a.round-02.json")
        self.assertEqual(path.read_bytes(), content)
        entry = json.loads((path.parent / MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual((entry["name"], entry["kind"], entry["round"], entry["source"]),
                         ("a.round-02.json", "round", 2, "/project/a.round-02.json"))
        self.assertEqual(missing_backups(self.root, self.sha, "s1", ["a.round-02.json", "other.json"]), ["other.json"])

    def test_backing_up_the_same_file_again_changes_nothing(self):
        content = encoded(round_file())
        backup_file(self.root, "a.json", content)
        manifest = (self.root / self.sha / "s1" / MANIFEST).read_bytes()
        backup_file(self.root, "a.json", content)
        self.assertEqual(self.files(), ["a.json", MANIFEST])
        self.assertEqual((self.root / self.sha / "s1" / MANIFEST).read_bytes(), manifest)

    def test_parsed_json_matches_the_bytes_of_the_file_beside_the_recording(self):
        data = round_file()
        first = backup_file(self.root, "a.json", encoded(data))
        self.assertEqual(backup_data(self.root, "a.json", data), first)
        self.assertEqual(self.files(), ["a.json", MANIFEST])

    def test_a_different_file_under_a_taken_name_never_replaces_it(self):
        first = encoded(round_file())
        second = encoded(round_file(number=3))
        kept = backup_file(self.root, "a.json", first)
        other = backup_file(self.root, "a.json", second)
        self.assertNotEqual(kept, other)
        self.assertEqual((kept.read_bytes(), other.read_bytes()), (first, second))

    def test_rounds_with_one_number_and_recordings_with_one_name_stay_apart(self):
        first = backup_file(self.root, "a.round-01.json", encoded(round_file(seed="s1", number=1)))
        reused = backup_file(self.root, "a.round-01.json", encoded(round_file(seed="s2", number=1)))
        same_name = backup_file(self.root, "a.round-01.json", encoded(round_file(
            seed="s1", number=1, recording={**RECORDING, "sha256": "b" * 64})))
        self.assertEqual(len({first, reused, same_name}), 3)
        self.assertTrue(all(path.is_file() for path in (first, reused, same_name)))

    def test_update_files_are_kept_beside_their_round(self):
        update = build_update_file(finished_round(), self.sha, 1, 1, 2, [], [])
        path = backup_file(self.root, "a.update-01.json", encoded(update))
        self.assertEqual(path.parent, self.root / self.sha / "s1")

    def test_a_file_that_is_not_a_valid_round_file_is_refused(self):
        for content in (b"not json", b"{}", encoded({**round_file(), "changes": "broken"})):
            with self.subTest(content=content[:12]), self.assertRaises(ValueError):
                backup_file(self.root, "a.json", content)
        self.assertFalse(self.root.exists())

    def test_a_file_cannot_choose_a_path_outside_the_backups(self):
        with self.assertRaises(ValueError):
            backup_file(self.root, "a.json", encoded(round_file(seed="../../escape")))
        escaped = backup_file(self.root, "../../a.json", encoded(round_file()))
        self.assertEqual(escaped.parent, self.root / self.sha / "s1")

    def test_an_interrupted_write_leaves_earlier_backups_and_no_partial_file(self):
        first = encoded(round_file())
        kept = backup_file(self.root, "a.json", first)
        with patch("jipandan.core.round_backups.os.link", side_effect=OSError("disk full")), \
                self.assertRaises(OSError):
            backup_file(self.root, "b.json", encoded(round_file(number=3)))
        self.assertEqual(kept.read_bytes(), first)
        self.assertEqual(self.files(), ["a.json", MANIFEST])
        self.assertEqual(missing_backups(self.root, self.sha, "s1", ["b.json"]), ["b.json"])

    def test_a_copy_that_reads_back_wrong_is_not_published(self):
        with patch.object(Path, "read_bytes", return_value=b"damaged"), self.assertRaises(OSError):
            backup_file(self.root, "a.json", encoded(round_file()))
        self.assertEqual(os.listdir(self.root / self.sha / "s1"), [])

    def test_a_manifest_line_cut_short_does_not_lose_later_entries(self):
        backup_file(self.root, "a.json", encoded(round_file()))
        manifest = self.root / self.sha / "s1" / MANIFEST
        manifest.write_bytes(manifest.read_bytes() + b'{"name": "cut')
        backup_file(self.root, "b.json", encoded(round_file(number=3)))
        self.assertEqual(missing_backups(self.root, self.sha, "s1", ["a.json", "b.json"]), [])

    def test_a_removed_or_truncated_copy_counts_as_missing_and_is_written_again(self):
        content = encoded(round_file())
        path = backup_file(self.root, "a.json", content)
        path.write_bytes(b"short")
        self.assertEqual(missing_backups(self.root, self.sha, "s1", ["a.json"]), ["a.json"])
        healed = backup_file(self.root, "a.json", content)
        self.assertEqual(healed.read_bytes(), content)
        self.assertEqual(missing_backups(self.root, self.sha, "s1", ["a.json"]), [])

    def test_an_unknown_recording_has_nothing_backed_up(self):
        self.assertEqual(missing_backups(self.root, None, "s1", ["a.json"]), ["a.json"])

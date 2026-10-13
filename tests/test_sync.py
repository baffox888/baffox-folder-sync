import os, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import file_sync as fs


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def r(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "src")
        self.dst = os.path.join(self.tmp, "dst")
        w(os.path.join(self.src, "a.txt"), "A2")
        w(os.path.join(self.src, "sub", "b.txt"), "B")
        w(os.path.join(self.dst, "a.txt"), "A1-old")
        w(os.path.join(self.dst, "extra.txt"), "X")
        w(os.path.join(self.dst, "olddir", "c.txt"), "C")

    def test_incremental(self):
        res = fs.execute_plan(fs.plan_sync(self.src, self.dst, "incremental"), use_send2trash=False)
        self.assertEqual(res["copied"], 1)
        self.assertEqual(res["skipped"], 1)
        self.assertEqual(r(os.path.join(self.dst, "a.txt")), "A1-old")
        self.assertTrue(os.path.exists(os.path.join(self.dst, "extra.txt")))
        self.assertEqual(r(os.path.join(self.dst, "sub", "b.txt")), "B")

    def test_full_preview_and_trash(self):
        plan = fs.plan_sync(self.src, self.dst, "full")
        self.assertEqual(sorted(plan["deletions"]), sorted(["extra.txt", "olddir" + os.sep]))
        self.assertTrue(os.path.exists(os.path.join(self.dst, "extra.txt")))  # plan changes nothing
        res = fs.execute_plan(plan, use_send2trash=False)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["deleted"], 2)
        self.assertEqual(r(os.path.join(self.dst, "a.txt")), "A2")
        self.assertFalse(os.path.exists(os.path.join(self.dst, "extra.txt")))
        trash = os.path.join(self.dst, fs.TRASH_DIR_NAME)
        found = [os.path.relpath(os.path.join(a, f), trash) for a, _, fl in os.walk(trash) for f in fl]
        self.assertEqual(len(found), 2)
        # second full run: nothing to do, trash folder not deleted
        plan2 = fs.plan_sync(self.src, self.dst, "full")
        self.assertEqual(plan2["deletions"], [])
        self.assertEqual(plan2["copies"], [])

    def test_full_without_delete(self):
        res = fs.execute_plan(fs.plan_sync(self.src, self.dst, "full"), do_delete=False)
        self.assertEqual(res["deleted"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.dst, "extra.txt")))

    def test_nested_blocked(self):
        self.assertIsNotNone(fs.validate_pair(self.src, os.path.join(self.src, "backup")))
        self.assertIsNotNone(fs.validate_pair(os.path.join(self.dst, "x"), self.dst))
        self.assertIsNotNone(fs.validate_pair(self.src, self.src + os.sep))
        self.assertIsNone(fs.validate_pair(self.src, self.src + "2"))
        plan = fs.plan_sync(self.src, os.path.join(self.src, "backup"), "full")
        self.assertTrue(plan["errors"])
        self.assertEqual(plan["copies"], [])

    def test_missing_source(self):
        plan = fs.plan_sync(os.path.join(self.tmp, "nope"), self.dst, "full")
        self.assertTrue(plan["errors"])
        self.assertEqual(fs.execute_plan(plan)["copied"], 0)


if __name__ == "__main__":
    unittest.main()

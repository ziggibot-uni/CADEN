import unittest
import os
from tools import list_files, read_file, write_file, run_cmd

class TestTools(unittest.TestCase):
    def setUp(self):
        self.testfile = "testfile.txt"
        self.testcontent = "hello world"
        if os.path.exists(self.testfile):
            os.remove(self.testfile)

    def tearDown(self):
        if os.path.exists(self.testfile):
            os.remove(self.testfile)

    def test_write_and_read_file(self):
        result = write_file(self.testfile, self.testcontent)
        self.assertEqual(result, "ok")
        content = read_file(self.testfile)
        self.assertEqual(content, self.testcontent)

    def test_list_files(self):
        write_file(self.testfile, self.testcontent)
        files = list_files(".")
        self.assertIn(self.testfile, files)

    def test_run_cmd(self):
        output = run_cmd(["echo", "hi"])
        self.assertIn("hi", output)

    def test_invalid_path(self):
        with self.assertRaises(ValueError):
            list_files(123)
        with self.assertRaises(ValueError):
            read_file(123)
        with self.assertRaises(ValueError):
            write_file(123, "bad")
        with self.assertRaises(ValueError):
            run_cmd(123)

if __name__ == "__main__":
    unittest.main()

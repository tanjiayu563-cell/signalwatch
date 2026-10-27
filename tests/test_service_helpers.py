import unittest

from monitor_agent.service import split_terms


class ServiceHelperTests(unittest.TestCase):
    def test_split_terms_supports_chinese_and_ascii_separators(self):
        self.assertEqual(
            split_terms("品牌A，品牌B\n品牌C;品牌D"),
            ["品牌A", "品牌B", "品牌C", "品牌D"],
        )

    def test_split_terms_deduplicates_case_insensitive(self):
        self.assertEqual(split_terms(["Apple", "apple", "苹果"]), ["Apple", "苹果"])


if __name__ == "__main__":
    unittest.main()

import unittest

from monitor_agent.article_reader import (
    ArticleHTMLParser,
    ArticleReadError,
    _clean_title,
    _validate_public_url,
)


class ArticleReaderTests(unittest.TestCase):
    def test_parser_extracts_article_text_and_skips_navigation(self):
        parser = ArticleHTMLParser()
        parser.feed("""
        <html><head><title>蓝色光标测试文章</title>
        <meta property="og:site_name" content="测试媒体">
        <meta name="description" content="文章摘要">
        </head><body>
        <nav>这是导航，不应该进入正文。</nav>
        <article><h1>蓝色光标测试文章</h1>
        <p>蓝色光标发布了新的业务进展，这是一段足够长的正文内容。</p>
        <p>第二段正文用于验证文章解析和去重逻辑是否正常。</p></article>
        <footer>页脚不应该进入正文。</footer></body></html>
        """)
        text = "\n".join(parser.paragraphs)
        self.assertIn("蓝色光标发布", text)
        self.assertNotIn("导航", text)
        self.assertNotIn("页脚", text)
        self.assertEqual(parser.site_name, "测试媒体")

    def test_site_title_suffix_is_cleaned(self):
        self.assertEqual(
            _clean_title("赵文权：AI²_集团新闻_新闻中心_蓝色光标集团-BlueFocus"),
            "赵文权：AI²",
        )

    def test_localhost_is_rejected(self):
        with self.assertRaises(ArticleReadError):
            _validate_public_url("http://127.0.0.1/private")


if __name__ == "__main__":
    unittest.main()

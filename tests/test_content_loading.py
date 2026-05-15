import unittest

from launchpad.content import (
    extract_checklist_items,
    list_checklists,
    list_modules,
    read_checklist_markdown,
    read_module_markdown,
    render_markdown,
)


class ContentLoadingTests(unittest.TestCase):
    def test_modules_are_loadable_from_manifest(self):
        modules = list_modules()

        self.assertGreaterEqual(len(modules), 8)
        for module in modules:
            markdown = read_module_markdown(module["slug"])
            self.assertIn("## Goal", markdown)

    def test_checklists_are_loadable_and_have_items(self):
        for checklist in list_checklists():
            markdown = read_checklist_markdown(checklist["slug"])
            items = extract_checklist_items(markdown)

            self.assertIn("## Purpose", markdown)
            self.assertGreater(len(items), 5)

    def test_markdown_renderer_handles_headings_and_checkboxes(self):
        rendered = render_markdown("# Title\n\n- [ ] Check this\n\n**Bold**")

        self.assertIn("<h1>Title</h1>", rendered)
        self.assertIn("type=\"checkbox\"", rendered)
        self.assertIn("<strong>Bold</strong>", rendered)


if __name__ == "__main__":
    unittest.main()

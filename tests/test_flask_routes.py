import unittest


def load_flask_app():
    import app as app_module

    if hasattr(app_module, "create_app"):
        return app_module.create_app()

    if hasattr(app_module, "app"):
        return app_module.app

    raise RuntimeError("Could not find create_app() or app in app.py")


class FlaskRouteSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_flask_app()
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()

    def test_simple_get_routes_do_not_crash(self):
        simple_get_routes = []

        for rule in self.app.url_map.iter_rules():
            if "GET" not in rule.methods:
                continue

            # Skip Flask's built-in static route.
            if rule.endpoint == "static":
                continue

            # Skip dynamic routes such as /modules/<module_id>.
            # Those should get separate targeted tests later.
            if rule.arguments:
                continue

            simple_get_routes.append(rule.rule)

        self.assertTrue(simple_get_routes, "No simple GET routes found to smoke test.")

        for route in simple_get_routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertLess(
                    response.status_code,
                    500,
                    f"{route} returned {response.status_code}",
                )


if __name__ == "__main__":
    unittest.main()

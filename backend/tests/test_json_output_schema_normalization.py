import unittest

from backend.agents.json_output_schema import normalize_instance_for_schema


class JsonOutputSchemaNormalizationTests(unittest.TestCase):
    def test_coerces_common_llm_scalar_type_drift(self):
        schema = {
            "type": "object",
            "properties": {
                "safe": {"type": "boolean"},
                "count": {"type": "integer", "minimum": 0},
                "score": {"type": "number", "minimum": 0, "maximum": 100},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "line": {"type": ["integer", "null"], "minimum": 1},
                            "enabled": {"type": "boolean"},
                        },
                    },
                },
            },
        }

        normalized = normalize_instance_for_schema(
            {
                "safe": "true",
                "count": "2",
                "score": "87.5",
                "items": [{"line": 0, "enabled": 1}],
            },
            schema,
        )

        self.assertEqual(
            normalized,
            {
                "safe": True,
                "count": 2,
                "score": 87.5,
                "items": [{"line": None, "enabled": True}],
            },
        )

    def test_coerces_object_items_when_schema_expects_strings(self):
        schema = {
            "type": "object",
            "properties": {
                "dry_violations": {"type": "array", "items": {"type": "string"}},
            },
        }

        normalized = normalize_instance_for_schema(
            {
                "dry_violations": [
                    {
                        "rule": "Clean Code - Magic number",
                        "description": "Magic number tespit edildi: 60",
                        "line_hint": "5",
                    }
                ]
            },
            schema,
        )

        self.assertEqual(
            normalized,
            {"dry_violations": ["Clean Code - Magic number: Magic number tespit edildi: 60 (5)"]},
        )


if __name__ == "__main__":
    unittest.main()

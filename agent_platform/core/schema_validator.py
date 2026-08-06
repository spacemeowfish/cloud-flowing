"""JSON Schema validation with actionable field-level errors."""

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from agent_platform.core.errors import SchemaValidationError


class SchemaValidator:
    @staticmethod
    def validate(instance: dict[str, JsonValue], schema: dict[str, JsonValue]) -> None:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
        if not errors:
            return
        error = errors[0]
        field = ".".join(str(part) for part in error.absolute_path) or "$"
        actual = repr(error.instance)
        raise SchemaValidationError(
            f"Field {field}: {error.message}; actual={actual}. Correct the value to match the declared schema."
        )


__all__ = ["SchemaValidator"]


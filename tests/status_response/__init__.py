from __future__ import annotations

import abc
from typing import Any, TypeVar, cast

import pytest

from mcstatus.status_response import BaseStatusResponse

__all__ = ["BaseStatusResponseTest"]
_T = TypeVar("_T", bound="type[BaseStatusResponseTest]")


class BaseStatusResponseTest(abc.ABC):
    EXPECTED_VALUES: list[tuple[str, Any]] | None = None
    EXPECTED_TYPES: list[tuple[str, type]] | None = None
    ATTRIBUTES_IN: list[str] | None = None
    # if we don't specify item in raw answer, target field will be None
    # first element is a list with fields to remove, and attribute that
    # must be None. a dict is a raw answer to pass into `build` method
    OPTIONAL_FIELDS: tuple[list[tuple[str, str]], dict[str, Any]] | None = None  # noqa: ANN401
    # there should be a ValueError, if we exclude the field from input
    # and a TypeError, if specify incorrect type
    # second item in tuple is an additional items to test their types,
    # but they can be not present. third item in tuple is a raw answer dict
    BUILD_METHOD_VALIDATION: tuple[list[str], list[str], dict[str, Any]] | None = None  # noqa: ANN401

    def _validate(self) -> None:
        """Perform checks to validate the class."""
        if self.EXPECTED_TYPES is not None and self.EXPECTED_VALUES is not None:
            expected_values_keys = list(dict(self.EXPECTED_VALUES).keys())

            for key in dict(self.EXPECTED_TYPES).keys():
                if key in expected_values_keys:
                    raise ValueError("You can't test the type of attribute, if already testing its value.")

        if self.ATTRIBUTES_IN is not None and (self.EXPECTED_VALUES is not None or self.EXPECTED_TYPES is not None):
            if self.EXPECTED_VALUES and self.EXPECTED_TYPES:
                to_dict = self.EXPECTED_VALUES.copy()
                to_dict.extend(self.EXPECTED_TYPES)
                already_checked_attributes = dict(to_dict).keys()
            else:
                already_checked_attributes = dict(self.EXPECTED_VALUES or self.EXPECTED_TYPES).keys()  # type: ignore

            for attribute_name in self.ATTRIBUTES_IN:
                if attribute_name in already_checked_attributes:
                    raise ValueError("You can't test the type availability, if already testing its value/type.")

        if self.BUILD_METHOD_VALIDATION is not None:
            for do_required_item in self.BUILD_METHOD_VALIDATION[1]:
                if do_required_item in self.BUILD_METHOD_VALIDATION[0]:
                    raise ValueError(
                        "You must specify only required fields, in first tuple's item."
                        f" Found '{do_required_item}' in first and second items."
                    )

    @abc.abstractmethod
    def build(self) -> Any:  # noqa: ANN401
        ...

    # implementations for tests

    def test_values_of_attributes(self, build: BaseStatusResponse, field: str, value: Any) -> None:  # noqa: ANN401
        assert getattr(build, field) == value

    def test_types_of_attributes(self, build: BaseStatusResponse, field: str, type_: type) -> None:
        assert isinstance(getattr(build, field), type_)

    def test_attribute_in(self, build: BaseStatusResponse, field: str) -> None:
        assert hasattr(build, field)

    def test_optional_field_turns_into_none(self, build: BaseStatusResponse, to_remove: str, attribute_name: str) -> None:
        raw = cast(tuple, self.OPTIONAL_FIELDS)[1]
        del raw[to_remove]
        assert getattr(type(build).build(raw), attribute_name) is None

    def test_value_validating(self, build: BaseStatusResponse, exclude_field: str) -> None:
        raw = cast(list, self.BUILD_METHOD_VALIDATION)[2].copy()
        raw.pop(exclude_field)
        with pytest.raises(ValueError):
            type(build).build(raw)

    def test_type_validating(self, build: BaseStatusResponse, to_change_field: str) -> None:
        raw = cast(list, self.BUILD_METHOD_VALIDATION)[2].copy()
        raw[to_change_field] = object()
        with pytest.raises(TypeError):
            type(build).build(raw)

    def _dependency_table(self) -> dict[str, bool]:
        # a key in the dict must be a name of a test implementation.
        # and a value of the dict is a bool. if it's false - we
        # "delete" a test from the class.
        return {
            "test_values_of_attributes": self.EXPECTED_VALUES is not None,
            "test_types_of_attributes": self.EXPECTED_TYPES is not None,
            "test_attribute_in": self.ATTRIBUTES_IN is not None,
            "test_optional_field_turns_into_none": self.OPTIONAL_FIELDS is not None,
            "test_value_validating": self.BUILD_METHOD_VALIDATION is not None,
            "test_type_validating": self.BUILD_METHOD_VALIDATION is not None,
        }

    def _marks_table(self) -> dict[str, tuple[str, tuple[Any, ...]]]:
        # hooks in conftest.py parses this table
        if self.BUILD_METHOD_VALIDATION is not None:
            build_method_validation_args = self.BUILD_METHOD_VALIDATION[0].copy()
            build_method_validation_args.extend(self.BUILD_METHOD_VALIDATION[1])
        else:
            build_method_validation_args = []

        # a key in the dict must be a name of a test implementation.
        # and a value of the dict is a tuple, where first element is
        # a name of mark to apply to the test, and second element is
        # positional arguments, which passed to the mark
        return {
            "test_values_of_attributes": ("parametrize", ("field,value", self.EXPECTED_VALUES)),
            "test_types_of_attributes": ("parametrize", ("field,type_", self.EXPECTED_TYPES)),
            "test_attribute_in": ("parametrize", ("field", self.ATTRIBUTES_IN)),
            "test_optional_field_turns_into_none": (
                "parametrize",
                ("to_remove,attribute_name", self.OPTIONAL_FIELDS[0] if self.OPTIONAL_FIELDS is not None else ()),
            ),
            "test_value_validating": (
                "parametrize",
                ("exclude_field", self.BUILD_METHOD_VALIDATION[0] if self.BUILD_METHOD_VALIDATION is not None else ()),
            ),
            "test_type_validating": ("parametrize", ("to_change_field", build_method_validation_args)),
        }

    @staticmethod
    def construct(class_: _T) -> _T:
        instance: BaseStatusResponseTest = class_()  # type: ignore
        instance._validate()
        for implementation_name, meet_dependencies in instance._dependency_table().items():
            if not meet_dependencies:
                # delattr works only with initialized classes,
                # hopefully overwriting with None doesn't have this limitation
                setattr(class_, implementation_name, None)

        return class_

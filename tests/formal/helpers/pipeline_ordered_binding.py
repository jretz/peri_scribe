"""Qualify the closed pipeline replay before sharing native trace witnesses.

See [Verification tooling](../../../docs/algorithms/verification-tooling.md).
"""

from __future__ import annotations

import ast
import dataclasses
import functools
import hashlib
import importlib
import inspect
import io
import os
import pathlib
import shutil
import sys
import types

import pydantic

import peri_scribe.cli_options
import peri_scribe.execution
import peri_scribe.publication
import tests.formal.helpers.pipeline_effect_matrix
import tests.formal.helpers.pipeline_file_footprint


footprint = tests.formal.helpers.pipeline_file_footprint
matrix = tests.formal.helpers.pipeline_effect_matrix

# A source change requires a fresh review of the closed replay or the full native run.
SOURCES: dict[str, str] = {
    "peri_scribe.cli_options": (
        "a2030af89a7d20de9e0653c74eb60304cc8cadd3ce3d6055c9bce1b738e80435"
    ),
    "peri_scribe.execution": (
        "28f510672d82b6b0c6d6a9af88e47c6ae78499c2ca3ee50350959c59b5250a8d"
    ),
    "peri_scribe.paths": (
        "8813be85bd95083ef17eadbe026fb5c9109fba899a9a8d887d3e20ee03a0c86d"
    ),
    "peri_scribe.phases": (
        "e55e470ecee1d4c1f455d27d2251196bad914b50bdaf196bc2a235837e87d060"
    ),
    "peri_scribe.pipeline": (
        "a4532a15005419430abf5940a8c260562756a9e51a1c75060788fddcff66fd09"
    ),
    "peri_scribe.pipeline_stages": (
        "32a189fa77ccb515367f9ecc9d482a30fd7ce3f4fc332d6d2b99e1921f58cc58"
    ),
    "peri_scribe.pipeline_state": (
        "61a0cec5e5d4f86648ee97762a535f33312fc1a819a42b8fa42ba7acbf1159ec"
    ),
    "peri_scribe.preparation": (
        "8d640c20f86933aaaaeb66781c1de7a92355595fa327f43434005598f88ad3dc"
    ),
    "peri_scribe.publication": (
        "bacc246a6aabe3e8d0a98d8728912d4998be8ceb3754fee3ecb4463550c99b93"
    ),
    "peri_scribe.sources.catalog": (
        "752297b6ccda42a67bdc5d3698c0d457f0e92915981d5d13f1a96f1fcf3e07d0"
    ),
    "peri_scribe.sources.fetch_control": (
        "09d15641408326d76b33adb14fc3807e458ff0d8de89bf4fafc429464224b259"
    ),
    "peri_scribe.sources.full_fetch_state": (
        "b5ed8944fabd978bc12927e070dcecfd688c347da8fcd7846df3043f0e5ea55e"
    ),
    "peri_scribe.sources.snapshots": (
        "1d51ec80b638766886ec0e48c9ce94153882909bec22a7afb64dabb78751678b"
    ),
    "peri_scribe.supervision": (
        "c4851a7eb1da3316d9101684a02d6d2fd049cd82e22a01ae7786c8f29f48be2c"
    ),
    "tests.formal.helpers.paths": (
        "424a5eec26b47b7184460a427db341e848cbcee58c0738b066a2d10b50b0d475"
    ),
    "tests.formal.helpers.pipeline_batches": (
        "f64c6d7ddb6e525bb57f4f4844cfcf4fc073673886cda883cb024f7a4d54d322"
    ),
    "tests.formal.helpers.pipeline_composition": (
        "137d56540769bc01171e5524005427b7ddc9421f9bd65b968b3c10109fb19caf"
    ),
    "tests.formal.helpers.pipeline_ordered_replay": (
        "32b6507a2dc67ffcfa3ef6efc8e1166a01dfe5d1586ca9d0024fbbc8d73b718c"
    ),
    "tests.formal.helpers.pipeline_replay_files": (
        "3d86b99ace88be3f11cf763c9729914f04adf3f0577ffc35d2249aefae867268"
    ),
    "tests.helpers.doubles.peri_scribe.pipeline_fetch_recovery": (
        "fedc4393c609fed2f3315fa825ec703b7c06175e7e4964cdc90862164e66a134"
    ),
    "tests.helpers.factories.peri_scribe.publication": (
        "ab4a25b8b966bb2aa63b0120ff17acbbb0ad76e1caedadb4df6249dd16566747"
    ),
}


# These are the production and fixture entry points whose plain functions must
# match the compiled reviewed source even before checking live substitutions.
ENTRY_POINTS: dict[str, tuple[str, ...]] = {
    "peri_scribe.pipeline": (
        "run_selected_stages",
        "run_pipeline_stage",
        "run_fetch_stage",
        "run_gated_fetch_stage",
        "fetch_fire_sources",
        "publication_decision",
        "run_geography_stage",
        "run_score_stage",
        "run_kmz_stage",
        "run_reports_stage",
    ),
    "peri_scribe.sources.fetch_control": (
        "collect_fire_sources",
        "run_ungated_fetch",
        "restore_previous_state",
        "proceed_without_pending",
    ),
    "peri_scribe.pipeline_state": (
        "read_state",
        "write_state",
        "state_path",
        "deferred_inputs_path",
        "defer_inputs",
        "clear_deferred_inputs",
        "has_deferred_inputs",
        "required_state",
        "completed_state",
        "require_stages",
        "complete_stage",
    ),
    "peri_scribe.preparation": ("cached_year",),
    "peri_scribe.publication": (
        "file_stamp",
        "publication_path",
        "read_state",
        "write_state",
        "read_publication",
        "invalidate",
        "commit",
        "decide",
    ),
    "tests.formal.helpers.pipeline_replay_files": (
        "read_image",
        "Memory.at",
        "Memory.fork",
        "Memory.mutate",
        "Memory.write_generation",
        "File.entry",
        "File.read_bytes",
        "File.exists",
        "File.identity",
        "File.replace_text",
        "File.touch",
        "File.remove",
        "Artifacts.image",
        "Artifacts.read_bytes",
        "Artifacts.exists",
        "Artifacts.modified_nanoseconds",
        "Artifacts.effect_input",
        "Artifacts.record_effect",
        "Artifacts.write_generation",
    ),
    "tests.formal.helpers.pipeline_composition": (
        "replay",
        "install_dependencies",
        "Replay.__post_init__",
        "Replay.snapshot",
        "Replay.begin",
        "Replay.observe",
        "Replay.inspect",
        "Replay.install_observer",
        "Replay.interrupt",
        "Replay.check",
        "Replay.initialize",
        "Replay.write_kmz",
        "Replay.fetch",
        "Replay.collect",
        "Replay.geography",
        "Replay.score",
        "Replay.reports",
        "Replay.create_kmz",
    ),
    "tests.formal.helpers.pipeline_batches": ("replay", "replay_memory", "trees"),
    "tests.formal.helpers.pipeline_ordered_replay": (
        "missing_reply",
        "read_hook",
        "expected_reply",
        "verify_tape",
        "verify",
        "categories",
        "representatives",
        "compare",
        "ReadTrace.record",
    ),
}


@dataclasses.dataclass(frozen=True, kw_only=True)
class Live:
    """Retain a reviewed object binding and any executable state it uses."""

    owner: object
    name: str
    value: object
    code: types.CodeType | None
    defaults: tuple[object, ...] | None
    keywords: tuple[tuple[str, object], ...]
    cells: tuple[object, ...]

    def valid(self) -> bool:
        """Require the same executable object, defaults and namespace binding.

        Returns:
            Whether the callable or native primitive is still the reviewed object.
        """
        current = inspect.getattr_static(self.owner, self.name, None)
        return current is self.value and (
            not isinstance(current, types.FunctionType)
            or (
                current.__code__ is self.code
                and current.__defaults__ == self.defaults
                and tuple((current.__kwdefaults__ or {}).items()) == self.keywords
                and tuple(id(cell.cell_contents) for cell in current.__closure__ or ())
                == tuple(map(id, self.cells))
            )
        )


def live(owner: object, name: str) -> Live:
    """Record the actual binding without invoking descriptors.

    Returns:
        The object and executable fields to compare before qualifying a replay.
    """
    value = inspect.getattr_static(owner, name, None)
    function = value if isinstance(value, types.FunctionType) else None
    return Live(
        owner=owner,
        name=name,
        value=value,
        code=None if function is None else function.__code__,
        defaults=None if function is None else function.__defaults__,
        keywords=()
        if function is None
        else tuple((function.__kwdefaults__ or {}).items()),
        cells=()
        if function is None
        else tuple(cell.cell_contents for cell in function.__closure__ or ()),
    )


def reviewed_bindings(module: types.ModuleType) -> tuple[Live, ...]:
    """Bind its definitions and imported names before test overrides run.

    Returns:
        The module-level values and methods reachable from its own definitions.
    """
    result = []
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        result.append(live(module, name))
        if isinstance(value, type) and value.__module__ == module.__name__:
            result.extend(
                live(value, member)
                for member, method in vars(value).items()
                if isinstance(method, types.FunctionType)
            )
    return tuple(result)


MODULES = tuple(importlib.import_module(name) for name in SOURCES)
RUNTIME_IMPORTS = {
    name: importlib.import_module(name)
    for name in (
        "peri_scribe.fires.differential",
        "peri_scribe.fires.index",
        "peri_scribe.fires.scores",
        "peri_scribe.kml.builder",
        "peri_scribe.logging",
        "peri_scribe.preparation",
        "peri_scribe.sources.fetching",
    )
}
LIVE = (
    *(binding for module in MODULES for binding in reviewed_bindings(module)),
    live(io, "open"),
    live(importlib, "import_module"),
    live(os, "strerror"),
    live(pathlib.Path, "__fspath__"),
    live(pathlib.Path, "__str__"),
    live(pathlib.Path, "relative_to"),
    live(pathlib.Path, "as_posix"),
    live(shutil, "copytree"),
    live(shutil, "copy2"),
    live(shutil, "copystat"),
    live(shutil, "copyfile"),
    live(RUNTIME_IMPORTS["peri_scribe.sources.fetching"], "FetchResult"),
    *(
        live(owner, name)
        for module in MODULES
        for owner in vars(module).values()
        if isinstance(owner, type) and owner.__module__ == module.__name__
        for name in ("__getattribute__", "__getattr__", "__setattr__", "__new__")
    ),
)


def immutable(value: object) -> object:
    """Capture the exact fixture values needed by the reviewed continuations.

    Returns:
        Immutable values suitable for checking live containers.
    """
    if isinstance(value, dict):
        return tuple(value.items())
    if isinstance(value, pydantic.BaseModel):
        return value.model_dump_json(), frozenset(value.model_fields_set)
    if isinstance(value, peri_scribe.publication.Threshold):
        return float(value.area.magnitude).hex(), str(value.area.units), value.interval
    if isinstance(value, tuple):
        return tuple(
            (item.name, item.description)
            if isinstance(item, peri_scribe.cli_options.PipelineStage)
            else item
            for item in value
        )
    return value


VALUES = tuple(
    (module, name, immutable(getattr(module, name)))
    for module in MODULES
    for name in (
        "PIPELINE_STAGES",
        "STAGE_INDEX",
        "DERIVED_STAGES",
        "BASELINE_MAPPING",
        "SMALL_CHANGE_MAPPING",
        "THRESHOLD_CHANGE_MAPPING",
        "THRESHOLD",
        "NOW",
        "FILES",
        "FILE_INDEX",
        "MARKERS",
    )
    if name in vars(module)
)


def imported(module: types.ModuleType) -> bool:
    """Require module and parent namespace lookups to reach the same object.

    Returns:
        Whether ordinary imports resolve to this exact module.
    """
    parent, _, name = module.__name__.rpartition(".")
    package = sys.modules.get(parent)
    return (
        sys.modules.get(module.__name__) is module
        and package is not None
        and vars(package).get(name) is module
    )


@functools.lru_cache(maxsize=32)
def compiled_entries(
    source: str,
    names: tuple[str, ...],
) -> tuple[tuple[str, tuple[object, ...]], ...]:
    """Compile the exact source without running its module initializers.

    Returns:
        Original code signatures for the requested reviewed functions.
    """
    module_code = compile(source, "<ordered-pipeline>", "exec", dont_inherit=True)
    classes = {
        value.co_name: value
        for value in module_code.co_consts
        if isinstance(value, types.CodeType)
    }
    signatures = footprint.function_codes(module_code)
    for name in names:
        owner, separator, member = name.partition(".")
        if separator:
            signatures[name] = footprint.function_codes(classes[owner])[member]
    return tuple((name, signatures[name]) for name in names)


def source_matches(module: types.ModuleType) -> bool:
    """Qualify the current source and the loaded code of its reviewed entry points.

    Returns:
        Whether this source and its actual functions can participate in a replay.
    """
    path = vars(module).get("__file__")
    if not isinstance(path, str) or not imported(module):
        return False
    source = pathlib.Path(path).read_text(encoding="utf-8")
    normalized = footprint.normalize(ast.parse(source))
    if hashlib.sha256(normalized.encode()).hexdigest() != SOURCES[module.__name__]:
        return False
    for name, signature in compiled_entries(
        source,
        ENTRY_POINTS.get(module.__name__, ()),
    ):
        owner, separator, member = name.partition(".")
        function = inspect.unwrap(
            getattr(getattr(module, owner), member)
            if separator
            else getattr(module, owner),
        )
        if (
            not isinstance(function, types.FunctionType)
            or function.__globals__ is not vars(module)
            or footprint.signature(function.__code__) != signature
        ):
            return False
    return True


def reviewed_proof() -> bool:
    """Qualify the exact mixed-step theorem before using the current Lean build.

    Returns:
        Whether the source matches the reviewed reader and effect equations.
    """
    directory = pathlib.Path(__file__).parents[1] / "lean" / "PeriScribe"
    sources = (
        (
            "EffectRefinement.lean",
            "1bf9e61d1ce4c96140524b6ad125c84269aa4495b67c5ed1fee223bc5bc7a19e",
        ),
        (
            "PipelineFileFootprint.lean",
            "351b6da62560cd5800a350222360a9d60a2af561ed33717e93204eba9c71002f",
        ),
    )
    return all(
        hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected
        for name, expected in sources
    )


def resolve() -> footprint.Footprint | None:
    """Use the mixed proof only inside the reviewed source and runtime closure.

    Returns:
        The checked transfers, or absence to run the entire original native matrix.
    """
    try:
        if (
            not all(binding.valid() for binding in LIVE)
            or peri_scribe.execution.active()
        ):
            return None
        if not all(imported(module) for module in RUNTIME_IMPORTS.values()):
            return None
        if not all(
            immutable(getattr(module, name)) == original
            for module, name, original in VALUES
        ):
            return None
        if not reviewed_proof() or not all(
            source_matches(module) for module in MODULES
        ):
            return None
    except OSError, UnicodeError, SyntaxError, ValueError:
        return None
    return footprint.resolve(matrix, matrix.FRAME_TYPES)

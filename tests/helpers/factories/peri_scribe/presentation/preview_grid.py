"""Share one invocation's exact default dart hulls between history consumers.

The geometry and image tests continue to exercise the original rendering functions.
History fixtures can reconstruct these immutable inputs under the current code,
libraries, constants and callable bindings.
"""

from __future__ import annotations

import base64
import collections.abc
import dataclasses
import fcntl
import functools
import hashlib
import importlib
import inspect
import json
import pathlib
import platform
import sys
import tempfile
import types
import typing
import unittest.mock

import peri_scribe.presentation.preview_geometry as geometry
import tests.formal.helpers.session


if typing.TYPE_CHECKING:
    import shapely


type Grid = tuple[tuple[float, shapely.Polygon], ...]
type Snapshot = tuple[object, ...]


class EncodedGrid(typing.TypedDict):
    """Keep exact angle spellings and shared hull references together."""

    angles: list[str]
    indices: list[int]
    wkbs: list[str]


class CacheInfo(typing.Protocol):
    """Read the original functools cache's current population."""

    @property
    def currsize(self) -> int:
        """The count of retained grid entries."""
        ...


class CachedGrid(typing.Protocol):
    """Keep the original callable and its normal cache interface."""

    def __call__(self) -> Grid:
        """Return the original default coarse table."""
        ...

    def cache_info(self) -> CacheInfo:
        """Return the normal functools cache counters."""
        ...


SCHEMA = 1
GRID_COUNT = 7201
RENDERER_DIGEST = "f439806bf56cc646170ff6c0c8c2684025db0b4041c2a9b125d270c9575f48fa"


def executable(value: object, seen: set[int] | None = None) -> Snapshot:
    """Retain callable identities and the executable state behind their wrappers.

    Args:
        value: A rendering binding, default, closure value or descriptor.
        seen: Objects already retained while traversing this binding.

    Returns:
        Immutable state that detects replacement and in-place callable changes.
    """
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return (identity,)
    seen.add(identity)
    if isinstance(value, types.FunctionType):
        result = (
            identity,
            value,
            id(value.__code__),
            value.__code__,
            id(value.__defaults__),
            value.__defaults__,
            executable(value.__defaults__, seen),
            id(value.__kwdefaults__),
            value.__kwdefaults__,
            executable(value.__kwdefaults__, seen),
            tuple(
                (id(cell), executable(cell.cell_contents, seen))
                for cell in value.__closure__ or ()
            ),
            executable(getattr(value, "__wrapped__", None), seen),
        )
    elif isinstance(value, (staticmethod, classmethod)):
        result = identity, value, executable(value.__func__, seen)
    elif isinstance(value, property):
        result = (
            identity,
            value,
            executable(value.fget, seen),
            executable(value.fset, seen),
            executable(value.fdel, seen),
        )
    elif isinstance(value, dict):
        result = (
            identity,
            value,
            tuple(
                (executable(key, seen), executable(item, seen))
                for key, item in value.items()
            ),
        )
    elif isinstance(value, (tuple, list)):
        result = identity, value, tuple(executable(item, seen) for item in value)
    elif isinstance(value, (set, frozenset)):
        result = (
            identity,
            value,
            tuple(executable(item, seen) for item in sorted(value, key=id)),
        )
    else:
        wrapped = getattr(value, "__wrapped__", None)
        result = identity, value, executable(wrapped, seen)
    return result


def primitive_bindings() -> tuple[object, ...]:
    """Read the live functions and constants used to construct default dart hulls.

    Returns:
        Object bindings, including Pillow constructors and drawing methods.
    """
    values = [
        geometry.north_dart_hull,
        geometry.dart_hull_from_state,
        geometry.supersampled_dart,
        geometry.rotate,
        geometry.rotation_axes,
        geometry.PIL.Image.new,
        geometry.PIL.Image.fromarray,
        geometry.PIL.Image.frombuffer,
        geometry.PIL.Image.frombytes,
        geometry.PIL.ImageDraw.Draw,
        geometry.PIL.Image.core,
        geometry.PIL.Image.core.draw,
        geometry.shapely.MultiPoint,
        geometry.shapely.points,
        geometry.shapely.multipoints,
        geometry.shapely.convex_hull,
        geometry.shapely.get_coordinates,
        geometry.shapely.from_wkb,
        geometry.shapely.buffer,
        geometry.np.packbits,
        geometry.np.unpackbits,
        geometry.np.frombuffer,
        geometry.np.asarray,
        geometry.np.array,
        geometry.np.uint8,
        geometry.np.nonzero,
        geometry.np.column_stack,
        geometry.np.concatenate,
        geometry.np.arange,
        geometry.np.nextafter,
        geometry.math.sin,
        geometry.math.cos,
        geometry.math.radians,
        getattr(geometry.PIL.Image.Image, "getdraw", None),
    ]
    for owner in (
        geometry.PIL.Image.Image,
        geometry.PIL.ImageDraw.ImageDraw,
        geometry.shapely.geometry.base.BaseGeometry,
        geometry.shapely.MultiPoint,
    ):
        values.append(owner)
        values.extend(
            (name, member)
            for name, member in vars(owner).items()
            if callable(member)
            or isinstance(member, (property, staticmethod, classmethod))
        )
    return tuple(values)


def constants() -> tuple[object, ...]:
    """Read every constant used by the coarse grid and its placed raster support.

    Returns:
        The current default grid and raster parameters.
    """
    return (
        geometry.SIZE,
        geometry.SUPERSAMPLING,
        geometry.DART_SIZE,
        geometry.DART_HULL_SIZE,
        geometry.DART_HULL_BOX,
        geometry.DART_VERTICES,
        geometry.DART_CLEARANCE,
        geometry.MINIMUM_ANGLE,
        geometry.MAXIMUM_ANGLE,
        geometry.ANGLE_STEP,
        geometry.PIL.Image.Resampling.LANCZOS,
        geometry.np.inf,
    )


DEFAULT_PRIMITIVES = primitive_bindings()


def primitive_state() -> Snapshot:
    """Retain each named class member without depending on temporary pair objects.

    Returns:
        The live executable state of the reviewed rendering bindings.
    """
    return tuple(
        (value[0], executable(value[1]))
        if isinstance(value, tuple)
        else executable(value)
        for value in primitive_bindings()
    )


DEFAULT_EXECUTABLES = primitive_state()
DEFAULT_CONSTANTS = constants()
DEFAULT_COARSE = geometry.coarse_dart_hulls
DEFAULT_COARSE_STATE = executable(DEFAULT_COARSE)


def code_paths(value: object, seen: set[int]) -> set[pathlib.Path]:
    """Find source artifacts behind wrapped Python rendering functions.

    Args:
        value: One reviewed binding or descriptor.
        seen: Objects already inspected.

    Returns:
        Existing files containing executable Python definitions.
    """
    if id(value) in seen:
        return set()
    seen.add(id(value))
    if isinstance(value, types.FunctionType):
        result = {pathlib.Path(value.__code__.co_filename)}
        result.update(code_paths(getattr(value, "__wrapped__", None), seen))
        result.update(code_paths(value.__defaults__, seen))
        result.update(code_paths(value.__kwdefaults__, seen))
        for cell in value.__closure__ or ():
            result.update(code_paths(cell.cell_contents, seen))
        result = {path for path in result if path.is_file()}
    elif isinstance(value, (staticmethod, classmethod)):
        result = code_paths(value.__func__, seen)
    elif isinstance(value, property):
        result = (
            code_paths(value.fget, seen)
            | code_paths(value.fset, seen)
            | code_paths(value.fdel, seen)
        )
    elif isinstance(value, dict):
        result = set().union(*(code_paths(item, seen) for item in value.values()))
    elif isinstance(value, (tuple, list)):
        result = set().union(*(code_paths(item, seen) for item in value))
    else:
        result = code_paths(getattr(value, "__wrapped__", None), seen)
    return result


def artifact_paths() -> tuple[pathlib.Path, ...]:
    """Pin the loaded renderer and its bundled native libraries.

    Returns:
        Python sources, actual extension files and package-local shared libraries.
    """
    paths = {
        pathlib.Path(__file__),
        pathlib.Path(geometry.__file__),
        pathlib.Path(sys.executable),
    }
    mathematics = getattr(geometry.math, "__file__", None)
    if mathematics is not None:
        paths.add(pathlib.Path(mathematics))
    seen: set[int] = set()
    for value in DEFAULT_PRIMITIVES:
        paths.update(code_paths(value, seen))
    paths.update(
        pathlib.Path(typing.cast("str", module.__file__))
        for module in (
            geometry.PIL.Image.core,
            geometry.shapely.lib,
            importlib.import_module("numpy._core._multiarray_umath"),
        )
    )
    for package, distribution_name in (
        (geometry.PIL, "pillow"),
        (geometry.shapely, "shapely"),
        (geometry.np, "numpy"),
    ):
        directory = pathlib.Path(package.__file__).parent
        for bundled in {
            directory / ".dylibs",
            directory.parent / f"{package.__name__}.libs",
            directory.parent / f"{distribution_name}.libs",
        }:
            if bundled.is_dir():
                paths.update(path for path in bundled.rglob("*") if path.is_file())
    return tuple(sorted(paths))


ARTIFACTS = artifact_paths()


def artifact_digest(path: pathlib.Path) -> str:
    """Read actual content because file metadata cannot establish byte identity.

    Args:
        path: Loaded Python or native renderer artifact.

    Returns:
        The artifact's SHA-256 content identity.
    """
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def artifact_name(path: pathlib.Path) -> str:
    """Use package-relative artifact roles across isolated source copies.

    Args:
        path: The actual loaded artifact.

    Returns:
        Its stable package-relative name.
    """
    packages = {
        "peri_scribe",
        "PIL",
        "shapely",
        "numpy",
        "pillow.libs",
        "shapely.libs",
        "numpy.libs",
    }
    for position in reversed(range(len(path.parts))):
        part = path.parts[position]
        if part in packages:
            return "/".join(path.parts[position:])
    return "helper/" + path.name


def signature() -> str:
    """Bind the table to the loaded rendering artifacts and Python runtime.

    Returns:
        The exact source and runtime identity used within this invocation.
    """
    artifacts = sorted(
        (artifact_name(path), artifact_digest(path)) for path in ARTIFACTS
    )
    runtime = (
        sys.version,
        sys.implementation.cache_tag,
        sys.platform,
        sys.byteorder,
        platform.machine(),
        sys.flags.optimize,
    )
    document = SCHEMA, runtime, artifacts
    return hashlib.sha256(json.dumps(document).encode()).hexdigest()


def encode(grid: Grid) -> EncodedGrid:
    """Encode binary64 angles and unique immutable hull bytes without rounding.

    Args:
        grid: Values returned by the real default coarse-grid implementation.

    Returns:
        JSON-compatible angle spellings, hull indices and Base64 WKB.
    """
    objects: dict[int, int] = {}
    positions: dict[bytes, int] = {}
    wkbs: list[str] = []
    indices: list[int] = []
    for _, hull in grid:
        index = objects.get(id(hull))
        if index is None:
            raw = hull.wkb
            index = positions.get(raw)
            if index is None:
                index = len(wkbs)
                positions[raw] = index
                wkbs.append(base64.b64encode(raw).decode("ascii"))
            objects[id(hull)] = index
        indices.append(index)
    return {
        "angles": [float(angle).hex() for angle, _ in grid],
        "indices": indices,
        "wkbs": wkbs,
    }


def decode(value: EncodedGrid) -> Grid:
    """Reconstruct the producer's immutable GEOS values and exact angles.

    Args:
        value: Checked JSON payload from this invocation's producer.

    Returns:
        The complete coarse input table.

    Raises:
        ValueError: The table is incomplete or its geometry bytes cannot roundtrip.
    """
    angles = [float.fromhex(text) for text in value["angles"]]
    raw = [base64.b64decode(text, validate=True) for text in value["wkbs"]]
    hulls = geometry.shapely.from_wkb(raw)
    if any(hull.wkb != original for hull, original in zip(hulls, raw, strict=True)):
        message = "Dart hull bytes changed during decoding"
        raise ValueError(message)
    indices = value["indices"]
    if len(angles) != GRID_COUNT or len(indices) != len(angles) or not raw:
        message = "Incomplete dart grid"
        raise ValueError(message)
    if any(type(index) is not int or not 0 <= index < len(hulls) for index in indices):
        message = "Invalid dart hull reference"
        raise ValueError(message)
    return tuple(
        (angle, hulls[index]) for angle, index in zip(angles, indices, strict=True)
    )


def read_grid(destination: pathlib.Path, identity: str) -> Grid:
    """Validate a complete publication before reconstructing immutable geometry.

    Args:
        destination: The current invocation's atomically published table.
        identity: The expected renderer and runtime identity.

    Returns:
        Exact table values from the qualified native producer.

    Raises:
        ValueError: The publication belongs to another renderer or is incomplete.
    """
    document = json.loads(destination.read_bytes())
    payload = document["grid"]
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    if (
        document["identity"] != identity
        or document["checksum"] != hashlib.sha256(raw).hexdigest()
    ):
        message = "The dart table publication failed its identity check"
        raise ValueError(message)
    return decode(payload)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SharedGrid:
    """Seed a worker's normal coarse cache from freshly qualified immutable inputs."""

    original: CachedGrid
    native_body: collections.abc.Callable[[], Grid]
    owner: pathlib.Path
    identity: str
    original_state: Snapshot

    def valid(self) -> bool:
        """Require the original rendering environment and the same live owner.

        Returns:
            Whether this consumer may use the current invocation's table.
        """
        try:
            return (
                constants() == DEFAULT_CONSTANTS
                and primitive_state() == DEFAULT_EXECUTABLES
                and executable(self.original) == self.original_state
                and tests.formal.helpers.session.directory() == self.owner
                and artifact_digest(pathlib.Path(geometry.__file__)) == RENDERER_DIGEST
                and signature() == self.identity
            )
        except OSError, RuntimeError, ValueError, AttributeError, TypeError:
            return False

    def native(self) -> Grid:
        """Run the original body after an unsupported dependency change.

        Returns:
            Its genuine native coarse table.
        """
        return self.native_body()

    @functools.cached_property
    def loaded(self) -> Grid:
        """Read or publish a complete table under the live invocation's writer lock.

        Returns:
            Exact immutable values computed by the current native producer.
        """
        directory = self.owner / "shared-dart-grid" / self.identity
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "grid.json"
        with (directory / "writer.lock").open("ab") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if destination.exists():
                try:
                    return read_grid(destination, self.identity)
                except (
                    OSError,
                    ValueError,
                    TypeError,
                    AttributeError,
                    KeyError,
                    IndexError,
                    geometry.shapely.errors.GEOSException,
                ):
                    pass
            grid = self.original()
            payload = encode(grid)
            decode(payload)
            raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
            document = {
                "identity": self.identity,
                "checksum": hashlib.sha256(raw).hexdigest(),
                "grid": payload,
            }
            with tempfile.TemporaryDirectory(dir=directory) as temporary:
                staging = pathlib.Path(temporary) / destination.name
                staging.write_text(json.dumps(document, separators=(",", ":")))
                staging.replace(destination)
            return grid

    def get(self) -> Grid:
        """Populate the unchanged original coarse loop and its ordinary cache.

        Returns:
            The same table a native build would retain for this worker.

        Raises:
            ValueError: The original coarse loop differs from the qualified table.
        """
        if not self.valid():
            return self.native()
        if self.original.cache_info().currsize:
            return self.original()
        table = self.loaded
        primitive = geometry.north_dart_hull
        choices = {geometry.math.radians(angle): hull for angle, hull in table}

        def lookup(angle: float) -> shapely.Polygon:
            """Use qualified default angles and retain native unexpected-angle behavior.

            Args:
                angle: Radian angle requested by the original coarse loop.

            Returns:
                Its exact immutable hull.
            """
            hull = choices.get(angle)
            return primitive(angle) if hull is None else hull

        with unittest.mock.patch.object(geometry, "north_dart_hull", lookup):
            grid = self.original()
        if any(
            float(angle).hex() != float(saved).hex() or hull is not restored
            for (angle, hull), (saved, restored) in zip(grid, table, strict=True)
        ):
            message = "The native coarse loop differs from the qualified table"
            raise ValueError(message)
        return grid


def current_grid() -> SharedGrid | None:
    """Bind one worker to the fresh invocation and its original rendering functions.

    Returns:
        A loader whose unsupported environments take the native route.
    """
    owner = tests.formal.helpers.session.directory()
    renderer = pathlib.Path(geometry.__file__)
    original = geometry.coarse_dart_hulls
    if (
        owner is None
        or original is not DEFAULT_COARSE
        or executable(original) != DEFAULT_COARSE_STATE
        or artifact_digest(renderer) != RENDERER_DIGEST
    ):
        return None
    return SharedGrid(
        original=original,
        native_body=inspect.unwrap(original),
        owner=owner,
        identity=signature(),
        original_state=executable(original),
    )

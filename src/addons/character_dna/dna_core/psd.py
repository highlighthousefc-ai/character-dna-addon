"""What drives each blend shape channel: raw controls, correctives (PSDs) and RBF poses.

RigLogic numbers its controls ``[raw | PSD | ML | RBF pose]``. A blend shape channel reads exactly
one control (``getBlendShapeChannelInputIndices`` -> ``OutputIndices``). A raw control is a face
expression (``CTRL_expressions.jawOpen``). A PSD ("pose space deformation", a corrective) is

    value = clamp(product(input * weight), 0, 1)

over its input controls, which are raw controls or RBF pose outputs; PSDs never read other PSDs.
Verified against RigLogic on Ada's head: max difference 7.4e-8 over 149,100 random samples, and
every PSD whose inputs are all raw controls is exactly 1 when those inputs are 1 (docs/FINDINGS).

An RBF pose control comes from bone rotations (neck), not from face expressions, so a channel
whose chain reaches one can only be activated by posing the neck. :func:`ControlGraph.activation`
therefore refuses those channels.
"""

from dataclasses import dataclass
from typing import Any


RAW = "raw"
PSD = "psd"
ML = "ml"
RBF = "rbf"


class NotActivatableError(ValueError):
    """The channel can't be switched fully on from face expressions alone."""


@dataclass(frozen=True)
class Input:
    control: int
    weight: float


@dataclass(frozen=True)
class Dependency:
    """One node of a channel's dependency tree."""

    control: int
    name: str
    kind: str
    weight: float
    inputs: tuple["Dependency", ...]


class ControlGraph:
    """The control structure of one DNA, read once from a ``dna`` reader."""

    def __init__(self, reader: Any) -> None:
        self.raw_count = reader.getRawControlCount()
        self.psd_count = reader.getPSDCount()
        self.ml_count = reader.getMLControlCount()
        self.rbf_count = reader.getRBFPoseControlCount()
        self._raw_names = [reader.getRawControlName(index) for index in range(self.raw_count)]
        self._ml_names = [reader.getMLControlName(index) for index in range(self.ml_count)]
        self._rbf_names = [reader.getRBFPoseControlName(index) for index in range(self.rbf_count)]
        self._psd_inputs: dict[int, list[Input]] = {}
        for row, column, weight in zip(
            reader.getPSDRowIndices(), reader.getPSDColumnIndices(), reader.getPSDValues(), strict=True
        ):
            self._psd_inputs.setdefault(int(row), []).append(Input(int(column), float(weight)))
        self.channel_names = [reader.getBlendShapeChannelName(i) for i in range(reader.getBlendShapeChannelCount())]
        self._channel_control = dict.fromkeys(range(len(self.channel_names)), -1)
        for control, channel in zip(
            reader.getBlendShapeChannelInputIndices(), reader.getBlendShapeChannelOutputIndices(), strict=True
        ):
            self._channel_control[int(channel)] = int(control)

    # ---------------------------------------------------------------- controls
    def kind(self, control: int) -> str:
        if control < 0:
            raise IndexError(f"Control {control} does not exist")
        for kind, end in (
            (RAW, self.raw_count),
            (PSD, self.raw_count + self.psd_count),
            (ML, self.raw_count + self.psd_count + self.ml_count),
            (RBF, self.raw_count + self.psd_count + self.ml_count + self.rbf_count),
        ):
            if control < end:
                return kind
        raise IndexError(f"Control {control} does not exist")

    def name(self, control: int) -> str:
        kind = self.kind(control)
        if kind == RAW:
            return self._raw_names[control]
        if kind == PSD:
            return f"PSD {control - self.raw_count}"
        if kind == ML:
            return self._ml_names[control - self.raw_count - self.psd_count]
        return self._rbf_names[control - self.raw_count - self.psd_count - self.ml_count]

    def inputs(self, control: int) -> list[Input]:
        """A PSD's inputs; other controls have none."""
        return list(self._psd_inputs.get(control, [])) if self.kind(control) == PSD else []

    # ---------------------------------------------------------------- channels
    def channel_control(self, channel: int) -> int:
        """The control a channel reads, or -1 when the DNA maps none to it."""
        return self._channel_control[channel]

    def dependency_tree(self, channel: int) -> Dependency | None:
        control = self.channel_control(channel)
        return None if control < 0 else self._node(control, 1.0)

    def _node(self, control: int, weight: float) -> Dependency:
        children = tuple(self._node(item.control, item.weight) for item in self.inputs(control))
        return Dependency(control, self.name(control), self.kind(control), weight, children)

    def leaves(self, channel: int) -> dict[int, str]:
        """The non-PSD controls at the bottom of a channel's chain, with their kinds."""
        control = self.channel_control(channel)
        if control < 0:
            return {}
        if self.kind(control) != PSD:
            return {control: self.kind(control)}
        return {item.control: self.kind(item.control) for item in self.inputs(control)}

    def activatable(self, channel: int) -> bool:
        leaves = self.leaves(channel)
        return bool(leaves) and all(kind == RAW for kind in leaves.values())

    def activation(self, channel: int) -> dict[int, float]:
        """Raw control values that switch ``channel`` fully on: every raw leaf at 1.

        A raw-driven channel then reads 1; a PSD reads clamp(product(1 * weight)) = 1, since every
        weight is at least 1 (Ada's are 1 and 4, checked here too).
        """
        leaves = self.leaves(channel)
        if not leaves:
            raise NotActivatableError(f'Channel "{self.channel_names[channel]}" has no driving control')
        blocked = sorted(self.name(control) for control, kind in leaves.items() if kind != RAW)
        if blocked:
            raise NotActivatableError(
                f'Channel "{self.channel_names[channel]}" also needs {", ".join(blocked)}, '
                "which come from bone rotations, not face expressions"
            )
        control = self.channel_control(channel)
        if self.kind(control) == PSD and any(item.weight < 1.0 for item in self.inputs(control)):
            raise NotActivatableError(f'Channel "{self.channel_names[channel]}" has a PSD weight below 1')
        return dict.fromkeys(leaves, 1.0)

    def value(self, control: int, raw_values: dict[int, float]) -> float:
        """A raw or PSD control's value for the given raw values (absent raw controls are 0)."""
        kind = self.kind(control)
        if kind == RAW:
            return float(raw_values.get(control, 0.0))
        if kind != PSD:
            raise NotActivatableError(f"{self.name(control)} is not computed from raw controls")
        product = 1.0
        for item in self.inputs(control):
            product *= self.value(item.control, raw_values) * item.weight
        return min(1.0, max(0.0, product))

    def channel_value(self, channel: int, raw_values: dict[int, float]) -> float:
        control = self.channel_control(channel)
        return 0.0 if control < 0 else self.value(control, raw_values)
